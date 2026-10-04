"""CLI end to end with the mock LLM. API served by httpx.MockTransport, PDF built with reportlab."""
import io
import json
import shutil
from pathlib import Path

import httpx
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from typer.testing import CliRunner

from openparl_extract import cli
from openparl_extract.config import Config
from openparl_extract.evaluate.gold import GoldDoc, entries_for_affair, save_gold
from openparl_extract.extract.llm_client import MockLLMClient, load_client
from openparl_extract.ingest.api import OpenParlDataClient
from openparl_extract.models import Affair
from openparl_extract.parse.blocks import load_parsed

FIX = Path(__file__).parent / "fixtures" / "api"
runner = CliRunner()
CFG = Config("http://x/v1", "none", "apertus-8b", "http://api.test", "apertus")


def make_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    pages = [
        [("Helvetica-Bold", 16, "Interpellation betreffend Velowege"), ("Helvetica", 11, "Eingereicht von Hans Muster."),
         ("Helvetica-Bold", 14, "Fragen"),
         ("Helvetica", 11, "1. Wie viele Velowege gibt es im Kanton?"),
         ("Helvetica", 11, "2. Plant der Regierungsrat einen Ausbau?")],
        [("Helvetica-Bold", 14, "Antwort des Regierungsrates"),
         ("Helvetica", 11, "Zu Frage 1: Es gibt 120 Kilometer Velowege."),
         ("Helvetica-Bold", 14, "Beschluss"),
         ("Helvetica", 11, "Die Interpellation ist erledigt.")]]
    for n, lines in enumerate(pages, 1):
        c.setFont("Helvetica", 9)
        c.drawString(60, 810, "Kanton Glarus Parlament")
        c.drawString(280, 30, f"Seite {n}")
        y = 740
        for font, size, text in lines:
            c.setFont(font, size)
            c.drawString(60, y, text)
            y -= 50
        c.showPage()
    c.save()
    return buf.getvalue()


def affairs():
    base = json.loads((FIX / "affair_340560.json").read_text(encoding="utf-8"))
    base["docs"]["data"][0].update(id=1, url_oparl="https://files.test/doc/1.pdf")
    base["docs"]["data"][0].pop("text", None)
    nodocs = json.loads((FIX / "affair_nodocs.json").read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(nodocs))
    base["id"], nodocs["id"], bad["id"] = 1001, 1002, 1003
    bad["title"] = {}  # no language can be determined -> merge raises ValueError
    bad["title_long"] = {}
    return {1001: base, 1002: nodocs, 1003: bad}


BODY = {"id": 258, "body_key": "GL", "name": {"de": "Glarus"}, "type": "canton", "canton_key": "GL",
        "country_key": "CHE", "lang": "DE"}
PDF = make_pdf()


def handler(req: httpx.Request) -> httpx.Response:
    p, A = req.url.path, affairs()
    if req.url.host == "files.test":
        return httpx.Response(200, content=PDF)
    if p == "/v1/bodies/":
        return httpx.Response(200, json={"data": [BODY], "meta": {"has_more": False}})
    if p == "/v1/affairs/":
        return httpx.Response(200, json={"data": [A[1001], A[1002]], "meta": {"has_more": False}})
    return httpx.Response(200, json=A[int(p.rsplit("/", 1)[1])])


def patch_api(mp):
    mp.setattr(cli, "make_api_client",
               lambda config: OpenParlDataClient(transport=httpx.MockTransport(handler), delay=0))


@pytest.fixture(autouse=True)
def api(monkeypatch):
    patch_api(monkeypatch)


def run(*args, ok=True):
    r = runner.invoke(cli.app, [str(a) for a in args])
    if ok:
        assert r.exit_code == 0, r.output
    return r


@pytest.fixture(scope="module")
def parsed_data(tmp_path_factory):
    """ingest + parse + segment once (Docling is slow)."""
    d = tmp_path_factory.mktemp("cli") / "data"
    with pytest.MonkeyPatch.context() as mp:
        patch_api(mp)
        run("ingest", "1001", "1002", "1003", "--data-dir", d)
        run("parse", "--all", "--data-dir", d)
        run("segment", "--all", "--data-dir", d)
    return d


@pytest.fixture
def work(parsed_data, tmp_path):
    d = tmp_path / "data"
    shutil.copytree(parsed_data, d)
    return d


def doc_of(data: Path):
    return load_parsed(data / "parsed/GL/1001/parsed.json")


def block_with(doc, needle):
    return next(b for b in doc.blocks if needle in b.text)


def item(doc, needle, value=None):
    return {"value": value or needle, "block_id": block_with(doc, needle).id, "quote": needle}


def fixtures_for(data: Path) -> dict:
    doc = doc_of(data)
    return {
        "questions": {"questions": [
            {"id": "q1", "text": item(doc, "Wie viele Velowege gibt es im Kanton?")},
            {"id": "q2", "text": item(doc, "Plant der Regierungsrat einen Ausbau?")}]},
        "answers": {"answers": [{"question_id": "q1", "text": item(doc, "Es gibt 120 Kilometer Velowege.")}]},
        "decision": {"decision": {"outcome": item(doc, "Die Interpellation ist erledigt.", "written_off"),
                                  "date": {}, "body": {}}}}


def write_fx(data: Path, fx: dict) -> Path:
    p = data.parent / "fx.json"
    p.write_text(json.dumps(fx), encoding="utf-8")
    return p


def pipeline(data: Path, fx: dict):
    f = write_fx(data, fx)
    run("extract", "--all", "--mock-fixtures", f, "--data-dir", data)
    run("verify", "--all", "--data-dir", data)
    run("merge", "1001", "--data-dir", data)
    return Affair.model_validate_json((data / "output/GL/1001/affair.json").read_text(encoding="utf-8"))


def test_ingest_writes_raw_and_bodies(tmp_path):
    run("ingest", "1001", "--data-dir", tmp_path)
    d = tmp_path / "raw/GL/1001"
    assert (d / "affair.json").exists() and (d / "manifest.json").exists() and (d / "doc_1.pdf").read_bytes() == PDF
    assert json.loads((tmp_path / "raw/bodies.json").read_text(encoding="utf-8"))[0]["body_key"] == "GL"


def test_ingest_by_body_key_only_affairs_with_docs(tmp_path):
    r = run("ingest", "--body-key", "GL", "--limit", "5", "--data-dir", tmp_path)
    assert (tmp_path / "raw/GL/1001/affair.json").exists() and not (tmp_path / "raw/GL/1002").exists()
    assert "ingest" in r.output


def test_parse_and_segment_files(parsed_data):
    doc = doc_of(parsed_data)
    assert doc.blocks and not (parsed_data / "parsed/GL/1002").exists()  # no PDF -> nothing written
    seg = json.loads((parsed_data / "segmented/GL/1001/segments.json").read_text(encoding="utf-8"))
    bs = seg["block_section"]
    assert bs[block_with(doc, "Wie viele Velowege").id] == "questions"
    assert bs[block_with(doc, "120 Kilometer").id] == "executive_answer"
    assert bs[block_with(doc, "ist erledigt").id] == "decision"
    assert not (parsed_data / "output/errors.jsonl").exists()


def test_extract_verify_merge_valid_affair_with_provenance(work):
    a = pipeline(work, fixtures_for(work))
    doc = doc_of(work)
    assert [q.text.status for q in a.questions] == ["extracted", "extracted"]
    assert a.answers[0].text.status == "extracted" and a.decision.outcome.status == "extracted"
    for v in (a.questions[0].text, a.answers[0].text, a.decision.outcome):
        p = v.provenance[0]
        b = next(b for b in doc.blocks if b.id == p.block_id)
        assert b.text[p.char_start:p.char_end] == p.quote
    assert a.source.level.value == "cantonal" and a.title.status == "from_metadata"


def test_run_all_matches_stepwise_and_is_idempotent(work, tmp_path):
    expected = pipeline(work, fixtures_for(work)).model_dump_json()
    d = tmp_path / "ra"
    shutil.copytree(work / "raw", d / "raw")
    f = write_fx(d, fixtures_for(work))
    args = ["run-all", "1001", "--skip-ingest", "--mock-fixtures", f, "--data-dir", d]
    run(*args)
    out = d / "output/GL/1001/affair.json"
    assert Affair.model_validate_json(out.read_text(encoding="utf-8")).model_dump_json() == expected
    r = run(*args)
    assert "parse: 0 done, 1 skipped" in r.output and "merge: 0 done, 1 skipped" in r.output
    r = run(*args, "--force")
    assert "merge: 1 done, 0 skipped" in r.output


def test_no_pdf_affair_yields_metadata_only(work):
    run("merge", "1002", "--data-dir", work)
    a = Affair.model_validate_json((work / "output/GL/1002/affair.json").read_text(encoding="utf-8"))
    assert "no_document" in a.review_flags and "no_extraction" in a.review_flags
    assert a.title.status == "from_metadata" and not a.questions
    assert not (work / "output/errors.jsonl").exists()


def test_batch_failure_is_logged_and_others_complete(work):
    pipeline(work, fixtures_for(work))
    (work / "output/GL/1001/affair.json").unlink()
    r = run("merge", "--all", "--data-dir", work)  # 1003 has no determinable language
    assert (work / "output/GL/1001/affair.json").exists() and (work / "output/GL/1002/affair.json").exists()
    rows = [json.loads(x) for x in (work / "output/errors.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(x["affair_id"], x["stage"], x["error_type"]) for x in rows] == [("1003", "merge", "ValueError")]
    assert "1 failed" in r.output
    assert run("merge", "1003", "--data-dir", work, "--force", ok=False).exit_code == 1  # explicit id failed


def test_evaluate_with_and_without_gold(work):
    a = pipeline(work, fixtures_for(work))
    r = run("evaluate", "--data-dir", work, "--out", work / "rep0")
    assert (work / "rep0/feasibility_matrix.md").exists() and "feasibility_matrix.md" in r.output
    entries = entries_for_affair(a)
    for e in entries:
        e.verdict = "correct"
    save_gold(GoldDoc(affair_id="1001", body_key="GL", level="cantonal", language="de", entries=entries),
              work / "gold")
    r = run("evaluate", "--data-dir", work, "--gold-dir", work / "gold", "--out", work / "rep")
    for f in ("metrics.json", "feasibility_matrix.md"):
        assert (work / "rep" / f).exists()
    assert "precision" in r.output and "recall" in r.output and "hallucination_rate" in r.output


def test_export_schema(tmp_path):
    out = tmp_path / "s" / "affair.json"
    run("export-schema", "--out", out)
    assert "properties" in json.loads(out.read_text(encoding="utf-8"))


def test_load_client():
    assert isinstance(load_client(CFG, mock=True), MockLLMClient)
    with pytest.raises(RuntimeError, match="provided by the Apertus integration"):
        load_client(CFG)
    assert isinstance(load_client(Config("", "", "", "", "mock")), MockLLMClient)


def test_hallucinated_quote_is_flagged(work):
    fx = fixtures_for(work)
    fx["questions"]["questions"][0]["text"].update(quote="Dieser Text steht nirgends im Dokument",
                                                    value="Dieser Text steht nirgends im Dokument")
    a = pipeline(work, fx)
    assert a.questions[0].text.status == "not_found" and a.questions[0].text.value is None
    assert any(f.startswith("quote_not_found") for f in a.review_flags)
