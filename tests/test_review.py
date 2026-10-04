"""Review app backend: i18n, question builder, gold store, rendering, HTTP API, end to end."""
import http.client
import json
import re
import threading
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from openparl_extract.evaluate.gold import GoldDoc, GoldEntry, load_gold, prefill_gold
from openparl_extract.evaluate.metrics import field_metrics
from openparl_extract.models import (Affair, Answer, Decision, Provenance, Question, Source, Value)
from openparl_extract.parse.blocks import Block, ParsedDoc
from openparl_extract.review.app import make_server
from openparl_extract.review.i18n import LANGS, STRINGS, t
from openparl_extract.review.questions import FIELD_ORDER, build_question
from openparl_extract.review.render import page_blocks, page_size, render_page
from openparl_extract.review.store import GoldStore, ReviewError


# ---------- fixtures ----------
def ext(text, block="p1_b0", page=1):
    return Value[str](value=text, status="extracted", provenance=[Provenance(page=page, block_id=block, quote=text)])


NF = Value[str](status="not_found")


def mk_affair(aid, lang="de"):
    return Affair(
        source=Source(openparldata_id=aid, parliament="Zürich", body_key="ZH", level="cantonal", language=lang),
        affair_type=Value(value="motion", status="from_metadata"),
        original_type_label=Value(value="Motion", status="from_metadata"),
        affair_text=ext("Der Regierungsrat wird beauftragt."), justification=NF,
        questions=[Question(id="q1", text=ext("Wie viele Stellen?", "p1_b1"))],
        answers=[Answer(question_id="q1", text=ext("Es sind 12 Stellen.", "p2_b0", 2))],
        decision=Decision(outcome=Value(value="adopted", status="extracted",
                                        provenance=[Provenance(page=2, block_id="p2_b1", quote="angenommen")]),
                          date=Value(status="not_found"), body=NF))


def mk_pdf(path: Path, pages=2):
    c = canvas.Canvas(str(path))
    for i in range(pages):
        c.drawString(72, 700, f"Page {i + 1} Regierungsrat")
        c.showPage()
    c.save()


def mk_parsed(pages=2):
    return ParsedDoc(source_file="x.pdf", page_count=pages, is_scanned=False, blocks=[
        Block(id="p1_b0", page=1, bbox=(72, 80, 300, 100), text="Der Regierungsrat wird beauftragt.", type="paragraph"),
        Block(id="p2_b0", page=2, bbox=None, text="Es sind 12 Stellen.")])


@pytest.fixture
def env(tmp_path):
    data, gold = tmp_path / "data", tmp_path / "data" / "gold"
    for aid, lang in (("100", "de"), ("101", "it")):
        a = mk_affair(aid, lang)
        out, raw, par = (data / d / "ZH" / aid for d in ("output", "raw", "parsed"))
        for d in (out, raw, par):
            d.mkdir(parents=True)
        (out / "affair.json").write_text(a.model_dump_json(), encoding="utf-8")
        (raw / "manifest.json").write_text(json.dumps({"primary_doc_id": 7, "docs": []}), encoding="utf-8")
        mk_pdf(raw / "doc_7.pdf")
        (par / "parsed.json").write_text(mk_parsed().model_dump_json(), encoding="utf-8")
        prefill_gold(a, gold)
    return data, gold


def ge(field, pv, verdict="unreviewed"):
    return GoldEntry(field=field, pipeline_value=pv, verdict=verdict)


# ---------- i18n ----------
def test_i18n_parity():
    assert LANGS == ("de", "it", "en")
    keys = set(STRINGS["en"])
    for lang in LANGS:
        assert set(STRINGS[lang]) == keys
        assert all(v.strip() for v in STRINGS[lang].values())
    for k in keys:
        ph = {frozenset(re.findall(r"\{(\w+)\}", STRINGS[lang][k])) for lang in LANGS}
        assert len(ph) == 1, k


def test_t_fallback():
    assert t("it", "btn.yes") == "Sì"
    assert t("xx", "btn.yes") == "Yes"
    assert t("it", "no.such.key") == "no.such.key"
    assert t("de", "progress.question", n=2, total=5) == "Frage 2 von 5"


NONNULL_OPTS = [("btn.correct", "correct", False), ("btn.wrong", "wrong", False),
                ("btn.not_in_document", "not_in_document", False), ("btn.unsure", "unsure", False)]
NULL_OPTS = [("btn.no", "not_in_document", False), ("btn.yes", "wrong", True), ("btn.unsure", "unsure", False)]


# ---------- questions ----------
def test_question_builder():
    a = mk_affair("100")
    doc = GoldDoc(affair_id="100", body_key="ZH", level="cantonal", language="de")
    parsed = mk_parsed()
    q = build_question(doc, ge("affair_text", "Der Regierungsrat wird beauftragt."), a, parsed, "it")
    assert (q.kind, q.block_id, q.page, q.page_count) == ("text", "p1_b0", 1, 2)
    assert q.quote == "Der Regierungsrat wird beauftragt." and [(o.key, o.verdict, o.needs_gold) for o in q.options] == NONNULL_OPTS
    assert not q.needs_gold_on_wrong
    ans = build_question(doc, ge("answer:0", "Es sind 12 Stellen."), a, parsed, "en")
    assert ans.question_text == "Wie viele Stellen?" and ans.page == 2
    qq = build_question(doc, ge("question:q1", "Wie viele Stellen?"), a, parsed, "en")
    assert qq.block_id == "p1_b1"
    voc = build_question(doc, ge("decision.outcome", "adopted"), a, parsed, "de")
    assert (voc.kind, voc.vocab[0]) == ("vocab", "adopted") and "rejected" in voc.vocab and not voc.allow_free_text
    assert voc.block_id == "p2_b1"
    dt = build_question(doc, ge("decision.date", None), a, parsed, "de")
    assert dt.kind == "presence" and dt.value_kind == "date" and dt.needs_gold_on_wrong
    assert [(o.key, o.verdict, o.needs_gold) for o in dt.options] == NULL_OPTS and dt.block_id is None
    assert build_question(doc, ge("decision.outcome", None), a, parsed, "de").vocab
    prompts = {build_question(doc, ge("affair_text", "x"), None, None, lg).prompt for lg in LANGS}
    assert len(prompts) == 3
    assert build_question(doc, ge("affair_text", "x"), None, None, "en").block_id is None  # no affair: no provenance


def test_field_order_and_store_serves_it(tmp_path):
    assert FIELD_ORDER[0] == "affair_text" and FIELD_ORDER[-1] == "decision.body"
    doc = GoldDoc(affair_id="1", body_key="ZH", level="cantonal", language="de",
                  entries=[ge("decision.body", None), ge("answer:0", "a"), ge("question:q1", "q"),
                           ge("justification", None), ge("affair_text", "t")])
    (tmp_path / "ZH_1.json").write_text(doc.model_dump_json(), encoding="utf-8")
    s = GoldStore(tmp_path, tmp_path)
    order = []
    for _ in range(5):
        k, f = s.next_question_ref("r", None)
        order.append(f)
        s.apply_answer(k, f, "not_in_document", "r")
    assert order == ["affair_text", "question:q1", "answer:0", "justification", "decision.body"]
    assert s.next_question_ref("r", None) is None


# ---------- store ----------
def test_store_answer_persists_and_logs(env):
    data, gold = env
    s = GoldStore(gold, data)
    assert [d.doc_key for d in s.docs(None)] == ["ZH_100", "ZH_101"]
    e = s.apply_answer("ZH_100", "affair_text", "correct", "Anna")
    assert e.verdict == "correct" and e.reviewer == "Anna" and e.timestamp
    again = GoldStore(gold, data)
    assert [x for x in again.get("ZH_100").entries if x.field == "affair_text"][0].verdict == "correct"
    assert not list(gold.glob("*.tmp")) and not list(gold.glob(".*.tmp"))
    lines = [json.loads(x) for x in (gold / ".review_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    assert lines[0]["action"] == "answer" and lines[0]["before"]["verdict"] == "unreviewed"
    assert lines[0]["after"]["verdict"] == "correct" and lines[0]["doc_key"] == "ZH_100"
    assert {"ts", "reviewer", "field"} <= set(lines[0])


def test_store_validation(env):
    data, gold = env
    s = GoldStore(gold, data)
    with pytest.raises(ValueError):
        s.apply_answer("nope", "affair_text", "correct", "A")
    with pytest.raises(ValueError):
        s.apply_answer("ZH_100", "nope", "correct", "A")
    for bad in ("unreviewed", "maybe"):
        with pytest.raises(ValueError):
            s.apply_answer("ZH_100", "affair_text", bad, "A")
    with pytest.raises(ValueError):  # miss without gold
        s.apply_answer("ZH_100", "justification", "wrong", "A")
    s.apply_answer("ZH_100", "justification", "wrong", "A", gold_block_id="p1_b0")
    with pytest.raises(ValueError):
        s.apply_answer("ZH_100", "decision.outcome", "wrong", "A", gold_value="bogus")
    s.apply_answer("ZH_100", "decision.outcome", "wrong", "A", gold_value="rejected")
    for bad in ("21.03.2024", "2024-13-40", "2024-3-1"):
        with pytest.raises(ValueError):
            s.apply_answer("ZH_100", "decision.date", "wrong", "A", gold_value=bad)
    s.apply_answer("ZH_100", "decision.date", "wrong", "A", gold_value="2024-03-21")
    # non-null + wrong needs no gold value
    assert s.apply_answer("ZH_100", "affair_text", "wrong", "A").verdict == "wrong"


def test_unsure_queue_and_progress(env):
    data, gold = env
    s = GoldStore(gold, data)
    assert s.next_question_ref("A", None) == ("ZH_100", "affair_text")
    s.apply_answer("ZH_100", "affair_text", "unsure", "A")
    assert s.next_question_ref("A", None) == ("ZH_100", "question:q1")
    assert s.progress("A", None) == {"docs_total": 2, "docs_done": 0, "questions_total": 18,
                                     "questions_done": 0, "questions_unsure": 1}
    assert [d.doc_key for d in s.docs({"it"})] == ["ZH_101"]
    assert s.progress("A", {"it"})["questions_total"] == 9
    for d in s.docs(None):
        for f in [e.field for e in s.get(d.doc_key).entries]:
            if (d.doc_key, f) != ("ZH_100", "affair_text"):
                s.apply_answer(d.doc_key, f, "not_in_document", "A")
    assert s.next_question_ref("A", None) is None
    assert s.next_question_ref("A", None, include_unsure=True) == ("ZH_100", "affair_text")
    assert s.progress("A", None)["docs_done"] == 1  # only ZH_101 fully settled
    assert s.summary(None)["affair_text"]["not_in_document"] == 1


def test_undo_per_reviewer(env):
    data, gold = env
    s = GoldStore(gold, data)
    assert s.undo("A") is None
    s.apply_answer("ZH_100", "affair_text", "correct", "A")
    s.apply_answer("ZH_100", "question:q1", "wrong", "B")
    s.apply_answer("ZH_100", "answer:0", "correct", "A")
    r = s.undo("A")
    assert r.field == "answer:0" and r.verdict == "unreviewed" and r.reviewer is None
    assert s.get("ZH_100").entries[[e.field for e in s.get("ZH_100").entries].index("question:q1")].verdict == "wrong"
    assert s.undo("A").field == "affair_text"
    assert s.undo("A") is None
    assert s.undo("B").field == "question:q1"
    acts = [json.loads(x)["action"] for x in (gold / ".review_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert acts == ["answer"] * 3 + ["undo"] * 3
    assert GoldStore(gold, data).undo("A") is None  # stack derived from the log, survives restart


def test_reread_on_mtime_change(env):
    data, gold = env
    s1, s2 = GoldStore(gold, data), GoldStore(gold, data)
    s1.get("ZH_100")
    s2.apply_answer("ZH_100", "affair_text", "correct", "A")
    assert s1.get("ZH_100").entries[0].verdict == "correct"


def test_concurrent_answers(env):
    data, gold = env
    s = GoldStore(gold, data)
    fields = ["affair_text", "question:q1", "answer:0", "decision.outcome"]

    def work(f):
        for i in range(26):
            s.apply_answer("ZH_100", f, "correct" if i % 2 else "unsure", "A")

    th = [threading.Thread(target=work, args=(f,)) for f in fields]
    [x.start() for x in th]
    [x.join() for x in th]
    doc = GoldDoc.model_validate_json((gold / "ZH_100.json").read_text(encoding="utf-8"))
    got = {e.field: e.verdict for e in doc.entries}
    assert all(got[f] == "correct" for f in fields)
    assert len((gold / ".review_log.jsonl").read_text(encoding="utf-8").splitlines()) == 104


# ---------- render ----------
def test_render(env):
    data, _ = env
    pdf = data / "raw" / "ZH" / "100" / "doc_7.pdf"
    assert render_page(pdf, 1)[:8] == b"\x89PNG\r\n\x1a\n"
    assert render_page(pdf, 1, 1.5) == render_page(pdf, 1, 1.5)  # cached path
    for bad in (0, 3):
        with pytest.raises(ValueError):
            render_page(pdf, bad)
    w, h = page_size(pdf, 2)
    assert 500 < w < 700 and 700 < h < 900
    bl = page_blocks(mk_parsed(), 1)
    assert bl == [{"id": "p1_b0", "bbox": (72, 80, 300, 100), "text": "Der Regierungsrat wird beauftragt.",
                   "type": "paragraph"}]
    assert page_blocks(mk_parsed(), 2)[0]["bbox"] is None


# ---------- http ----------
@pytest.fixture
def server(env):
    data, gold = env
    srv, url = make_server(data, gold, 0, "de")
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv, url
    srv.shutdown()
    srv.server_close()


def call(srv, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    c.request(method, path, json.dumps(body) if body is not None else None,
              {"Content-Type": "application/json"} if body is not None else {})
    r = c.getresponse()
    raw = r.read()
    c.close()
    ct = r.getheader("Content-Type")
    return r.status, ct, (json.loads(raw) if ct.startswith("application/json") else raw)


def test_server_bound_local(server):
    srv, url = server
    assert srv.server_address[0] == "127.0.0.1" and url.startswith("http://127.0.0.1:")


def test_static_and_traversal(server):
    srv, _ = server
    s, ct, b = call(srv, "GET", "/")
    assert s == 200 and ct.startswith("text/html") and b"/api/i18n" in b
    assert call(srv, "GET", "/static/index.html")[0] == 200
    for p in ("/static/..%2f..%2fpyproject.toml", "/static/../app.py", "/static/nope.js", "/static/%2fetc%2fpasswd",
              "/static/..%5capp.py"):
        assert call(srv, "GET", p)[0] in (400, 404), p
    assert call(srv, "GET", "/nothing")[0] == 404


def test_api_flow(server):
    srv, _ = server
    s, _, i18n = call(srv, "GET", "/api/i18n?lang=it")
    assert s == 200 and i18n["btn.yes"] == "Sì"
    assert call(srv, "GET", "/api/i18n?lang=zz")[2]["btn.yes"] == "Yes"
    s, _, docs = call(srv, "GET", "/api/docs?languages=it")
    assert [d["doc_key"] for d in docs] == ["ZH_101"] and docs[0]["n_entries"] == 9
    s, _, p = call(srv, "GET", "/api/progress?reviewer=Anna")
    assert p["questions_total"] == 18 and p["questions_done"] == 0
    s, _, q = call(srv, "GET", "/api/question?reviewer=Anna&lang=it")
    assert (q["doc_key"], q["field"], q["kind"]) == ("ZH_100", "affair_text", "text")
    assert q["prompt"] == STRINGS["it"]["q.affair_text"] and q["page_count"] == 2
    s, _, e = call(srv, "POST", "/api/answer", {"doc": "ZH_100", "field": "affair_text", "verdict": "correct",
                                                "reviewer": "Anna"})
    assert s == 200 and e["verdict"] == "correct" and e["reviewer"] == "Anna"
    q2 = call(srv, "GET", "/api/question?reviewer=Anna&lang=de")[2]
    assert q2["field"] == "question:q1"
    back = call(srv, "GET", "/api/question?doc=ZH_100&field=affair_text&lang=en")[2]
    assert back["field"] == "affair_text" and back["pipeline_value"]
    assert call(srv, "GET", "/api/progress?reviewer=Anna")[2]["questions_done"] == 1
    s, _, r = call(srv, "POST", "/api/undo", {"reviewer": "Anna"})
    assert s == 200 and r["field"] == "affair_text" and r["verdict"] == "unreviewed"
    assert call(srv, "POST", "/api/undo", {"reviewer": "Anna"})[0] == 404
    s, _, bl = call(srv, "GET", "/api/blocks?doc=ZH_100&page=1")
    assert s == 200 and bl["blocks"][0]["id"] == "p1_b0" and bl["width"] > 0 and bl["height"] > 0
    s, ct, png = call(srv, "GET", "/api/page?doc=ZH_100&page=2&scale=1")
    assert s == 200 and ct == "image/png" and png[:4] == b"\x89PNG"


def test_api_errors(server, env):
    srv, _ = server
    data, gold = env
    s, _, e = call(srv, "POST", "/api/answer", {"doc": "ZH_100", "field": "justification", "verdict": "wrong",
                                                "reviewer": "A", "lang": "it"})
    assert s == 400 and e["error"] == STRINGS["it"]["err.gold_required"]
    for body in ({"doc": "ZH_100", "field": "affair_text", "verdict": "nope", "reviewer": "A"},
                 {"doc": "../x", "field": "affair_text", "verdict": "correct", "reviewer": "A"},
                 {"doc": "ZH_100", "field": "affair_text", "verdict": "correct", "reviewer": "\x00\x01"},
                 {"doc": "ZH_100"}):
        s, _, e = call(srv, "POST", "/api/answer", body)
        assert s == 400 and "error" in e
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    c.request("POST", "/api/answer", "not json", {"Content-Type": "application/json"})
    assert c.getresponse().status == 400
    for p in ("/api/page?doc=../../x&page=1", "/api/page?doc=ZH_100%2f..&page=1", "/api/blocks?doc=nope&page=1",
              "/api/question?doc=nope&field=affair_text"):
        assert call(srv, "GET", p)[0] == 404, p
    assert call(srv, "GET", "/api/page?doc=ZH_100&page=99")[0] == 400
    assert call(srv, "GET", "/api/page?doc=ZH_100&page=abc")[0] == 400
    # missing pdf / parsed -> clear 404, question still works
    (data / "raw" / "ZH" / "101" / "doc_7.pdf").unlink()
    (data / "parsed" / "ZH" / "101" / "parsed.json").unlink()
    s, _, e = call(srv, "GET", "/api/page?doc=ZH_101&page=1")
    assert s == 404 and "error" in e
    assert call(srv, "GET", "/api/blocks?doc=ZH_101&page=1")[0] == 404
    assert call(srv, "GET", "/api/question?doc=ZH_101&field=affair_text")[0] == 200


def test_end_to_end(server, env):
    srv, _ = server
    data, gold = env
    n = 0
    while True:
        s, _, q = call(srv, "GET", "/api/question?reviewer=Anna&lang=it")
        if q.get("done"):
            break
        verdict = "not_in_document" if q["kind"] == "presence" else "correct"
        assert call(srv, "POST", "/api/answer", {"doc": q["doc_key"], "field": q["field"], "verdict": verdict,
                                                 "reviewer": "Anna"})[0] == 200
        n += 1
    assert n == 18
    assert q["summary"]["affair_text"]["correct"] == 2 and q["summary"]["decision.date"]["not_in_document"] == 2
    p = call(srv, "GET", "/api/progress?reviewer=Anna")[2]
    assert (p["docs_done"], p["questions_done"], p["questions_unsure"]) == (2, 18, 0)
    gdocs = load_gold(gold)
    assert len(gdocs) == 2 and all(e.verdict != "unreviewed" and e.reviewer == "Anna"
                                   for d in gdocs for e in d.entries)
    affairs = [mk_affair("100"), mk_affair("101", "it")]
    m = field_metrics(affairs, gdocs)["_all"]
    assert (m.tp, m.fp, m.fn, m.tn, m.n_reviewed) == (8, 0, 0, 10, 18) and not m.stale


def raw(srv, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    h = {"Host": f"127.0.0.1:{srv.server_address[1]}", **(headers or {})}
    for k, v in h.items():
        c.putheader(k, v)
    data = body.encode() if isinstance(body, str) else body
    if data is not None and "Content-Length" not in h:
        c.putheader("Content-Length", str(len(data)))
    c.endheaders(data)
    r = c.getresponse()
    out = r.read()
    c.close()
    return r.status, out


ANS = {"doc": "ZH_100", "field": "affair_text", "verdict": "correct", "reviewer": "A"}
JSONH = {"Content-Type": "application/json"}


def test_host_origin_content_type(server):
    srv, _ = server
    port = srv.server_address[1]
    assert raw(srv, "GET", "/api/progress", headers={"Host": "evil.example:80"})[0] == 403
    assert raw(srv, "GET", "/api/progress", headers={"Host": "attacker.com"})[0] == 403
    assert raw(srv, "GET", "/api/progress", headers={"Host": f"localhost:{port}"})[0] == 200
    body = json.dumps(ANS)
    assert raw(srv, "POST", "/api/answer", body, {"Content-Type": "text/plain"})[0] in (400, 415)
    assert raw(srv, "POST", "/api/answer", body)[0] in (400, 415)
    assert raw(srv, "POST", "/api/answer", body, {**JSONH, "Origin": "http://evil.example"})[0] == 403
    assert raw(srv, "POST", "/api/answer", body, {**JSONH, "Origin": f"http://127.0.0.1:{port}"})[0] == 200
    assert raw(srv, "POST", "/api/answer", body, {"Content-Type": "application/json; charset=utf-8"})[0] == 200


def test_bad_content_length(server):
    srv, _ = server
    assert raw(srv, "POST", "/api/answer", "{}", {**JSONH, "Content-Length": "-5"})[0] == 400


@pytest.mark.parametrize("extra", [{"gold_value": {"a": 1}}, {"note": [1]}, {"gold_block_id": 5},
                                   {"note": "x" * 501}, {"gold_value": "x" * 5001}, {"reviewer": 7},
                                   {"verdict": ["correct"]}])
def test_non_string_fields_rejected(server, env, extra):
    srv, _ = server
    _, gold = env
    s, _, e = call(srv, "POST", "/api/answer", {**ANS, "verdict": "wrong", **extra})
    assert s == 400 and "error" in e
    assert len(load_gold(gold)) == 2
    assert call(srv, "GET", "/api/question?doc=ZH_100&field=affair_text")[0] == 200


def test_static_drive_letter(server):
    srv, _ = server
    for p in ("/static/D:x", "/static/C:index.html", "/static/..%2f"):
        assert call(srv, "GET", p)[0] == 404, p


def test_undo_conflict_and_vanished(env):
    data, gold = env
    s = GoldStore(gold, data)
    s.apply_answer("ZH_100", "affair_text", "correct", "A")
    s.apply_answer("ZH_100", "affair_text", "wrong", "B")
    with pytest.raises(ReviewError) as ei:
        s.undo("A")
    assert ei.value.key == "err.undo_conflict"
    assert s.get("ZH_100").entries[0].verdict == "wrong" and s.get("ZH_100").entries[0].reviewer == "B"
    assert len((gold / ".review_log.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert s.undo("B").verdict == "correct"  # B's own undo still works
    s.apply_answer("ZH_100", "question:q1", "correct", "C")
    d = s.get("ZH_100")
    d.entries = [e for e in d.entries if e.field != "question:q1"]
    (gold / "ZH_100.json").write_text(d.model_dump_json(), encoding="utf-8")
    with pytest.raises(ReviewError):
        s.undo("C")


def test_undo_conflict_http(server):
    srv, _ = server
    call(srv, "POST", "/api/answer", ANS)
    call(srv, "POST", "/api/answer", {**ANS, "reviewer": "B", "verdict": "unsure"})
    s, _, e = call(srv, "POST", "/api/undo", {"reviewer": "A", "lang": "it"})
    assert s == 409 and e["error"] == STRINGS["it"]["err.undo_conflict"]


def test_concurrent_render_and_blocks(server):
    srv, _ = server
    errs = []

    def work(i):
        for j in range(5):
            if (i + j) % 2:
                p = "/api/page?doc=ZH_100&page=%d&scale=1" % (1 + j % 2)
            else:
                p = "/api/blocks?doc=ZH_100&page=1"
            st = call(srv, "GET", p)[0]
            if st != 200:
                errs.append(st)

    th = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    [x.start() for x in th]
    [x.join() for x in th]
    assert not errs


def test_correct_on_null_rejected(env):
    data, gold = env
    s = GoldStore(gold, data)
    with pytest.raises(ReviewError) as ei:
        s.apply_answer("ZH_100", "decision.date", "correct", "A")
    assert ei.value.key == "err.invalid_verdict"


def test_correct_on_null_http(server):
    srv, _ = server
    s, _, e = call(srv, "POST", "/api/answer", {**ANS, "field": "decision.date", "lang": "de"})
    assert s == 400 and e["error"] == STRINGS["de"]["err.invalid_verdict"]


def test_unknown_block(server):
    srv, _ = server
    s, _, e = call(srv, "POST", "/api/answer", {**ANS, "verdict": "wrong", "gold_block_id": "p9_b9", "lang": "en"})
    assert s == 400 and e["error"] == STRINGS["en"]["err.unknown_block"]
    assert call(srv, "POST", "/api/answer", {**ANS, "verdict": "wrong", "gold_block_id": "p1_b0"})[0] == 200


def test_unknown_block_skipped_without_parsed(server, env):
    srv, _ = server
    data, _ = env
    (data / "parsed" / "ZH" / "101" / "parsed.json").unlink()
    assert call(srv, "POST", "/api/answer", {**ANS, "doc": "ZH_101", "verdict": "wrong",
                                             "gold_block_id": "whatever"})[0] == 200


def test_clean_reviewer():
    from openparl_extract.review.app import ApiError, clean_reviewer
    assert clean_reviewer("  Anna‮​ ") == "Anna"
    assert clean_reviewer("Bo⁦b") == "Bob"
    for bad in ("‮​", "   ", None):
        with pytest.raises(ApiError):
            clean_reviewer(bad)


def test_i18n_plural_keys_and_wording():
    for lg in LANGS:
        assert "{n}" in STRINGS[lg]["summary.unsure_many"] and "{n}" not in STRINGS[lg]["summary.unsure_one"]
        assert STRINGS[lg]["err.undo_conflict"] and STRINGS[lg]["err.unknown_block"]
    assert STRINGS["de"]["lang.it"] == "Italienisch"


def test_cli_registered_before_main_guard():
    src = (Path(__file__).parent.parent / "src/openparl_extract/cli.py").read_text(encoding="utf-8")
    assert src.index("def review(") < src.index('if __name__ == "__main__"')


def test_cli_review_needs_gold(tmp_path):
    from typer.testing import CliRunner
    from openparl_extract.cli import app
    r = CliRunner().invoke(app, ["review", "--data-dir", str(tmp_path), "--no-open"])
    assert r.exit_code == 1 and "gold-prefill" in r.output and "pick-corpus" in r.output


def test_cache_sees_rewrite_with_same_mtime(env):
    import os
    data, gold = env
    s = GoldStore(gold, data)
    p = gold / "ZH_100.json"
    s.get("ZH_100")
    st = p.stat()
    d = GoldDoc.model_validate_json(p.read_text(encoding="utf-8"))
    d.entries = d.entries[:-1]
    p.write_text(d.model_dump_json(), encoding="utf-8")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))  # coarse-timestamp filesystem: same mtime
    assert len(s.get("ZH_100").entries) == len(d.entries)
