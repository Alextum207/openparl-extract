"""Tiny self-contained demo dataset for the review app (no network, no Docling): two affairs with real PDFs.

The pipeline output is deliberately imperfect so a first-time reviewer meets every question kind:
a correct value, a wrong value (decision outcome), and values that are missing (answer to question 2, decision date)."""
import json
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from openparl_extract.evaluate.gold import prefill_gold
from openparl_extract.models import (
    Affair,
    Answer,
    Decision,
    Provenance,
    Question,
    Source,
    Value,
)
from openparl_extract.parse.blocks import Block, ParsedDoc, save_parsed

PAGE_H, PAGE_W = 841.89, 595.28  # A4 in points (reportlab default)
FONT, SIZE = "Helvetica", 11

# (block id, page, top y in points, type, text)
DE_BLOCKS = [
    ("p1_b0", 1, 90, "heading", "Interpellation betreffend Velowege"),
    ("p1_b1", 1, 130, "paragraph", "Der Regierungsrat wird gebeten, folgende Fragen zu beantworten:"),
    ("p1_b2", 1, 170, "paragraph", "1. Wie viele Kilometer Velowege wurden 2023 gebaut?"),
    ("p1_b3", 1, 210, "paragraph", "2. Wie hoch waren die Kosten pro Kilometer?"),
    ("p2_b0", 2, 90, "heading", "Antwort des Regierungsrates"),
    ("p2_b1", 2, 130, "paragraph", "Im Jahr 2023 wurden 12 Kilometer Velowege gebaut."),
    ("p2_b2", 2, 170, "paragraph", "Die Kosten betrugen im Schnitt 1,2 Millionen Franken pro Kilometer."),
    ("p2_b3", 2, 230, "paragraph", "Der Rat hat die Interpellation am 21. März 2024 abgeschrieben."),
]
IT_BLOCKS = [
    ("p1_b0", 1, 90, "heading", "Mozione: Più alberi nelle scuole"),
    ("p1_b1", 1, 130, "paragraph", "Il Consiglio di Stato è invitato a piantare alberi in tutti i cortili scolastici."),
    ("p1_b2", 1, 170, "paragraph", "Motivazione: gli alberi migliorano il clima e la salute dei bambini."),
    ("p1_b3", 1, 230, "paragraph", "Il Gran Consiglio ha accolto la mozione il 12 giugno 2024."),
]


def _write_pdf(path: Path, blocks: list, pages: int) -> ParsedDoc:
    c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
    c.setFont(FONT, SIZE)
    out = []
    for p in range(1, pages + 1):
        for bid, page, top, typ, text in blocks:
            if page == p:
                c.drawString(72, PAGE_H - top - SIZE, text)
                out.append(Block(id=bid, page=page, type=typ, text=text,
                                 bbox=(72, top, 72 + stringWidth(text, FONT, SIZE), top + SIZE + 3)))
        c.showPage()
    c.save()
    return ParsedDoc(source_file=path.name, page_count=pages, is_scanned=False, blocks=out)


def _ext(parsed: ParsedDoc, block_id: str, quote: str, value=None) -> Value:
    """Extracted Value whose provenance (page, block, offsets) is consistent with the parsed block."""
    b = next(b for b in parsed.blocks if b.id == block_id)
    i = b.text.index(quote)
    return Value(value=quote if value is None else value, status="extracted",
                 provenance=[Provenance(page=b.page, block_id=b.id, char_start=i, char_end=i + len(quote), quote=quote)])


def _text(parsed: ParsedDoc, block_id: str) -> Value[str]:
    return _ext(parsed, block_id, next(b.text for b in parsed.blocks if b.id == block_id))


NF = Value(status="not_found")


def _affair_de(p: ParsedDoc) -> Affair:
    return Affair(
        source=Source(openparldata_id="9001", parliament="Kantonsrat Zürich (Demo)", body_key="ZH", level="cantonal",
                      language="de", is_scanned=False),
        affair_type=Value(value="interpellation", status="from_metadata"),
        original_type_label=Value(value="Interpellation", status="from_metadata"),
        affair_text=_text(p, "p1_b1"), justification=NF,
        addressed_body=_ext(p, "p1_b1", "Regierungsrat"),
        questions=[Question(id="q1", text=_text(p, "p1_b2")), Question(id="q2", text=_text(p, "p1_b3"))],
        answers=[Answer(question_id="q1", text=_text(p, "p2_b1")),
                 Answer(question_id="q2", text=NF)],  # missed: the answer to question 2 IS on page 2
        executive_reasoning=NF,
        decision=Decision(
            # deliberately WRONG: the text says "abgeschrieben" (written off), not adopted
            outcome=_ext(p, "p2_b3", "abgeschrieben", value="adopted"),
            date=NF,  # missed: 21. März 2024
            body=_ext(p, "p2_b3", "Rat")))


def _affair_it(p: ParsedDoc) -> Affair:
    return Affair(
        source=Source(openparldata_id="9002", parliament="Gran Consiglio Ticino (demo)", body_key="TI",
                      level="cantonal", language="it", is_scanned=False),
        affair_type=Value(value="motion", status="from_metadata"),
        original_type_label=Value(value="Mozione", status="from_metadata"),
        affair_text=_text(p, "p1_b1"), justification=_text(p, "p1_b2"),
        addressed_body=_ext(p, "p1_b1", "Consiglio di Stato"), executive_reasoning=NF,
        decision=Decision(outcome=_ext(p, "p1_b3", "accolto", value="adopted"),
                          date=_ext(p, "p1_b3", "12 giugno 2024", value="2024-06-12"),
                          body=_ext(p, "p1_b3", "Gran Consiglio")))


def build_demo(data_dir: Path) -> Path:
    """Write the demo under `data_dir` (raw/, parsed/, output/, gold/); returns the gold directory."""
    data_dir = Path(data_dir)
    for bk, aid, doc_id, blocks, pages, make in (("ZH", "9001", 501, DE_BLOCKS, 2, _affair_de),
                                                 ("TI", "9002", 502, IT_BLOCKS, 1, _affair_it)):
        dirs = {s: data_dir / s / bk / aid for s in ("raw", "parsed", "output")}
        for d in dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        parsed = _write_pdf(dirs["raw"] / f"doc_{doc_id}.pdf", blocks, pages)
        (dirs["raw"] / "manifest.json").write_text(json.dumps({"primary_doc_id": doc_id, "docs": []}), encoding="utf-8")
        save_parsed(parsed, dirs["parsed"] / "parsed.json")
        affair = make(parsed)
        (dirs["output"] / "affair.json").write_text(affair.model_dump_json(indent=2), encoding="utf-8")
        prefill_gold(affair, data_dir / "gold")
    return data_dir / "gold"
