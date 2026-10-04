"""Rule-based segmentation: assign parsed blocks to affair sections by headings (no LLM)."""
import re
import unicodedata

from pydantic import BaseModel

from openparl_extract.parse.blocks import Block
from openparl_extract.segment.patterns import PATTERNS

SECTIONS = ("affair_text", "justification", "questions", "executive_answer", "decision", "annex", "other")
MAX_HEADING_LEN = 120

_NUMBERING = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[a-z]\)|[ivx]+\.)\s+")


class SegmentResult(BaseModel):
    sections: dict[str, list[str]]
    block_section: dict[str, str]
    headings: list[tuple[str, str]] = []
    review_flags: list[str] = []


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("\u2019", "'").replace("\u00b4", "'").replace("\u2018", "'").replace("`", "'")
    t = re.sub(r"\s+", " ", t).strip()
    t = _NUMBERING.sub("", t).rstrip(":").strip()
    return t


def heading_section(b: Block) -> str | None:
    if b.type in ("image", "table", "signature_stamp"):
        return None
    if b.type != "heading" and len(b.text) > MAX_HEADING_LEN:
        return None
    t = normalise(b.text)
    return next((s for s, p in PATTERNS.items() if p.match(t)), None)


def segment(blocks: list[Block]) -> SegmentResult:
    sections: dict[str, list[str]] = {s: [] for s in SECTIONS}
    block_section: dict[str, str] = {}
    headings: list[tuple[str, str]] = []
    current = "affair_text"
    for b in blocks:
        h = heading_section(b)
        if h:
            current = h
            headings.append((b.id, h))
        sections[current].append(b.id)
        block_section[b.id] = current
    flags: list[str] = []
    if blocks and not headings:
        sections = {s: [] for s in SECTIONS}
        sections["other"] = [b.id for b in blocks]
        block_section = {b.id: "other" for b in blocks}
        flags.append("segmentation_failed")
    return SegmentResult(sections=sections, block_section=block_section, headings=headings, review_flags=flags)


def section_blocks(result: SegmentResult, blocks: list[Block], name: str) -> list[Block]:
    ids = set(result.sections.get(name, []))
    return [b for b in blocks if b.id in ids]
