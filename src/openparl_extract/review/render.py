"""PDF page rendering (pypdfium2 + Pillow) and block lookup for the review UI."""
import io
from functools import lru_cache
from pathlib import Path

import pypdfium2 as pdfium

from openparl_extract.parse.blocks import ParsedDoc


def _open(pdf_path: Path, page: int):
    pdf = pdfium.PdfDocument(str(pdf_path))
    if not 1 <= page <= len(pdf):
        pdf.close()
        raise ValueError(f"page {page} out of range")
    return pdf, pdf[page - 1]


@lru_cache(maxsize=32)
def _render(path: str, mtime: int, page: int, scale: float) -> bytes:
    pdf, p = _open(Path(path), page)
    try:
        buf = io.BytesIO()
        p.render(scale=scale).to_pil().save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()


def render_page(pdf_path: Path, page: int, scale: float = 1.5) -> bytes:
    """PNG bytes of a 1-based page. ValueError when the page does not exist."""
    pdf_path = Path(pdf_path)
    return _render(str(pdf_path), pdf_path.stat().st_mtime_ns, page, float(scale))


def page_size(pdf_path: Path, page: int) -> tuple[float, float]:
    """(width, height) in PDF points."""
    pdf, p = _open(Path(pdf_path), page)
    try:
        return p.get_size()
    finally:
        pdf.close()


def page_blocks(parsed: ParsedDoc, page: int) -> list[dict]:
    return [{"id": b.id, "bbox": b.bbox, "text": b.text, "type": b.type} for b in parsed.blocks if b.page == page]
