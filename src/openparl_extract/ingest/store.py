"""Local store: root/{body_key}/{affair_id}/{affair.json, doc_<id>.pdf, manifest.json}."""
import hashlib
import json
from pathlib import Path

from openparl_extract.ingest.api import OpenParlDataClient


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _docs(affair: dict) -> list[dict]:
    return (affair.get("docs") or {}).get("data") or []


def _is_pdf(doc: dict) -> bool:
    return doc.get("format") == "application/pdf"


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def save_affair(affair: dict, pdfs: dict[int, bytes], root: Path, primary_doc_id: int | None = None) -> Path:
    d = Path(root) / str(affair["body_key"]) / str(affair["id"])
    d.mkdir(parents=True, exist_ok=True)
    _write_json(d / "affair.json", affair)
    docs, entries = _docs(affair), []
    for doc in docs:
        pdf = pdfs.get(doc["id"])
        if pdf is not None:
            (d / f"doc_{doc['id']}.pdf").write_bytes(pdf)
        entries.append({
            "doc_id": doc["id"], "name": doc.get("name"), "url_oparl": doc.get("url_oparl"),
            "format": doc.get("format"), "language": doc.get("language"), "date": doc.get("date"),
            "pdf_file": f"doc_{doc['id']}.pdf" if pdf is not None else None,
            "pdf_sha256": sha256_bytes(pdf) if pdf is not None else None,
            "has_plain_text": bool(doc.get("text")),
        })
    primary = primary_doc_id or next((x["id"] for x in docs if _is_pdf(x)), None)
    flags = ["no_document"] if not docs else ["no_pdf"] if primary is None else []
    _write_json(d / "manifest.json", {
        "affair_id": affair["id"], "body_key": affair["body_key"], "number": affair.get("number"),
        "docs": entries, "primary_doc_id": primary, "flags": flags})
    return d


def load_manifest(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ingest_affair(client: OpenParlDataClient, affair_id: int | str, root: Path,
                  primary_doc_id: int | None = None) -> Path:
    """primary_doc_id: use this PDF as the one the pipeline processes (must be one of the affair's pdf docs).
    Only that PDF is downloaded unless it is already the first pdf (then all are, as without the argument)."""
    affair = client.get_affair(affair_id)
    docs = [d for d in _docs(affair) if _is_pdf(d) and d.get("url_oparl")]
    if primary_doc_id is not None:
        if primary_doc_id not in {d["id"] for d in docs}:
            raise ValueError(f"doc {primary_doc_id} is not a pdf document of affair {affair_id}")
        if primary_doc_id != docs[0]["id"]:
            docs = [d for d in docs if d["id"] == primary_doc_id]
    pdfs = {d["id"]: client.download_pdf(d["url_oparl"]) for d in docs}
    return save_affair(affair, pdfs, root, primary_doc_id)
