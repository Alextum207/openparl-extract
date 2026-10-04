"""Docling glue: PDF -> ParsedDoc with stable block IDs p{page}_b{index}."""
import ssl
from pathlib import Path

import truststore
from pypdf import PdfReader

from openparl_extract.parse.blocks import Block, ParsedDoc, strip_running_headers_footers

SCANNED_CHARS_PER_PAGE = 50  # avg extractable chars/page below this => treated as scanned
_TYPES = {"section_header": "heading", "title": "heading", "text": "paragraph", "paragraph": "paragraph",
          "list_item": "paragraph", "table": "table", "picture": "image", "handwritten_text": "signature_stamp"}
_HF = {"page_header", "page_footer"}  # Docling-detected running header/footer: always removed


def _is_scanned(path: Path) -> tuple[bool, int]:
    r = PdfReader(str(path))
    n = len(r.pages)
    chars = sum(len((p.extract_text() or "").strip()) for p in r.pages)
    return (n == 0 or chars / n < SCANNED_CHARS_PER_PAGE), n


def _convert(path: Path, ocr: bool):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    truststore.inject_into_ssl()  # HF model download behind Windows cert store
    opts = PdfPipelineOptions(do_ocr=ocr)
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    return conv.convert(str(path)).document


def parse_pdf(path: Path, ocr: bool | None = None) -> ParsedDoc:
    path = Path(path)
    scanned, n_pages = _is_scanned(path)
    base = dict(source_file=path.name, page_count=n_pages, is_scanned=scanned)
    try:
        doc = _convert(path, scanned if ocr is None else ocr)
    except Exception:  # ponytail: swallow only for text-less PDFs; real failures on text PDFs must surface
        if scanned:
            return ParsedDoc(**base, blocks=[])
        raise
    counters: dict[int, int] = {}
    blocks: list[Block] = []
    hf: list[Block] = []
    heights: dict[int, float] = {}
    for item, _ in doc.iterate_items():
        if not item.prov:
            continue
        pv = item.prov[0]
        page = pv.page_no  # 1-based
        h = doc.pages[page].size.height if page in doc.pages else None
        if h:
            heights[page] = h
        bbox = None
        if pv.bbox is not None:
            # Docling bboxes are bottom-left origin in PDF points; convert to top-left origin
            b = pv.bbox.to_top_left_origin(h) if h else pv.bbox
            bbox = (b.l, b.t, b.r, b.b)
        label = item.label.value
        text = getattr(item, "text", "") or ""
        if label == "table" and not text:
            text = item.export_to_markdown(doc) if hasattr(item, "export_to_markdown") else ""
        idx = counters.get(page, 0)  # assigned BEFORE stripping so IDs stay stable
        counters[page] = idx + 1
        blk = Block(id=f"p{page}_b{idx}", page=page, bbox=bbox, text=text, type=_TYPES.get(label, "other"))
        (hf if label in _HF else blocks).append(blk)
    kept, removed = strip_running_headers_footers(blocks, n_pages, heights)
    return ParsedDoc(**base, blocks=kept, removed=hf + removed)
