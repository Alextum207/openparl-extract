"""Evaluate: gold format, metrics (hand-computed), feasibility matrix."""
import json
from datetime import date

import pandas as pd
import pytest

from openparl_extract.evaluate.gold import GoldDoc, GoldEntry, entries_for_affair, load_gold, save_gold
from openparl_extract.evaluate.matrix import Thresholds, build_matrix, classify, matrix_wide, write_matrix
from openparl_extract.evaluate.metrics import (aggregate_provenance, field_metrics, flag_rates, group_metrics,
                                               load_outputs, provenance_validity, values_match, write_report)
from openparl_extract.extract.schemas import ExtractedItem, ExtractedQuestion, ExtractionResult
from openparl_extract.models import (Actor, Affair, Answer, Decision, Provenance, Question, Reference, Source, Value)
from openparl_extract.parse.blocks import Block
from openparl_extract.verify.verify import verify


def ext(text):
    return Value[str](value=text, status="extracted",
                      provenance=[Provenance(page=1, block_id="p1_b0", quote=text)])


NF = Value[str](status="not_found")


def mk(aid, text=None, level="cantonal", lang="de", parl="ZH", **kw):
    return Affair(
        source=Source(openparldata_id=aid, parliament=parl, level=level, language=lang),
        affair_type=Value(value="motion", status="from_metadata"),
        original_type_label=Value(value="Motion", status="from_metadata"),
        affair_text=ext(text) if text else NF, **kw)


def gd(aid, entries, level="cantonal", lang="de", parl="ZH", **kw):
    return GoldDoc(affair_id=aid, body_key=parl, level=level, language=lang, entries=entries, **kw)


def ge(key, pv, verdict, gold_value=None):
    return GoldEntry(field=key, pipeline_value=pv, verdict=verdict, gold_value=gold_value)


def text_fixture():
    # (pipeline value, verdict)
    rows = [("A", "correct"), ("B", "correct"), ("C", "wrong"), ("D", "not_in_document"),
            (None, "wrong"), (None, "not_in_document"), (None, "not_in_document"),
            ("E", "unsure"), ("F", "unreviewed")]
    affairs = [mk(f"a{i}", v) for i, (v, _) in enumerate(rows)]
    gold = [gd(f"a{i}", [ge("affair_text", v, vd)]) for i, (v, vd) in enumerate(rows)]
    return affairs, gold


# ---------- gold ----------
def test_entries_for_affair_one_per_question_and_answer():
    a = mk("x", "T", questions=[Question(id="q1", text=ext("Why?")), Question(id="q2", text=NF)],
           answers=[Answer(question_id="q1", text=ext("Because."))],
           decision=Decision(outcome=Value(value="adopted", status="extracted",
                                           provenance=[Provenance(page=1, block_id="b", quote="q")]),
                             date=Value[date](value=date(2024, 1, 2), status="from_metadata"),
                             body=Value[str](status="not_found")))
    got = {e.field: e for e in entries_for_affair(a)}
    assert set(got) == {"affair_text", "justification", "executive_reasoning", "addressed_body",
                        "decision.outcome", "decision.date", "decision.body",
                        "question:q1", "question:q2", "answer:0"}
    assert got["affair_text"].pipeline_value == "T"
    assert got["justification"].pipeline_value is None
    assert got["question:q2"].pipeline_value is None
    assert got["answer:0"].pipeline_value == "Because."
    assert got["decision.outcome"].pipeline_value == "adopted"
    assert got["decision.date"].pipeline_value == "2024-01-02"
    assert got["decision.body"].pipeline_value is None
    assert all(e.verdict == "unreviewed" for e in got.values())


def test_entries_for_affair_without_decision():
    got = {e.field: e.pipeline_value for e in entries_for_affair(mk("x"))}
    assert got["decision.outcome"] is None and "question:q1" not in got


def test_gold_round_trip(tmp_path):
    d = gd("77", [ge("affair_text", "x", "wrong", "y")], is_scanned=True, affair_type="motion")
    save_gold(d, tmp_path)
    assert (tmp_path / "ZH_77.json").exists()
    assert load_gold(tmp_path) == [d]


# ---------- field metrics ----------
def test_field_metrics_hand_computed():
    affairs, gold = text_fixture()
    m = field_metrics(affairs, gold)["affair_text"]
    # TP=2 (A,B) FP=2 (C wrong, D hallucinated) FN=1 (null but wrong) TN=2; E unsure, F unreviewed excluded
    assert (m.tp, m.fp, m.fn, m.tn) == (2, 2, 1, 2)
    assert m.precision == pytest.approx(2 / 4)
    assert m.recall == pytest.approx(2 / 3)
    assert m.f1 == pytest.approx(4 / 7)  # 2*.5*(2/3)/(.5+2/3)
    assert m.not_found_correctness == pytest.approx(2 / 3)  # TN/(TN+FN)
    assert m.hallucination_rate == pytest.approx(1 / 4)  # 1 not_in_document / 4 non-null reviewed
    assert m.n_reviewed == 7 and m.n_unsure_or_unreviewed == 2
    assert m.stale == []


def test_zero_division_gives_none():
    affairs = [mk("a")]
    gold = [gd("a", [ge("affair_text", None, "not_in_document")])]
    m = field_metrics(affairs, gold)["affair_text"]
    assert (m.tp, m.fp, m.fn, m.tn) == (0, 0, 0, 1)
    assert m.precision is None and m.recall is None and m.f1 is None and m.hallucination_rate is None
    assert m.not_found_correctness == 1.0


def test_stale_entry_excluded_and_reported():
    affairs = [mk("a", "new value")]
    gold = [gd("a", [ge("affair_text", "old value", "correct")])]
    m = field_metrics(affairs, gold)["affair_text"]
    assert m.stale == ["a|affair_text"] and m.tp == 0 and m.n_reviewed == 0


def test_question_answer_collapse_to_families():
    a = mk("a", questions=[Question(id="q1", text=ext("Q?"))], answers=[Answer(text=ext("A."))])
    g = gd("a", [ge("question:q1", "Q?", "correct"), ge("answer:0", "A.", "wrong")])
    m = field_metrics([a], [g])
    assert set(m) == {"questions", "answers", "_all"}
    assert m["questions"].tp == 1 and m["answers"].fp == 1


def test_values_match_and_near_miss():
    assert values_match("The quick brown fox jumps", "The quick   brown fox jumps.", 90)
    assert not values_match("abc", "xyz", 90)
    a = mk("a", "The quick brown fox jumps")
    g = gd("a", [ge("affair_text", "The quick brown fox jumps", "wrong", "The quick brown fox jumps.")])
    assert field_metrics([a], [g])["affair_text"].near_miss == 1


def test_group_metrics_split_by_level():
    affairs, gold = [], []
    for i, (lvl, v, vd) in enumerate([("federal", "A", "correct"), ("federal", "B", "correct"),
                                      ("cantonal", "C", "correct"), ("cantonal", "D", "wrong")]):
        affairs.append(mk(f"a{i}", v, level=lvl))
        gold.append(gd(f"a{i}", [ge("affair_text", v, vd)], level=lvl))
    df = group_metrics(affairs, gold, "level")
    r = df.set_index(["field", "group"])
    assert r.loc[("affair_text", "federal"), "precision"] == 1.0
    assert r.loc[("affair_text", "cantonal"), "precision"] == 0.5


# ---------- provenance ----------
def test_provenance_validity_with_real_verify():
    blocks = [Block(id="p1_b0", page=1, text="Der Regierungsrat wird gebeten, Bericht zu erstatten.")]
    raw = ExtractionResult(
        affair_text=ExtractedItem(value="Der Regierungsrat wird gebeten", block_id="p1_b0",
                                  quote="Der Regierungsrat wird gebeten"),
        justification=ExtractedItem(value="Invented", block_id="p1_b0", quote="Totally invented sentence here"),
        executive_reasoning=ExtractedItem(value="x", block_id="p9_b9", quote="x"),
        questions=[ExtractedQuestion(id="q1", text=ExtractedItem(value="Was?", block_id="p1_b0", quote=None))])
    ps = provenance_validity(raw, verify(raw, blocks))
    assert ps.n_values == 4 and ps.n_valid == 1
    assert ps.failures["quote_not_found"] == 1 and ps.failures["block_not_found"] == 1
    assert ps.failures["missing_quote"] == 1
    assert ps.validity == 0.25
    agg = aggregate_provenance([ps, ps])
    assert agg.n_values == 8 and agg.n_valid == 2 and agg.validity == 0.25
    assert provenance_validity(ExtractionResult(), verify(ExtractionResult(), blocks)).validity is None


# ---------- flag rates ----------
def test_flag_rates_prefix_handling():
    a1 = mk("1", review_flags=["unmapped_event:xyz", "unmapped_event:abc", "segmentation_failed"], parl="ZH")
    a2 = mk("2", parl="ZH")
    a3 = mk("3", review_flags=["no_document"], parl="BE", level="federal")
    df = flag_rates([a1, a2, a3])
    zh = df[(df.group_type == "parliament") & (df.group == "ZH")].iloc[0]
    assert zh.n_affairs == 2 and zh["unmapped_event"] == 0.5 and zh["segmentation_failed"] == 0.5
    assert zh["no_document"] == 0
    fed = df[(df.group_type == "level") & (df.group == "federal")].iloc[0]
    assert fed["no_document"] == 1.0


def test_load_outputs(tmp_path):
    d = tmp_path / "ZH" / "1"
    d.mkdir(parents=True)
    (d / "affair.json").write_text(mk("1", "T").model_dump_json(), encoding="utf-8")
    assert [a.source.openparldata_id for a in load_outputs(tmp_path)] == ["1"]


# ---------- matrix ----------
TH = Thresholds()


def test_classify_boundaries():
    assert classify(0.8, 0.8, 10, TH) == "consistent"
    assert classify(0.8, None, 10, TH) == "consistent"
    assert classify(0.79, None, 10, TH) == "partial"
    assert classify(0.9, 0.79, 10, TH) == "partial"
    assert classify(0.2, None, 10, TH) == "partial"
    assert classify(0.19, None, 10, TH) == "not_representable"
    assert classify(1.0, 1.0, 2, TH) == "insufficient_data"
    assert classify(1.0, 1.0, 3, TH) == "consistent"


def corpus():
    affairs = []
    for lvl, lang in [("federal", "de"), ("cantonal", "fr"), ("municipal", "de")]:
        for i in range(4):
            kw = {}
            if lvl == "federal":
                kw["actors"] = [Actor(name=ext("Meier"), role=Value(value="submitter", status="from_metadata"))]
                kw["annexes"] = [Reference(page=3)]
            affairs.append(mk(f"{lvl}{i}", "Text" if lvl != "municipal" or i == 0 else None,
                              level=lvl, lang=lang, parl=lvl.upper(), **kw))
    return affairs


def test_matrix_classifications_and_verified():
    affairs = corpus()
    gold = [gd(a.source.openparldata_id, [ge("affair_text", "Text", "correct")], level="federal", parl="FEDERAL")
            for a in affairs if a.source.level == "federal"]  # 4 reviewed entries on federal
    df = build_matrix(affairs, gold, Thresholds(min_gold_n=4))
    c = df.set_index(["field", "group_type", "group"])
    fed = c.loc[("affair_text", "level", "federal")]
    assert fed.classification == "consistent" and fed.verified and fed.f1 == 1.0 and fed.n_gold == 4
    mun = c.loc[("affair_text", "level", "municipal")]  # availability 1/4 -> partial, no gold
    assert mun.availability == 0.25 and mun.classification == "partial" and not mun.verified and pd.isna(mun.f1)
    assert c.loc[("actors.submitter", "level", "federal"), "classification"] == "consistent"
    assert c.loc[("actors.submitter", "level", "cantonal"), "classification"] == "not_representable"
    assert c.loc[("annexes", "language", "fr"), "classification"] == "not_representable"
    assert c.loc[("affair_text", "language", "rm"), "classification"] == "insufficient_data"
    assert c.loc[("affair_text", "parliament", "FEDERAL"), "n_affairs"] == 4
    wide = matrix_wide(df)
    assert wide.loc["affair_text", "federal"] == "consistent"  # verified: no star
    assert wide.loc["affair_text", "municipal"] == "partial*"
    assert wide.loc["actors.submitter", "cantonal"] == "not_representable"
    assert wide.loc["actors.submitter", "federal"] == "consistent*"


def test_write_matrix_and_report(tmp_path):
    affairs, gold = text_fixture()
    write_matrix(tmp_path, affairs, gold, TH)
    assert (tmp_path / "feasibility_matrix.csv").exists()
    assert pd.read_csv(tmp_path / "feasibility_matrix_long.csv").columns.tolist() == [
        "field", "group_type", "group", "n_affairs", "availability", "f1", "n_gold", "classification", "verified"]
    md = (tmp_path / "feasibility_matrix.md").read_text(encoding="utf-8")
    assert "| field |" in md and "min_gold_n" in md and "segmentation_failed" in md
    out = tmp_path / "rep"
    write_report(out, affairs, gold)
    for f in ("metrics.json", "metrics_by_field.csv", "metrics_by_group.csv", "flag_rates.csv", "provenance.json"):
        assert (out / f).exists()
    assert json.loads((out / "metrics.json").read_text())["affair_text"]["tp"] == 2
    assert "precision" in pd.read_csv(out / "metrics_by_field.csv").columns


# ---------- body_key grouping (fix round 1) ----------
def mk_bk(aid, parl, bk, text="T", level="federal", lang="de", flags=()):
    a = mk(aid, text, level=level, lang=lang, parl=parl, review_flags=list(flags))
    a.source.body_key = bk
    return a


def multiling():
    return [mk_bk("1", "Bundesversammlung", "CHE", lang="de", flags=["segmentation_failed"]),
            mk_bk("2", "Assemblée fédérale", "CHE", lang="fr"),
            mk_bk("3", "Assemblea federale", "CHE", lang="it")]


def test_matrix_one_column_per_body_key():
    df = build_matrix(multiling(), [])
    p = df[df.group_type == "parliament"]
    assert set(p.group) == {"CHE"} and set(p.n_affairs) == {3}


def test_flag_rates_and_group_metrics_share_parliament_keys():
    affairs = multiling()
    gold = [gd(a.source.openparldata_id, [ge("affair_text", "T", "correct")], level="federal", parl="CHE")
            for a in affairs]
    fr = flag_rates(affairs)
    assert set(fr[fr.group_type == "parliament"].group) == {"CHE"}
    gm = group_metrics(affairs, gold, "parliament")
    assert set(gm.group) == {"CHE"}


def test_group_metrics_prefers_affair_attributes():
    a = mk_bk("1", "Bundesversammlung", "CHE")
    g = gd("1", [ge("affair_text", "T", "correct")], level="municipal", parl="STALE")  # wrong copies on the doc
    assert set(group_metrics([a], [g], "parliament").group) == {"CHE"}
    assert set(group_metrics([a], [g], "level").group) == {"federal"}


def test_fallback_to_parliament_name_when_no_body_key():
    a = mk("1", "T", parl="Zürich")
    assert set(flag_rates([a]).query("group_type == 'parliament'").group) == {"Zürich"}
    assert set(build_matrix([a], []).query("group_type == 'parliament'").group) == {"Zürich"}


def test_all_headline_numbers():
    affairs, gold = text_fixture()
    m = field_metrics(affairs, gold)["_all"]
    # same fixture as the affair_text test: TP=2 FP=2 FN=1 TN=2
    assert (m.tp, m.fp, m.fn, m.tn) == (2, 2, 1, 2)
    assert m.f1 == pytest.approx(4 / 7) and m.hallucination_rate == pytest.approx(0.25)
    assert m.not_found_correctness == pytest.approx(2 / 3)
