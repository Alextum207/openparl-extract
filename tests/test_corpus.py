"""Corpus picker with a hand-built API (httpx.MockTransport): no network."""
import json

import httpx

from openparl_extract.evaluate.corpus import (
    CorpusEntry,
    choose_doc,
    format_summary,
    load_corpus,
    pick_corpus,
    write_corpus,
)
from openparl_extract.ingest.api import OpenParlDataClient


def doc(i, text=None, fmt="application/pdf", url=True, lang=None):
    return {"id": i, "format": fmt, "url_oparl": f"https://files.test/doc/{i}.pdf" if url else None,
            "text": text, "language": lang, "name": f"d{i}"}


def test_choose_doc():
    q = "Fragen\n1. Wie viele?\n" + "x" * 300
    ans = "Antwort des Regierungsrates\nZu Frage 1: so viele.\n" + "x" * 300
    assert choose_doc([doc(1, q), doc(2, ans)])["id"] == 2  # answer heading beats earlier doc
    assert choose_doc([doc(1, fmt="text/html"), doc(2, fmt="text/html")]) is None
    assert choose_doc([]) is None
    assert choose_doc([doc(1, url=False, text=ans)]) is None  # no url_oparl
    assert choose_doc([doc(1, ""), doc(2, None)])["id"] == 1  # empty text docs: tie -> earliest
    assert choose_doc([doc(1, None), doc(2, "irgendein Text ohne Ueberschrift")])["id"] == 2  # non-empty +1
    assert choose_doc([doc(1, "Text a"), doc(2, "Text b")])["id"] == 1  # tie -> earliest
    long = "Antwort des Regierungsrates " + "wort " * 40  # > 120 chars on one line: not a heading
    assert choose_doc([doc(1, "Beschluss\nok"), doc(2, long)])["id"] == 1


# ---- hand-built API ----
BODIES = [
    {"body_key": "CHE", "name": {"de": "Bund"}, "type": "country", "country_key": "CHE", "lang": None},
    {"body_key": "ZH", "name": {"de": "Zuerich"}, "type": "canton", "country_key": "CHE", "lang": "DE"},
    {"body_key": "BE", "name": {"de": "Bern"}, "type": "canton", "country_key": "CHE", "lang": "DE"},
    {"body_key": "GE", "name": {"de": "Genf", "fr": "Geneve"}, "type": "canton", "country_key": "CHE", "lang": "FR"},
    {"body_key": "VD", "name": {"fr": "Vaud"}, "type": "canton", "country_key": "CHE", "lang": "FR"},
    {"body_key": "TI", "name": {"it": "Ticino"}, "type": "canton", "country_key": "CHE", "lang": "IT"},
    {"body_key": "351", "name": {"de": "Bern"}, "type": "city", "country_key": "CHE", "lang": "DE"},
    {"body_key": "6621", "name": {"fr": "Geneve"}, "type": "city", "country_key": "CHE", "lang": "FR"},
    {"body_key": "5192", "name": {"it": "Lugano"}, "type": "municipality", "country_key": "CHE", "lang": "IT"},
    {"body_key": "4551", "name": {"de": "Aadorf"}, "type": "municipality", "country_key": "CHE", "lang": "DE",
     "indexed": False},
    {"body_key": "XX", "name": {"de": "Kaputt"}, "type": "canton", "country_key": "CHE", "lang": "DE"},
    {"body_key": "AUT", "name": {"de": "Oesterreich"}, "type": "country", "country_key": "AUT", "lang": None},
]
TYPES = [8, 3, 2, 12, 9, 8, 12, 2]
N_PER_BODY = 24


def affair(bk, i, lang):
    n = i + 1
    done = n % 3 != 0
    txt = "" if n % 4 == 0 else ("Antwort des Regierungsrates\nText. " + "wort " * 60)
    return {"id": hash_id(bk, i), "body_key": bk, "number": f"{bk}-{i}", "title": {lang: f"Titel {i}"},
            "type_harmonized_id": TYPES[i % len(TYPES)], "type_name": {lang: "Vorstoss"},
            "state_name": {lang: "Erledigt" if done else "InBearbeitung"}, "end_date": None,
            "docs": {"data": [doc(hash_id(bk, i) * 10, None, lang=lang), doc(hash_id(bk, i) * 10 + 1, txt, lang=lang)]}}


def hash_id(bk, i):
    return (sum(map(ord, bk)) % 97) * 1000 + i


class Api:
    def __init__(self):
        self.calls = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls += 1
        p, q = req.url.path, dict(req.url.params)
        if p == "/v1/bodies/":
            return httpx.Response(200, json={"data": BODIES, "meta": {"has_more": False}})
        bk = q["body_key"]
        if bk == "XX":
            return httpx.Response(404, json={})
        off, lim = int(q["offset"]), int(q["limit"])
        lang = (next(b["lang"] for b in BODIES if b["body_key"] == bk) or "de").lower()
        rows = []
        for i in range(off, min(off + lim, N_PER_BODY)):
            lg = ("de", "fr", "it")[i % 3] if bk == "CHE" else lang
            a = affair(bk, i, lg)
            rows.append(a)
        return httpx.Response(200, json={"data": rows, "meta": {"has_more": off + lim < N_PER_BODY}})


def client(api=None):
    return OpenParlDataClient(base_url="http://api.test", transport=httpx.MockTransport(api or Api()), delay=0)


def run(seed=7, n=18, **kw):
    api = Api()
    entries, summary = pick_corpus(client(api), n_total=n, seed=seed, page_size=8, **kw)
    return entries, summary, api


def test_pick_corpus_quotas_and_summary():
    entries, s, _ = run()
    assert 0 < len(entries) <= 18
    lv = {k: sum(e.level.value == k for e in entries) for k in ("federal", "cantonal", "municipal")}
    assert lv["federal"] <= 3 and lv["cantonal"] <= 9 and lv["municipal"] <= 6
    assert lv["cantonal"] == 9 and lv["federal"] == 3 and lv["municipal"] == 6  # data is rich enough
    assert s["level"] == lv and sum(s["language"].values()) == len(entries)
    assert {e.body_key for e in entries}.isdisjoint({"AUT", "4551"})  # foreign country, not indexed
    assert all(e.lifecycle_complete for e in entries) and all(e.doc_id for e in entries)
    assert len({e.affair_id for e in entries}) == len(entries)
    assert sum(e.scanned_guess for e in entries) >= 2 and s["scanned_guess"] == sum(e.scanned_guess for e in entries)
    assert max(s["affair_type"].values()) <= 0.4 * 18 + 1
    # chosen doc: the one with text (second doc), scanned ones have empty text
    assert all(e.doc_id % 10 == 1 or e.scanned_guess for e in entries)
    assert "federal" in format_summary(s) and "unmet" in format_summary(s)


def test_determinism_and_seed():
    a, _, _ = run(7)
    b, _, _ = run(7)
    c, _, _ = run(8)
    assert [e.model_dump() for e in a] == [e.model_dump() for e in b]
    assert [e.affair_id for e in a] != [e.affair_id for e in c]


def test_max_requests_and_unmet():
    entries, s, api = run(max_requests=3)
    assert api.calls <= 3
    assert len(entries) < 18 and s["unmet"]


def test_body_failure_recorded_and_not_fatal():
    entries, s, _ = run()
    entries, s, _ = run(n=36, max_requests=300)
    assert any(e["body_key"] == "XX" for e in s["errors"]) and entries


def test_write_load_roundtrip(tmp_path):
    entries, s, _ = run()
    p = tmp_path / "c.json"
    write_corpus(p, entries, s)
    e2, s2 = load_corpus(p)
    assert [e.model_dump() for e in e2] == [e.model_dump() for e in entries] and s2 == json.loads(json.dumps(s))
    assert isinstance(e2[0], CorpusEntry)


# ---- ingest_affair(primary_doc_id) ----
def two_pdf_handler(downloads):
    def h(req):
        if req.url.host == "files.test":
            downloads.append(req.url.path)
            return httpx.Response(200, content=b"%PDF-1.4 x")
        return httpx.Response(200, json={"id": 5, "body_key": "ZH", "title": {"de": "T"},
                                         "docs": {"data": [doc(1), doc(2), doc(3, fmt="text/html")]}})
    return h


def test_ingest_primary_doc_downloads_only_that_pdf(tmp_path):
    from openparl_extract.ingest.store import ingest_affair, load_manifest
    dl: list[str] = []
    d = ingest_affair(client(two_pdf_handler(dl)), 5, tmp_path, primary_doc_id=2)
    assert dl == ["/doc/2.pdf"] and load_manifest(d / "manifest.json")["primary_doc_id"] == 2
    assert (d / "doc_2.pdf").exists() and not (d / "doc_1.pdf").exists()


def test_ingest_primary_doc_first_pdf_and_default(tmp_path):
    from openparl_extract.ingest.store import ingest_affair, load_manifest
    dl: list[str] = []
    d = ingest_affair(client(two_pdf_handler(dl)), 5, tmp_path, primary_doc_id=1)
    assert load_manifest(d / "manifest.json")["primary_doc_id"] == 1 and sorted(dl) == ["/doc/1.pdf", "/doc/2.pdf"]
    d = ingest_affair(client(two_pdf_handler([])), 5, tmp_path)
    assert load_manifest(d / "manifest.json")["primary_doc_id"] == 1


def test_ingest_primary_doc_wrong_id(tmp_path):
    import pytest

    from openparl_extract.ingest.store import ingest_affair
    for bad in (3, 99):  # html doc, unknown doc
        with pytest.raises(ValueError):
            ingest_affair(client(two_pdf_handler([])), 5, tmp_path, primary_doc_id=bad)


# ---- duplicates: overlapping random offsets, same affair in two bodies ----
SMALL = [b for b in BODIES if b["body_key"] in ("ZH", "BE")]


def small_handler(req):
    if req.url.path == "/v1/bodies/":
        return httpx.Response(200, json={"data": SMALL, "meta": {"has_more": False}})
    q = dict(req.url.params)
    off, lim, bk = int(q["offset"]), int(q["limit"]), q["body_key"]
    rows = []
    for i in range(off, min(off + lim, 60)):  # 60 rows only: random offsets overlap heavily
        a = affair(bk, i, "de")
        a["id"] = 5000 + i  # SAME ids in both bodies -> cross-body duplicates
        a["docs"]["data"][0]["id"], a["docs"]["data"][1]["id"] = a["id"] * 10, a["id"] * 10 + 1
        rows.append(a)
    return httpx.Response(200, json={"data": rows, "meta": {"has_more": off + lim < 60, "total_records": 60}})


def test_no_duplicate_affairs_small_overlapping_bodies():
    c = OpenParlDataClient(base_url="http://api.test", transport=httpx.MockTransport(small_handler), delay=0)
    entries, s = pick_corpus(c, n_total=9, seed=3, page_size=50, pages_per_body=3)
    ids = [e.affair_id for e in entries]
    assert len(ids) == len(set(ids)) and s["n"] == len(ids) == sum(s["level"].values())
    assert sum(s["language"].values()) == sum(s["affair_type"].values()) == len(ids)
    assert s["duplicates_skipped"] > 0 and "duplicates_skipped" in format_summary(s)


def test_select_skips_duplicate_pool_entries():
    import random

    from openparl_extract.evaluate.corpus import Cand, _select
    e = CorpusEntry(affair_id=1, body_key="ZH", level="cantonal", language="de", affair_type="motion", doc_id=1,
                    n_pdf_docs=1, has_plain_text=True, scanned_guess=False, lifecycle_complete=True, reason="")
    cell = ("cantonal", "de")
    out = _select({cell: [Cand(e, 1, 0), Cand(e, 1, 1)]}, {cell: 2}, 2, random.Random(1))
    assert [x.affair_id for x in out] == [1]
