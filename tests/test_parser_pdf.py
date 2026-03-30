"""Tests for PDF parser with title detection and table fallback."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pymupdf
import pytest

from lecture_auto.schemas.manifest import SlideRecord, ShapeRecord


# ---------------------------------------------------------------------------
# Helpers: create synthetic PDFs in memory
# ---------------------------------------------------------------------------

def _create_simple_pdf(tmp_path: Path, *, title_text: str = "Lecture Title",
                       body_text: str = "Body content here") -> Path:
    """Create a single-page PDF with title (top, large, bold) and body text."""
    doc = pymupdf.open()
    page = doc.new_page(width=720, height=540)  # 10x7.5 inches in points

    # Title: top area, large font, bold
    page.insert_text(
        (50, 60),  # y=60, well within top 25% of 540 = 135
        title_text,
        fontname="helv",
        fontsize=24,
    )
    # Body: lower area, normal font
    page.insert_text(
        (50, 300),  # y=300, in bottom 75%
        body_text,
        fontname="helv",
        fontsize=12,
    )

    pdf_path = tmp_path / "test_simple.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _create_multi_page_pdf(tmp_path: Path, page_count: int = 3) -> Path:
    """Create a multi-page PDF with numbered titles and bodies."""
    doc = pymupdf.open()
    for i in range(page_count):
        page = doc.new_page(width=720, height=540)
        page.insert_text((50, 60), f"Slide {i + 1} Title", fontname="helv", fontsize=22)
        page.insert_text((50, 300), f"Content for slide {i + 1}", fontname="helv", fontsize=12)

    pdf_path = tmp_path / "test_multi.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _create_image_pdf(tmp_path: Path) -> Path:
    """Create a PDF with an embedded image block."""
    doc = pymupdf.open()
    page = doc.new_page(width=720, height=540)
    # Insert text
    page.insert_text((50, 60), "Title with image", fontname="helv", fontsize=20)
    # Insert a small colored rectangle as a pixmap/image
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 80), 1)
    pix.set_rect(pix.irect, (255, 0, 0, 255))  # red rectangle (RGBA for alpha pixmap)
    page.insert_image(pymupdf.Rect(200, 200, 400, 400), pixmap=pix)

    pdf_path = tmp_path / "test_image.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _create_table_pdf(tmp_path: Path) -> Path:
    """Create a PDF with tabular data that pdfplumber can detect."""
    doc = pymupdf.open()
    page = doc.new_page(width=720, height=540)

    # Draw a simple table with borders (lines) so pdfplumber can detect it
    # 3 rows x 2 cols
    x0, y0 = 50, 100
    col_w, row_h = 150, 30
    cols, rows = 2, 3

    for r in range(rows + 1):
        y = y0 + r * row_h
        page.draw_line((x0, y), (x0 + cols * col_w, y))
    for c in range(cols + 1):
        x = x0 + c * col_w
        page.draw_line((x, y0), (x, y0 + rows * row_h))

    # Fill cells with text
    cell_data = [["Header A", "Header B"], ["Row1 A", "Row1 B"], ["Row2 A", "Row2 B"]]
    for r, row_data in enumerate(cell_data):
        for c, text in enumerate(row_data):
            page.insert_text(
                (x0 + c * col_w + 10, y0 + r * row_h + 20),
                text,
                fontname="helv",
                fontsize=10,
            )

    pdf_path = tmp_path / "test_table.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


# ---------------------------------------------------------------------------
# Tests: parse_pdf returns list[SlideRecord]
# ---------------------------------------------------------------------------

class TestParsePdf:
    """Tests for parse_pdf producing SlideRecord list."""

    def test_parse_pdf_returns_slide_records(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import parse_pdf
        pdf_path = _create_simple_pdf(tmp_path)
        result = parse_pdf(pdf_path)

        assert isinstance(result, list)
        assert len(result) == 1
        slide = result[0]
        assert isinstance(slide, SlideRecord)
        assert slide.slide_index == 0
        assert slide.slide_number == 1
        assert slide.png_path == "slide_001.png"

    def test_parse_pdf_multi_page(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import parse_pdf
        pdf_path = _create_multi_page_pdf(tmp_path, page_count=3)
        result = parse_pdf(pdf_path)

        assert len(result) == 3
        for i, slide in enumerate(result):
            assert slide.slide_index == i
            assert slide.slide_number == i + 1
            assert slide.png_path == f"slide_{i + 1:03d}.png"


# ---------------------------------------------------------------------------
# Tests: title detection heuristic
# ---------------------------------------------------------------------------

class TestTitleDetection:
    """Title detection: y < page_height*0.25 AND (font_size >= 18.0 OR bold)."""

    def test_title_detected_for_top_large_text(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import parse_pdf
        pdf_path = _create_simple_pdf(tmp_path, title_text="Big Title")
        result = parse_pdf(pdf_path)

        slide = result[0]
        title_shapes = [s for s in slide.shapes if s.text_role == "title"]
        assert len(title_shapes) >= 1, "Expected at least one title shape"

        # Verify the title shape has font info
        title_shape = title_shapes[0]
        assert title_shape.has_text is True
        assert title_shape.content_source == "text"

    def test_body_detected_for_lower_normal_text(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import parse_pdf
        pdf_path = _create_simple_pdf(tmp_path, body_text="Normal body text")
        result = parse_pdf(pdf_path)

        slide = result[0]
        body_shapes = [s for s in slide.shapes if s.text_role == "body"]
        assert len(body_shapes) >= 1, "Expected at least one body shape"

    def test_is_title_span_with_y_position_and_large_font(self):
        from lecture_auto.pipeline.parser_pdf import is_title_span
        # y=50 < 540*0.25=135 AND size=24 >= 18 => title
        span = {"bbox": (50, 50, 200, 74), "size": 24.0, "flags": 0, "font": "Helvetica"}
        assert is_title_span(span, page_height=540) is True

    def test_is_title_span_with_y_position_and_bold(self):
        from lecture_auto.pipeline.parser_pdf import is_title_span
        # y=50 < 135 AND flags&16 (bold) => title even with small font
        span = {"bbox": (50, 50, 200, 62), "size": 12.0, "flags": 16, "font": "Helvetica-Bold"}
        assert is_title_span(span, page_height=540) is True

    def test_is_title_span_false_for_bottom_text(self):
        from lecture_auto.pipeline.parser_pdf import is_title_span
        # y=400 > 135 => not title regardless of font size
        span = {"bbox": (50, 400, 200, 424), "size": 24.0, "flags": 0, "font": "Helvetica"}
        assert is_title_span(span, page_height=540) is False

    def test_is_title_span_false_for_small_non_bold_top(self):
        from lecture_auto.pipeline.parser_pdf import is_title_span
        # y=50 < 135 BUT size < 18 AND not bold => not title
        span = {"bbox": (50, 50, 200, 62), "size": 10.0, "flags": 0, "font": "Helvetica"}
        assert is_title_span(span, page_height=540) is False

    def test_is_title_span_bold_font_name(self):
        from lecture_auto.pipeline.parser_pdf import is_title_span
        # y=50 < 135 AND font name contains "Bold" => title
        span = {"bbox": (50, 50, 200, 62), "size": 14.0, "flags": 0, "font": "Arial-Bold"}
        assert is_title_span(span, page_height=540) is True


# ---------------------------------------------------------------------------
# Tests: EMU conversion
# ---------------------------------------------------------------------------

class TestEmuConversion:
    """Bbox coordinates converted from PDF points to EMU (multiply by 12700)."""

    def test_bbox_in_emu(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import parse_pdf
        pdf_path = _create_simple_pdf(tmp_path)
        result = parse_pdf(pdf_path)

        slide = result[0]
        # All shapes must have EMU values (points * 12700)
        for shape in slide.shapes:
            # EMU values should be large integers (points are typically < 1000)
            # A shape at x=50 points => 50*12700 = 635000 EMU
            assert shape.left >= 0
            assert shape.top >= 0
            # Verify they're in EMU range (not raw points)
            # Raw points for a 720x540 page would be < 1000
            # EMU for same would be > 100000
            if shape.left > 0:
                assert shape.left > 10000, f"left={shape.left} looks like points, not EMU"


# ---------------------------------------------------------------------------
# Tests: image block detection
# ---------------------------------------------------------------------------

class TestImageBlock:
    """Image blocks get content_source='image', has_image=True."""

    def test_image_block_detected(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import parse_pdf
        pdf_path = _create_image_pdf(tmp_path)
        result = parse_pdf(pdf_path)

        slide = result[0]
        image_shapes = [s for s in slide.shapes if s.content_source == "image"]
        assert len(image_shapes) >= 1, "Expected at least one image shape"
        for img_shape in image_shapes:
            assert img_shape.has_image is True


# ---------------------------------------------------------------------------
# Tests: pdfplumber table fallback
# ---------------------------------------------------------------------------

class TestTableFallback:
    """extract_tables_fallback returns list of tables from a page."""

    def test_extract_tables_from_table_page(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import extract_tables_fallback
        pdf_path = _create_table_pdf(tmp_path)
        tables = extract_tables_fallback(pdf_path, page_num=0)

        assert isinstance(tables, list)
        # pdfplumber should detect at least one table
        assert len(tables) >= 1, "Expected at least one table detected"
        # Each table is a list of rows, each row a list of cell strings
        table = tables[0]
        assert isinstance(table, list)
        assert len(table) >= 2  # at least header + 1 data row

    def test_extract_tables_no_table_page(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import extract_tables_fallback
        pdf_path = _create_simple_pdf(tmp_path)
        tables = extract_tables_fallback(pdf_path, page_num=0)

        assert isinstance(tables, list)
        assert len(tables) == 0


# ---------------------------------------------------------------------------
# Tests: parse_input dispatch
# ---------------------------------------------------------------------------

class TestParseInput:
    """parse_input dispatches PPTX to LibreOffice conversion, PDF directly."""

    def test_parse_input_pdf_direct(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import parse_input
        pdf_path = _create_simple_pdf(tmp_path)
        result = parse_input(pdf_path)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], SlideRecord)

    def test_parse_input_unsupported_extension(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import parse_input
        bad_path = tmp_path / "test.docx"
        bad_path.write_text("not a pdf")

        with pytest.raises(ValueError, match="Unsupported"):
            parse_input(bad_path)

    def test_parse_input_accepts_path_object(self, tmp_path: Path):
        from lecture_auto.pipeline.parser_pdf import parse_input
        pdf_path = _create_simple_pdf(tmp_path)
        result = parse_input(Path(pdf_path))
        assert len(result) == 1
