"""openparl-extract CLI: thin typer wrappers around pipeline.py. Every stage reads/writes JSON under --data-dir."""
import json
from pathlib import Path
from typing import Optional

import typer

from openparl_extract import pipeline as pl
from openparl_extract.config import Config, load_config
from openparl_extract.evaluate.corpus import format_summary, load_corpus, pick_corpus, write_corpus
from openparl_extract.evaluate.gold import load_gold
from openparl_extract.evaluate.matrix import write_matrix
from openparl_extract.evaluate.metrics import (ProvenanceStats, aggregate_provenance, load_outputs,
                                               provenance_validity, write_report)
from openparl_extract.extract.llm_client import load_client
from openparl_extract.extract.schemas import ExtractionResult
from openparl_extract.ingest.api import OpenParlDataClient
from openparl_extract.models import export_schema
from openparl_extract.verify.verify import VerifiedParts

app = typer.Typer(help="Parliamentary affairs: PDF -> schema with provenance.", no_args_is_help=True)

IDS = typer.Argument(None, help="Affair ids (default: use --body-key or --all)")
DATA = typer.Option(Path("data"), "--data-dir", help="Root of raw/parsed/.../output")


def make_api_client(config: Config) -> OpenParlDataClient:
    return OpenParlDataClient(base_url=config.api_base)


def _echo(s: pl.Summary) -> None:
    typer.echo(s.line())


def _fail(msg: str) -> "typer.Exit":
    typer.echo(f"error: {msg}", err=True)
    return typer.Exit(1)


def _keys(data: Path, ids, body_key, all_) -> tuple[list[pl.Key], list[str]]:
    if not (ids or body_key or all_):
        raise _fail("give AFFAIR_ID(s), --body-key or --all")
    missing: list[str] = []
    return pl.select(data, ids, body_key, missing), missing


def _run(data, stage, ids, body_key, all_, force, **kw) -> pl.Summary:
    keys, missing = _keys(data, ids, body_key, all_)
    s = pl.run_stage(data, stage, keys, force, **kw)
    for i in missing:  # explicit id that was never ingested
        pl.log_error(data, ("", i), stage, FileNotFoundError(f"affair {i} not in {data}/raw"))
    s.failed += len(missing)
    _echo(s)
    if s.exit_code(bool(ids)):
        raise typer.Exit(1)
    return s


def _stage(stage: str):
    def cmd(ids: Optional[list[str]] = IDS, body_key: Optional[str] = typer.Option(None, "--body-key"),
            all_: bool = typer.Option(False, "--all"), force: bool = typer.Option(False, "--force"),
            data_dir: Path = DATA):
        _run(data_dir, stage, ids, body_key, all_, force)
    cmd.__doc__ = f"Run the {stage} stage (skips existing outputs unless --force)."
    app.command(stage)(cmd)


for _s in ("parse", "segment", "verify", "merge"):
    _stage(_s)


def _client(mock: bool, fixtures: Optional[Path]):
    try:
        fx = json.loads(fixtures.read_text(encoding="utf-8")) if fixtures else None
        return load_client(load_config(), mock=mock or fx is not None, mock_fixtures=fx)
    except (RuntimeError, OSError, ValueError) as e:
        raise _fail(str(e))


@app.command()
def ingest(ids: Optional[list[str]] = IDS, body_key: Optional[str] = typer.Option(None, "--body-key"),
           limit: Optional[int] = typer.Option(None, "--limit", help="default 10 (all corpus entries with --corpus)"),
           offset: int = typer.Option(0, "--offset"), force: bool = typer.Option(False, "--force"),
           corpus: Optional[Path] = typer.Option(None, "--corpus", help="corpus.json from pick-corpus"),
           data_dir: Path = DATA):
    """Fetch affairs (explicit ids, a body_key listing, or a --corpus file) into data/raw."""
    if corpus:
        try:
            entries, _ = load_corpus(corpus)
        except (OSError, ValueError) as e:
            raise _fail(f"cannot read corpus {corpus}: {e}")
        s = pl.ingest_corpus(make_api_client(load_config()), data_dir, entries[offset:][:limit], force)
        _echo(s)
        if s.exit_code(False):
            raise typer.Exit(1)
        return
    if not (ids or body_key):
        raise _fail("give AFFAIR_ID(s), --body-key or --corpus")
    s = pl.ingest(make_api_client(load_config()), data_dir, ids, body_key, limit or 10, offset, force)
    _echo(s)
    if s.exit_code(bool(ids)):
        raise typer.Exit(1)


MOCK = typer.Option(False, "--mock", help="Use MockLLMClient")
FIXTURES = typer.Option(None, "--mock-fixtures", help='JSON {group: payload} for the mock')


@app.command()
def extract(ids: Optional[list[str]] = IDS, body_key: Optional[str] = typer.Option(None, "--body-key"),
            all_: bool = typer.Option(False, "--all"), force: bool = typer.Option(False, "--force"),
            mock: bool = MOCK, mock_fixtures: Optional[Path] = FIXTURES,
            model: Optional[str] = typer.Option(None, "--model", help="default: LLM_MODEL"),
            max_chars: int = typer.Option(12000, "--max-chars"), data_dir: Path = DATA):
    """Run the LLM extraction per field group."""
    _run(data_dir, "extract", ids, body_key, all_, force, client=_client(mock, mock_fixtures),
         model=model or load_config().llm_model, max_chars=max_chars)


@app.command("run-all")
def run_all(ids: Optional[list[str]] = IDS, body_key: Optional[str] = typer.Option(None, "--body-key"),
            limit: int = typer.Option(10, "--limit"), force: bool = typer.Option(False, "--force"),
            skip_ingest: bool = typer.Option(False, "--skip-ingest"), mock: bool = MOCK,
            mock_fixtures: Optional[Path] = FIXTURES, model: Optional[str] = typer.Option(None, "--model"),
            max_chars: int = typer.Option(12000, "--max-chars"), data_dir: Path = DATA):
    """ingest (unless --skip-ingest or already in data/raw) then every stage, per affair."""
    if not (ids or body_key):
        raise _fail("give AFFAIR_ID(s) or --body-key")
    summaries: list[pl.Summary] = []
    if skip_ingest:
        keys, missing = _keys(data_dir, ids, body_key, False)
        for i in missing:
            pl.log_error(data_dir, ("", i), "ingest", FileNotFoundError(f"affair {i} not in {data_dir}/raw"))
    else:
        s = pl.ingest(make_api_client(load_config()), data_dir, ids, body_key, limit, 0, False)
        _echo(s)
        summaries.append(s)
        keys, missing = s.keys, []
    client = _client(mock, mock_fixtures)
    kw = {"extract": dict(client=client, model=model or load_config().llm_model, max_chars=max_chars)}
    summaries += [pl.run_stage(data_dir, st, keys, force, **kw.get(st, {})) for st in pl.STAGES]
    for s in summaries[len(summaries) - len(pl.STAGES):]:
        _echo(s)
    bad = sum(s.failed for s in summaries) + len(missing)
    if bad and (bool(ids) or not any(s.done or s.skipped for s in summaries[-1:])):
        raise typer.Exit(1)


@app.command()
def evaluate(data_dir: Path = DATA, gold_dir: Optional[Path] = typer.Option(None, "--gold-dir", help="default <data-dir>/gold"),
             out: Optional[Path] = typer.Option(None, "--out", help="default data/reports")):
    """Metrics report and feasibility matrix for data/output against the gold set (may be empty)."""
    gold_dir, out = gold_dir or data_dir / "gold", out or Path("data/reports")
    out_dir = data_dir / "output"
    affairs = load_outputs(out_dir)
    gold = load_gold(gold_dir) if gold_dir.exists() else []
    stats = []
    for p in sorted(out_dir.glob("*/*/affair.json")):
        key = (p.parent.parent.name, p.parent.name)
        ext, ver = (pl._read(pl.path(data_dir, d, key, f), m) for d, f, m in
                    (("extracted", "extraction.json", ExtractionResult), ("verified", "verified.json", VerifiedParts)))
        if ext and ver:
            stats.append(provenance_validity(ext, ver))
    write_report(out, affairs, gold, aggregate_provenance(stats) if stats else ProvenanceStats())
    write_matrix(out, affairs, gold)
    a = json.loads((out / "metrics.json").read_text(encoding="utf-8")).get("_all", {})
    f = lambda k: "n/a" if a.get(k) is None else f"{a[k]:.2f}"  # noqa: E731
    typer.echo(f"evaluate: {len(affairs)} affairs, {len(gold)} gold docs; precision={f('precision')} "
               f"recall={f('recall')} hallucination_rate={f('hallucination_rate')}")
    typer.echo(f"feasibility matrix: {out / 'feasibility_matrix.md'}")


@app.command("pick-corpus")
def pick_corpus_cmd(n: int = typer.Option(45, "--n"), seed: int = typer.Option(7, "--seed"),
                    max_requests: int = typer.Option(300, "--max-requests"),
                    out: Path = typer.Option(Path("data/corpus.json"), "--out")):
    """Pick stratified gold-set candidates (level x language x scanned x type) from the live API."""
    entries, summary = pick_corpus(make_api_client(load_config()), n, seed, max_requests)
    write_corpus(out, entries, summary)
    typer.echo(format_summary(summary))
    typer.echo(f"corpus written: {out}")


@app.command("gold-prefill")
def gold_prefill(data_dir: Path = DATA,
                 gold_dir: Optional[Path] = typer.Option(None, "--gold-dir", help="default <data-dir>/gold")):
    """Draft gold files from data/output; existing entries (reviewed ones too) are never overwritten."""
    c = pl.prefill_all(data_dir, gold_dir or data_dir / "gold")
    typer.echo(f"gold-prefill: {c['created']} created, {c['extended']} extended, {c['unchanged']} untouched")


@app.command("export-schema")
def export_schema_cmd(out: Path = typer.Option(Path("schema/affair.v0.1.json"), "--out")):
    """Write the JSON Schema of the Affair model."""
    export_schema(out)
    typer.echo(f"schema written: {out}")


if __name__ == "__main__":
    app()
