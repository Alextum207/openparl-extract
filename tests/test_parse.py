import re
from pathlib import Path

import pytest

from openparl_extract.parse.blocks import Block, ParsedDoc, load_parsed, save_parsed, strip_running_headers_footers

H = 842.0  # page height; bbox = (x0, top, x1, bottom), top-left origin


def B(page, idx, text, top=400.0, type="paragraph", bbox=True):
    return Block(id=f"p{page}_b{idx}", page=page, text=text, type=type,
                 bbox=(50.0, top, 500.0, top + 12) if bbox else None)


def test_repeating_header_removed_content_kept():
    blocks = []
    for p in (1, 2, 3):
        blocks += [B(p, 0, "Kanton Zürich Regierungsrat", top=20), B(p, 1, f"Unique body text {'abc'[p-1]}")]
    kept, removed = strip_running_headers_footers(blocks, 3)
    assert {b.text for b in removed} == {"Kanton Zürich Regierungsrat"} and len(removed) == 3
    assert [b.id for b in kept] == ["p1_b1", "p2_b1", "p3_b1"]


@pytest.mark.parametrize("t", ["3", "Seite 3", "Seite 2 von 5", "Page 3/6", "Pagina 3 di 6", "- 3 -", "Page 3 sur 6"])
def test_page_number_patterns_removed_at_bottom(t):
    kept, removed = strip_running_headers_footers([B(1, 0, "Body"), B(1, 1, t, top=810)], 1)
    assert [b.text for b in removed] == [t] and [b.text for b in kept] == ["Body"]


def test_number_in_body_kept():
    kept, removed = strip_running_headers_footers([B(1, 0, "3", top=400), B(1, 1, "x", top=500)], 1)
    assert not removed and len(kept) == 2


def test_content_once_kept_and_few_pages_no_repetition_rule():
    blocks = [B(1, 0, "Same header", top=20), B(2, 0, "Same header", top=20), B(1, 1, "Only once")]
    kept, removed = strip_running_headers_footers(blocks, 2)
    assert not removed and len(kept) == 3


def test_no_bbox_pattern_only_short():
    kept, removed = strip_running_headers_footers(
        [B(1, 0, "Seite 3", bbox=False), B(1, 1, "Seite 3 der Vorlage ist wichtig und lang genug", bbox=False)], 1)
    assert [b.text for b in removed] == ["Seite 3"] and len(kept) == 1


def test_save_load_roundtrip(tmp_path):
    d = ParsedDoc(source_file="a.pdf", page_count=1, is_scanned=False, blocks=[B(1, 0, "x")])
    save_parsed(d, tmp_path / "d.json")
    assert load_parsed(tmp_path / "d.json") == d


# ---- Docling integration ----
def _pdf(path: Path, pages=3):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    for p in range(1, pages + 1):
        c.setFont("Helvetica", 9)
        c.drawString(50, 810, "Kanton Beispiel - Grosser Rat")
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, 740, f"Interpellation Nummer {p}")
        c.setFont("Helvetica", 11)
        for i in range(4):
            c.drawString(50, 700 - 16 * i, f"Dies ist Absatz {i} auf Seite {p} mit eigenem Inhalt {p * 7 + i}.")
        c.setFont("Helvetica", 9)
        c.drawString(280, 30, f"Seite {p}")
        c.showPage()
    c.save()


def test_parse_pdf_born_digital(tmp_path):
    from openparl_extract.parse.docling_parse import parse_pdf
    pdf = tmp_path / "t.pdf"
    _pdf(pdf)
    d1, d2 = parse_pdf(pdf), parse_pdf(pdf)
    assert d1.is_scanned is False and d1.page_count == 3 and d1.blocks
    assert all(re.match(r"^p\d+_b\d+$", b.id) for b in d1.blocks)
    texts = " ".join(b.text for b in d1.blocks)
    assert "Grosser Rat" not in texts and not re.search(r"Seite \d\b(?! mit)", texts.replace("auf Seite", ""))
    assert any(b.type == "heading" and "Interpellation" in b.text for b in d1.blocks)
    assert [b.id for b in d1.blocks] == [b.id for b in d2.blocks]


def test_parse_pdf_no_text_layer(tmp_path):
    from reportlab.pdfgen import canvas
    from openparl_extract.parse.docling_parse import parse_pdf
    pdf = tmp_path / "s.pdf"
    c = canvas.Canvas(str(pdf))
    c.rect(100, 100, 200, 200, fill=1)
    c.save()
    d = parse_pdf(pdf)
    assert d.is_scanned is True and isinstance(d.blocks, list)
