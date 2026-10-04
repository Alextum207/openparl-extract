import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from openparl_extract.ingest.api import OpenParlDataClient
from openparl_extract.ingest.store import ingest_affair, load_manifest, save_affair

FIX = Path(__file__).parent / "fixtures" / "api"
PDF = (FIX / "tiny.pdf").read_bytes()


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def client(handler):
    return OpenParlDataClient(transport=httpx.MockTransport(handler), delay=0)


def page(offset, n, has_more, total=1000):
    return {"meta": {"offset": offset, "limit": n, "total_records": total, "has_more": has_more},
            "data": [{"id": offset + i} for i in range(n)]}


def test_pagination_follows_offset_and_stops():
    seen = []

    def h(req):
        o = int(req.url.params["offset"])
        seen.append(o)
        return httpx.Response(200, json=page(o, 2, o < 4))

    ids = [a["id"] for a in client(h).iter_affairs(page_size=2)]
    assert seen == [0, 2, 4] and ids == [0, 1, 2, 3, 4, 5]


def test_max_records():
    h = lambda req: httpx.Response(200, json=page(int(req.url.params["offset"]), 2, True))
    assert len(list(client(h).iter_affairs(page_size=2, max_records=3))) == 3


def test_offset_cap_stops():
    seen = []

    def h(req):
        o = int(req.url.params["offset"])
        seen.append(o)
        return httpx.Response(200, json=page(o, 50000, True, total=10**6))

    list(client(h).iter_affairs(page_size=50000))
    assert seen == [0, 50000]  # next offset 100000 is past the cap


def test_list_affairs_params():
    def h(req):
        assert req.url.params["body_key"] == "GL" and req.url.params["expand"] == "docs"
        assert req.headers["user-agent"] == "openparl-extract/0.1"
        return httpx.Response(200, json=fx("affairs_page.json"))

    assert len(client(h).list_affairs(body_key="GL", limit=3, expand_docs=True)["data"]) == 3


def test_get_affair_parses():
    h = lambda req: httpx.Response(200, json=fx("affair_340560.json"))
    a = client(h).get_affair(340560)
    assert a["id"] == 340560 and a["docs"]["data"][0]["format"] == "application/pdf"


def test_retry_once_on_5xx():
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(503) if len(n) == 1 else httpx.Response(200, json=fx("affair_340560.json"))

    assert client(h).get_affair(1)["id"] == 340560 and len(n) == 2


def test_list_bodies_paginates():
    def h(req):
        o = int(req.url.params.get("offset", 0))
        return httpx.Response(200, json=page(o, 1, o < 1))

    assert len(client(h).list_bodies()) == 2


def test_download_pdf_ok_and_rejects_non_pdf():
    assert client(lambda r: httpx.Response(200, content=PDF)).download_pdf("https://x/y") == PDF
    with pytest.raises(ValueError):
        client(lambda r: httpx.Response(200, content=b"<html>")).download_pdf("https://x/y")
    with pytest.raises(httpx.HTTPStatusError):
        client(lambda r: httpx.Response(404)).download_pdf("https://x/y")


def test_save_affair(tmp_path):
    a = fx("affair_340560.json")
    doc = a["docs"]["data"][0]
    d = save_affair(a, {doc["id"]: PDF}, tmp_path)
    assert d == tmp_path / "GL" / "340560"
    assert json.loads((d / "affair.json").read_text(encoding="utf-8"))["id"] == 340560
    assert (d / f"doc_{doc['id']}.pdf").read_bytes() == PDF
    m = load_manifest(d / "manifest.json")
    assert m["primary_doc_id"] == doc["id"] and m["flags"] == []
    e = m["docs"][0]
    assert e["pdf_sha256"] == hashlib.sha256(PDF).hexdigest()
    assert e["pdf_file"] == f"doc_{doc['id']}.pdf" and e["has_plain_text"] is True


def test_no_docs_flag_and_no_download(tmp_path):
    calls = []

    def h(req):
        calls.append(req.url.path)
        return httpx.Response(200, json=fx("affair_nodocs.json"))

    d = ingest_affair(client(h), 340560, tmp_path)
    m = load_manifest(d / "manifest.json")
    assert m["flags"] == ["no_document"] and m["primary_doc_id"] is None and m["docs"] == []
    assert not list(d.glob("*.pdf")) and len(calls) == 1


def test_no_pdf_flag(tmp_path):
    a = fx("affair_340560.json")
    a["docs"]["data"][0]["format"] = "text/html"
    m = load_manifest(save_affair(a, {}, tmp_path) / "manifest.json")
    assert m["flags"] == ["no_pdf"] and m["primary_doc_id"] is None


def test_ingest_affair_end_to_end(tmp_path):
    def h(req):
        if req.url.host == "files.openparldata.ch":
            return httpx.Response(200, content=PDF)
        return httpx.Response(200, json=fx("affair_340560.json"))

    d = ingest_affair(client(h), 340560, tmp_path)
    m = load_manifest(d / "manifest.json")
    assert m["docs"][0]["pdf_sha256"] == hashlib.sha256(PDF).hexdigest()
    assert (d / m["docs"][0]["pdf_file"]).exists()


@pytest.mark.skipif(not os.environ.get("RUN_NETWORK"), reason="set RUN_NETWORK=1 for live API")
def test_live_smoke(tmp_path):
    d = ingest_affair(OpenParlDataClient(), 340560, tmp_path)
    m = load_manifest(d / "manifest.json")
    assert m["primary_doc_id"] and m["docs"][0]["pdf_sha256"]


def test_get_affair_expands_docs_events_contributors():
    seen = {}

    def h(req):
        seen.update(req.url.params)
        return httpx.Response(200, json=fx("affair_340560.json"))

    client(h).get_affair(340560)
    assert seen["expand"] == "docs,events,contributors"


def test_ingest_stores_events_and_contributors(tmp_path):
    merge_fx = Path(__file__).parent / "fixtures" / "merge" / "zurich_city_interpellation_14228.json"
    full = json.loads(merge_fx.read_text(encoding="utf-8"))
    full["docs"]["data"] = full["docs"]["data"][:1]

    def h(req):
        return httpx.Response(200, content=PDF) if req.url.host == "files.openparldata.ch" else httpx.Response(200, json=full)

    d = ingest_affair(client(h), 14228, tmp_path)
    stored = json.loads((d / "affair.json").read_text(encoding="utf-8"))
    assert len(stored["events"]["data"]) == 3 and stored["contributors"]["data"][0]["fullname"]


def test_ingest_keeps_relation_meta(tmp_path):
    full = json.loads((Path(__file__).parent / "fixtures" / "merge" / "zh_motion_219288.json").read_text(encoding="utf-8"))
    full["events"]["meta"]["has_more"] = True
    full["docs"]["data"] = []
    d = ingest_affair(client(lambda r: httpx.Response(200, json=full)), 219288, tmp_path)
    assert json.loads((d / "affair.json").read_text(encoding="utf-8"))["events"]["meta"]["has_more"] is True
