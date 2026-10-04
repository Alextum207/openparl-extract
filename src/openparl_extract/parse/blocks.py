"""Block models and running header/footer stripping (pure Python, no Docling)."""
import re
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

PAGE_H = 842.0  # A4 height in points, fallback when page height unknown
EDGE = 0.10  # top/bottom fraction of page considered header/footer zone
SHORT = 20  # max chars for the pattern rule when bbox is unknown

_PAGENUM = re.compile(
    r"^[-–—\s]*(?:(?:seite|page|pagina|p\.|s\.)\s*)?\d+\s*(?:(?:/|von|sur|di|of)\s*\d+)?[-–—\s]*$", re.I)


class Block(BaseModel):
    id: str
    page: int
    bbox: tuple[float, float, float, float] | None = None  # (x0, top, x1, bottom), top-left origin, PDF points
    text: str
    type: Literal["heading", "paragraph", "table", "image", "signature_stamp", "other"] = "paragraph"


class ParsedDoc(BaseModel):
    source_file: str
    page_count: int
    is_scanned: bool
    blocks: list[Block]
    removed: list[Block] = []


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", t.lower())).strip()


def strip_running_headers_footers(blocks: list[Block], page_count: int,
                                  page_heights: dict[int, float] | None = None) -> tuple[list[Block], list[Block]]:
    """Return (kept, removed). Page heights default to the max bbox bottom seen on that page (or A4)."""
    heights = dict(page_heights or {})
    for b in blocks:
        if b.bbox and b.page not in heights:
            heights[b.page] = max(PAGE_H, max(x.bbox[3] for x in blocks if x.page == b.page and x.bbox))
    pages_by_norm: dict[str, set[int]] = defaultdict(set)
    for b in blocks:
        if b.text.strip():
            pages_by_norm[_norm(b.text)].add(b.page)

    def in_edge(b: Block) -> bool:
        h = heights.get(b.page, PAGE_H)
        return b.bbox[3] <= h * EDGE or b.bbox[1] >= h * (1 - EDGE)

    kept, removed = [], []
    for b in blocks:
        t = b.text.strip()
        repeated = page_count >= 3 and len(pages_by_norm[_norm(t)]) > page_count / 2 and not _PAGENUM.match(t)
        pagenum = bool(_PAGENUM.match(t)) and (in_edge(b) if b.bbox else len(t) <= SHORT)
        # repetition rule: only blocks in an edge zone (when known), so repeated body phrases survive
        if repeated and b.bbox and not in_edge(b):
            repeated = False
        (removed if repeated or pagenum else kept).append(b)
    return kept, removed


def save_parsed(doc: ParsedDoc, path: Path) -> None:
    Path(path).write_text(doc.model_dump_json(indent=2), encoding="utf-8")


def load_parsed(path: Path) -> ParsedDoc:
    return ParsedDoc.model_validate_json(Path(path).read_text(encoding="utf-8"))
