"""Review app frontend: static page structure, i18n keys used by the page, demo dataset end to end, pure JS logic."""
import http.client
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from openparl_extract.evaluate.gold import load_gold
from openparl_extract.evaluate.metrics import field_metrics, load_outputs
from openparl_extract.review.app import STATIC, make_server
from openparl_extract.review.demo import build_demo
from openparl_extract.review.i18n import LANGS, STRINGS

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
LOGIC = STATIC / "logic.js"
PAGE_SRC = HTML + LOGIC.read_text(encoding="utf-8")


# ---------- static structure ----------
def test_no_external_resources():
    urls = re.findall(r"https?://[^\s\"'<>)]+", PAGE_SRC)
    assert all(re.match(r"https?://(127\.0\.0\.1|localhost)([:/]|$)", u) for u in urls), urls
    for m in re.finditer(r"<(?:script|link|img)\b[^>]*\b(?:src|href)=\"([^\"]*)\"", HTML):
        assert not re.match(r"(?:[a-z]+:)?//", m.group(1)) and not m.group(1).startswith(("http", "data:")), m.group(1)
    assert "@import" not in HTML and "url(" not in HTML


def test_no_html_injection_sinks():
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in PAGE_SRC, sink


def test_uses_every_api_path_and_json_posts():
    for p in ("/api/i18n", "/api/question", "/api/answer", "/api/undo", "/api/page", "/api/blocks", "/api/progress"):
        assert p in HTML, p
    assert '"Content-Type": "application/json"' in HTML


def test_stable_test_ids():
    for i in ("start-btn", "reviewer-input", "undo-btn", "q-prompt", "answers", "btn-confirm", "btn-cancel",
              "page-prev", "page-next", "page-label", "overlay", "toast", "banner", "progress-text",
              "btn-review-unsure", "btn-start-over", "screen-start", "screen-question", "screen-done"):
        assert f'id="{i}"' in HTML and f'data-testid="{i}"' in HTML, i


def test_all_i18n_keys_used_exist():
    keys = set(re.findall(r"""\bt\(\s*["']([\w.]*\w)["']\s*\)""", PAGE_SRC))
    keys |= set(re.findall(r'data-i18n(?:-aria)?="([\w.]+)"', HTML))
    keys |= set(re.findall(r"""["']((?:btn|err|hint|page|progress|summary|toast|correction|question|pipeline|quote|"""
                           r"""reviewer|filter|lang|app)\.[\w.]*\w)["']""", PAGE_SRC))
    assert len(keys) > 25
    for lang in LANGS:
        assert not keys - set(STRINGS[lang]), (lang, keys - set(STRINGS[lang]))


# ---------- demo dataset ----------
@pytest.fixture
def demo(tmp_path):
    gold = build_demo(tmp_path)
    srv, _ = make_server(tmp_path, gold, 0, "de")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield tmp_path, gold, srv
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


def test_served_page_and_assets(demo):
    _, _, srv = demo
    s, ct, body = call(srv, "GET", "/")
    assert s == 200 and ct.startswith("text/html") and b"/static/logic.js" in body
    s, ct, body = call(srv, "GET", "/static/logic.js")
    assert s == 200 and "javascript" in ct


def test_demo_walkthrough_and_metrics(demo):
    data, gold, srv = demo
    kinds = set()
    n = 0
    while True:
        s, _, q = call(srv, "GET", "/api/question?reviewer=T&lang=it")
        assert s == 200
        if q.get("done"):
            break
        kinds.add(q["kind"])
        n += 1
        assert n < 40
        # page + blocks reachable for every question
        p = q["page"] or 1
        assert call(srv, "GET", f"/api/page?doc={q['doc_key']}&page={p}")[0] == 200
        assert call(srv, "GET", f"/api/blocks?doc={q['doc_key']}&page={p}")[2]["blocks"]
        body = {"doc": q["doc_key"], "field": q["field"], "reviewer": "T"}
        if q["pipeline_value"] is None:
            ans = ({"verdict": "wrong", "gold_value": "2024-03-21"} if q["field"] == "decision.date" else
                   {"verdict": "wrong", "gold_value": "Die Kosten betrugen im Schnitt 1,2 Millionen Franken pro Kilometer.",
                    "gold_block_id": "p2_b2"} if q["field"] == "answer:1" else {"verdict": "not_in_document"})
        elif q["field"] == "decision.outcome" and q["doc_key"] == "ZH_9001":
            ans = {"verdict": "wrong", "gold_value": "written_off"}
        else:
            ans = {"verdict": "correct"}
        s, _, r = call(srv, "POST", "/api/answer", {**body, **ans})
        assert s == 200, r
    assert kinds == {"text", "vocab", "date", "presence"}
    docs = load_gold(gold)
    assert len(docs) == 2 and all(e.verdict != "unreviewed" for d in docs for e in d.entries)
    m = field_metrics(load_outputs(data / "output"), docs)["_all"]
    assert m.fp >= 1 and m.fn >= 1 and m.tp >= 1 and m.tn >= 1 and not m.stale
    s, _, done = call(srv, "GET", "/api/question?reviewer=T&lang=en")
    assert done["done"] and done["summary"]["decision.outcome"]["wrong"] == 1


def test_demo_provenance_consistent(demo):
    data, _, _ = demo
    from openparl_extract.parse.blocks import load_parsed
    for a in load_outputs(data / "output"):
        parsed = load_parsed(data / "parsed" / a.source.body_key / a.source.openparldata_id / "parsed.json")
        blocks = {b.id: b for b in parsed.blocks}
        vals = [a.affair_text, a.addressed_body, a.decision.outcome, a.decision.date, a.decision.body,
                *(q.text for q in a.questions), *(x.text for x in a.answers)]
        for v in vals:
            for pr in v.provenance:
                b = blocks[pr.block_id]
                assert b.page == pr.page and b.text[pr.char_start:pr.char_end] == pr.quote


# ---------- pure JS logic in node ----------
@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_logic_js_in_node():
    script = f"""
const L = require({json.dumps(str(LOGIC))});
const assert = require('assert');
assert.strictEqual(L.fill('Frage {{n}} von {{total}} {{x}}', {{n: 2, total: 9}}), 'Frage 2 von 9 {{x}}');
assert.deepStrictEqual(L.scaleBox([72, 80, 300, 100], 600, 300), {{left: 36, top: 40, width: 114, height: 10}});
assert.strictEqual(L.pickLang(null, null, 'it-CH'), 'it');
assert.strictEqual(L.pickLang(null, null, 'de-AT'), 'de');
assert.strictEqual(L.pickLang(null, null, 'fr-CH'), 'en');
assert.strictEqual(L.pickLang(null, 'de', 'it'), 'de');
assert.strictEqual(L.pickLang('en', 'de', 'it'), 'en');
assert.strictEqual(L.optionClass('btn.correct'), 'ok');
assert.strictEqual(L.optionClass('btn.wrong'), 'bad');
assert.strictEqual(L.buttonLabel(0, 'Richtig'), '1  Richtig');
assert.deepStrictEqual(L.progressNumbers({{questions_done: 5, questions_total: 5, docs_done: 1, docs_total: 2}}),
                       {{n: 5, total: 5, d: 2, docs: 2}});
"""
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_inline_script_parses(tmp_path):
    js = tmp_path / "inline.js"
    js.write_text(re.findall(r"<script>(.*?)</script>", HTML, re.DOTALL)[0], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------- fix round 1: review findings ----------
def _func(name):
    m = re.search(r"function " + name + r"\(.*?\n\}\n", HTML, re.DOTALL)
    assert m, name
    return m.group(0)


def _keydown():
    i = HTML.index('document.addEventListener("keydown"')
    return HTML[i:HTML.index("\n});", i)]


def test_keydown_prevents_default_before_shortcut_and_ignores_repeat_and_ime():
    h = _keydown()
    assert re.search(r"preventDefault\(\);\s*choose\(", h)  # digit must not leak into the focused field
    assert "e.repeat" in h and h.index("e.repeat") < h.index("choose(")
    assert "isComposing" in h


def test_choose_ignores_clicks_right_after_a_question_is_shown():
    assert "Logic.tooSoon" in _func("choose") and "shownAt" in _func("showQuestion")


def test_gold_has_single_source_of_truth():
    assert 'gold-text").value = ""' in _func("selectBlock")
    assert re.search(r'\$\("gold-text"\)\.addEventListener\("input"', HTML)
    c = _func("confirmCorrection")
    assert "typed" in c and "gold_block_id" in c


def test_optional_correction_step_for_wrong_on_found_value():
    c = _func("choose")
    assert "optional" in c.lower()
    assert 'id="btn-skip"' in HTML and 'data-testid="btn-skip"' in HTML
    assert "correction.optional_title" in HTML and "btn.skip" in HTML


def test_setlang_and_loadquestion_guard_in_flight_requests():
    assert "S.busy" in _func("setLang")
    assert "qtoken" in _func("loadQuestion")


def test_narrow_header_not_sticky():
    assert re.search(r"@media \(max-width: 900px\)[^@]*header\s*\{[^}]*position:\s*static", HTML, re.DOTALL)


def test_new_i18n_keys_all_languages():
    for lang in LANGS:
        for k in ("btn.skip", "correction.optional_title"):
            assert STRINGS[lang].get(k), (lang, k)


def test_guides_describe_optional_step():
    docs = Path(__file__).resolve().parents[1] / "docs"
    assert "freiwillig" in (docs / "gold_review_anleitung.md").read_text(encoding="utf-8")
    assert "facoltativ" in (docs / "gold_review_guida.md").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_too_soon_in_node():
    script = f"const L = require({json.dumps(str(LOGIC))}); const a = require('assert');" \
             "a.strictEqual(L.tooSoon(1000, 1200), true); a.strictEqual(L.tooSoon(1000, 1500), false);" \
             "a.strictEqual(L.tooSoon(0, 5), false);"
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------- fix round 2 ----------
@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_block_repeat_in_node():
    script = f"""const L = require({json.dumps(str(LOGIC))}); const a = require('assert');
const b = (key, typing, correctionOpen, repeat = true) => L.blockRepeat({{key, typing, repeat, correctionOpen}});
a.strictEqual(b('Backspace', true, true), false);
a.strictEqual(b('a', true, false), false);
a.strictEqual(b('x', true, false), false);
a.strictEqual(b('1', false, false), true);
a.strictEqual(b('Enter', false, false), true);
a.strictEqual(b('z', false, false), true);
a.strictEqual(b('Z', false, false), true);
a.strictEqual(b('Enter', true, true), true);
a.strictEqual(b('Enter', true, false), false);
a.strictEqual(b('q', false, false), false);
a.strictEqual(b('1', false, false, false), false);
"""
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_keydown_uses_block_repeat_after_typing_is_computed():
    h = _keydown()
    assert "Logic.blockRepeat" in h and "e.repeat) {" not in h
    assert h.index("typing =") < h.index("Logic.blockRepeat")


def test_busy_is_counted_across_overlapping_requests():
    assert "S.inflight" in HTML and "setBusy(false)" not in _func("submit") and "setBusy(false)" not in _func("undo")
