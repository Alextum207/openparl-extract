"""Per-stage runners. Each stage reads the previous stage's JSON and writes its own under data/<stage dir>/<body_key>/<id>/."""
import json
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path

from openparl_extract.extract.runner import extract_affair
from openparl_extract.extract.schemas import ExtractionResult
from openparl_extract.ingest.api import OpenParlDataClient
from openparl_extract.ingest.store import _docs, ingest_affair, load_manifest
from openparl_extract.merge.merge import _language, merge_affair
from openparl_extract.parse.blocks import ParsedDoc, save_parsed
from openparl_extract.segment.rules import SegmentResult, segment
from openparl_extract.verify.verify import VerifiedParts, verify

Key = tuple[str, str]  # (body_key, affair_id)
# stage -> (output dir, output file)
OUT = {"parse": ("parsed", "parsed.json"), "segment": ("segmented", "segments.json"),
       "extract": ("extracted", "extraction.json"), "verify": ("verified", "verified.json"),
       "merge": ("output", "affair.json")}
STAGES = tuple(OUT)


def path(data: Path, stage_dir: str, key: Key, name: str) -> Path:
    return Path(data) / stage_dir / key[0] / key[1] / name


def log_error(data: Path, key: Key, stage: str, e: Exception) -> None:
    p = Path(data) / "output" / "errors.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"affair_id": key[1], "body_key": key[0], "stage": stage,
                             "error_type": type(e).__name__, "message": str(e)}, ensure_ascii=False) + "\n")


@dataclass
class Summary:
    stage: str
    done: int = 0
    skipped: int = 0
    failed: int = 0
    keys: list[Key] = field(default_factory=list)

    def line(self) -> str:
        return f"{self.stage}: {self.done} done, {self.skipped} skipped, {self.failed} failed"

    def exit_code(self, explicit: bool) -> int:
        return 1 if self.failed and (explicit or not (self.done or self.skipped)) else 0


def select(data: Path, ids: list[str] | None = None, body_key: str | None = None,
           missing: list[str] | None = None) -> list[Key]:
    """Affairs present in data/raw. Ids not found are appended to `missing`."""
    found = sorted((p.parent.parent.name, p.parent.name) for p in (Path(data) / "raw").glob("*/*/affair.json"))
    if ids:
        by_id = {k[1]: k for k in found}
        if missing is not None:
            missing += [i for i in ids if i not in by_id]
        return [by_id[i] for i in ids if i in by_id]
    return [k for k in found if body_key is None or k[0] == body_key]


# ---------- ingest ----------
def save_bodies(client: OpenParlDataClient, data: Path) -> None:
    p = Path(data) / "raw" / "bodies.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(client.list_bodies(), ensure_ascii=False, indent=2), encoding="utf-8")


def ingest(client: OpenParlDataClient, data: Path, ids: list[str] | None = None, body_key: str | None = None,
           limit: int = 10, offset: int = 0, force: bool = False) -> Summary:
    s = Summary("ingest")
    raw = Path(data) / "raw"
    if ids:
        wanted = [str(i) for i in ids]
    else:  # ponytail: lists with expand=docs and filters client-side; fine for samples, not for bulk
        wanted = [str(a["id"]) for a in islice((a for a in client.iter_affairs(body_key, expand_docs=True) if _docs(a)),
                                               offset, offset + limit)]
    for aid in wanted:
        have = next(iter(raw.glob(f"*/{aid}/affair.json")), None)
        try:
            if have and not force:
                key, s.skipped = (have.parent.parent.name, aid), s.skipped + 1
            else:
                d = ingest_affair(client, aid, raw)
                key, s.done = (d.parent.name, d.name), s.done + 1
            s.keys.append(key)
        except Exception as e:
            log_error(data, ("", aid), "ingest", e)
            s.failed += 1
    if s.done or not (raw / "bodies.json").exists():
        save_bodies(client, data)
    return s


# ---------- stages ----------
def _read(p: Path, model):
    return model.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None


def _write(p: Path, model) -> bool:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return True


def _parse(data, key, out, **_):
    raw = path(data, "raw", key, "")
    m = load_manifest(raw / "manifest.json")
    pdf = next((d["pdf_file"] for d in m["docs"] if d["doc_id"] == m["primary_doc_id"]), None)
    if not pdf:
        return False  # no_document / no_pdf: nothing to parse, merge emits a metadata-only Affair
    from openparl_extract.parse.docling_parse import parse_pdf  # heavy import, only when needed
    doc = parse_pdf(raw / pdf)
    out.parent.mkdir(parents=True, exist_ok=True)
    save_parsed(doc, out)
    return True


def _segment(data, key, out, **_):
    doc = _read(path(data, "parsed", key, "parsed.json"), ParsedDoc)
    return bool(doc) and _write(out, segment(doc.blocks))


def _extract(data, key, out, client=None, model="apertus-8b", max_chars=12000, **_):
    doc = _read(path(data, "parsed", key, "parsed.json"), ParsedDoc)
    seg = _read(path(data, "segmented", key, "segments.json"), SegmentResult)
    if not doc or not seg:
        return False
    raw = path(data, "raw", key, "")
    lang = _language(json.loads((raw / "affair.json").read_text(encoding="utf-8")),
                     load_manifest(raw / "manifest.json"), doc, [])
    return _write(out, extract_affair(seg, doc.blocks, client, model=model, max_chars=max_chars, language=lang))


def _verify(data, key, out, threshold=90, **_):
    doc = _read(path(data, "parsed", key, "parsed.json"), ParsedDoc)
    ext = _read(path(data, "extracted", key, "extraction.json"), ExtractionResult)
    return bool(doc and ext) and _write(out, verify(ext, doc.blocks, threshold))


def _merge(data, key, out, **_):
    raw = path(data, "raw", key, "")
    bodies = Path(data) / "raw" / "bodies.json"
    body = next((b for b in json.loads(bodies.read_text(encoding="utf-8")) if b.get("body_key") == key[0]),
                None) if bodies.exists() else None
    # ponytail: --force appends again to disagreements.jsonl; dedupe on (affair_id, field) if that matters
    affair = merge_affair(
        json.loads((raw / "affair.json").read_text(encoding="utf-8")), load_manifest(raw / "manifest.json"),
        _read(path(data, "parsed", key, "parsed.json"), ParsedDoc),
        _read(path(data, "segmented", key, "segments.json"), SegmentResult),
        _read(path(data, "verified", key, "verified.json"), VerifiedParts), body,
        disagreement_log=Path(data) / "output" / "disagreements.jsonl")
    return _write(out, affair)


RUNNERS = {"parse": _parse, "segment": _segment, "extract": _extract, "verify": _verify, "merge": _merge}


def run_stage(data: Path, stage: str, keys: list[Key], force: bool = False, **kw) -> Summary:
    s = Summary(stage, keys=list(keys))
    sub, name = OUT[stage]
    for key in keys:
        out = path(data, sub, key, name)
        if out.exists() and not force:
            s.skipped += 1
            continue
        try:
            wrote = RUNNERS[stage](data, key, out, **kw)
        except Exception as e:
            log_error(data, key, stage, e)
            s.failed += 1
            continue
        s.done += wrote
        s.skipped += not wrote
    return s
