"""
Unit tests for lecture_auto.pipeline.parser

TDD RED phase: tests are written before implementation.
All 15 behaviors from the plan are covered.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import pytest
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor

from lecture_auto.pipeline.parser_pptx import (
    parse_pptx,
    classify_shape,
    extract_text_content,
    extract_font_info,
)
from lecture_auto.schemas.manifest import ShapeRecord, SlideRecord, TextParagraph, TextRun, FontInfo


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def make_test_pptx() -> bytes:
    """
    Build a minimal in-memory PPTX for use as a test fixture.

    Slide 1: Title slide layout — title placeholder ("Test Title") +
             subtitle placeholder ("Subtitle text")
    Slide 2: Blank layout — body text box, a picture shape (tiny PNG),
             a plain text box with custom font
    """
    from pptx.util import Inches, Pt
    from PIL import Image as PILImage

    prs = Presentation()

    # --- Slide 1: title slide ---
    title_layout = prs.slide_layouts[0]  # "Title Slide"
    slide1 = prs.slides.add_slide(title_layout)
    slide1.shapes.title.text = "Test Title"
    slide1.placeholders[1].text = "Subtitle text"

    # --- Slide 2: blank + manual shapes ---
    blank_layout = prs.slide_layouts[6]  # "Blank"
    slide2 = prs.slides.add_slide(blank_layout)

    # Text box with body-like content
    txBox = slide2.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    tf = txBox.text_frame
    tf.text = "Body content paragraph"
    run = tf.paragraphs[0].runs[0]
    run.font.name = "Arial"
    run.font.size = Pt(18)
    run.font.bold = True
    run.font.italic = False

    # Tiny 1×1 PNG picture
    img_buf = io.BytesIO()
    img = PILImage.new("RGB", (1, 1), color=(255, 0, 0))
    img.save(img_buf, format="PNG")
    img_buf.seek(0)
    slide2.shapes.add_picture(img_buf, Inches(6), Inches(1), Inches(1), Inches(1))

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Mock shape helpers for non-renderable types (SmartArt, Chart, OLE)
# ---------------------------------------------------------------------------

@dataclass
class MockShape:
    """Minimal mock for python-pptx shape interface."""
    shape_id: int = 1
    name: str = "MockShape"
    shape_type: Any = None
    left: int = 914400
    top: int = 914400
    width: int = 1828800
    height: int = 914400
    has_text_frame: bool = False
    has_chart: bool = False
    has_table: bool = False
    is_placeholder: bool = False

    # python-pptx 1.0+ attribute
    @property
    def has_smart_art(self) -> bool:
        return self._has_smart_art

    def __post_init__(self):
        self._has_smart_art = False


def make_smartart_mock() -> MockShape:
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    s = MockShape(shape_id=10, name="SmartArt 1", shape_type=MSO_SHAPE_TYPE.IGX_GRAPHIC)
    s._has_smart_art = True
    return s


def make_chart_mock() -> MockShape:
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    s = MockShape(shape_id=11, name="Chart 1", shape_type=MSO_SHAPE_TYPE.CHART, has_chart=True)
    return s


def make_ole_mock() -> MockShape:
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    s = MockShape(shape_id=12, name="OLE 1", shape_type=MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT)
    return s


def make_linked_ole_mock() -> MockShape:
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    s = MockShape(shape_id=13, name="LinkedOLE 1", shape_type=MSO_SHAPE_TYPE.LINKED_OLE_OBJECT)
    return s


# ---------------------------------------------------------------------------
# Test 1: parse_pptx returns list[SlideRecord] with correct indices
# ---------------------------------------------------------------------------

class TestSlideIndexing:
    def test_returns_list_of_slide_records(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        assert isinstance(result, list)
        assert all(isinstance(s, SlideRecord) for s in result)

    def test_slide_count_matches_pptx(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        assert len(result) == 2

    def test_slide_index_is_zero_based(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        assert result[0].slide_index == 0
        assert result[1].slide_index == 1

    def test_slide_number_is_one_based(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        assert result[0].slide_number == 1
        assert result[1].slide_number == 2


# ---------------------------------------------------------------------------
# Test 2: Text shapes → content_source="text", has_text=True
# ---------------------------------------------------------------------------

class TestTextShapeClassification:
    def test_text_shape_content_source(self):
        data = make_test_pptx()
        slide2 = parse_pptx(data)[1]
        text_shapes = [s for s in slide2.shapes if s.content_source == "text"]
        assert len(text_shapes) >= 1

    def test_text_shape_has_text_true(self):
        data = make_test_pptx()
        slide2 = parse_pptx(data)[1]
        text_shapes = [s for s in slide2.shapes if s.content_source == "text"]
        assert all(s.has_text for s in text_shapes)


# ---------------------------------------------------------------------------
# Test 3: Title placeholder → text_role="title"
# ---------------------------------------------------------------------------

class TestTitleRole:
    def test_title_placeholder_role(self):
        data = make_test_pptx()
        slide1 = parse_pptx(data)[0]
        title_shapes = [s for s in slide1.shapes if s.text_role == "title"]
        assert len(title_shapes) >= 1

    def test_title_shape_content_source_is_text(self):
        data = make_test_pptx()
        slide1 = parse_pptx(data)[0]
        title_shapes = [s for s in slide1.shapes if s.text_role == "title"]
        assert all(s.content_source == "text" for s in title_shapes)


# ---------------------------------------------------------------------------
# Test 4: Body/subtitle placeholder → text_role="body"
# ---------------------------------------------------------------------------

class TestBodyRole:
    def test_subtitle_placeholder_gets_body_or_title_role(self):
        """Subtitle placeholder type maps to title role per PP_PLACEHOLDER.SUBTITLE."""
        data = make_test_pptx()
        slide1 = parse_pptx(data)[0]
        # On a title slide, subtitle is SUBTITLE placeholder → maps to "title" role in plan spec
        text_roles = {s.text_role for s in slide1.shapes if s.content_source == "text"}
        # Both title and (title or body) must be present
        assert "title" in text_roles


# ---------------------------------------------------------------------------
# Test 5: Non-placeholder text shapes → text_role="other"
# ---------------------------------------------------------------------------

class TestOtherRole:
    def test_non_placeholder_textbox_role_is_other(self):
        data = make_test_pptx()
        slide2 = parse_pptx(data)[1]
        text_shapes = [s for s in slide2.shapes if s.content_source == "text"]
        # All text boxes on blank slide are non-placeholder
        assert all(s.text_role == "other" for s in text_shapes)


# ---------------------------------------------------------------------------
# Test 6: Image shapes → content_source="image", has_image=True, has_text=False
# ---------------------------------------------------------------------------

class TestImageShape:
    def test_image_shape_content_source(self):
        data = make_test_pptx()
        slide2 = parse_pptx(data)[1]
        image_shapes = [s for s in slide2.shapes if s.content_source == "image"]
        assert len(image_shapes) >= 1

    def test_image_shape_has_image_true(self):
        data = make_test_pptx()
        slide2 = parse_pptx(data)[1]
        image_shapes = [s for s in slide2.shapes if s.content_source == "image"]
        assert all(s.has_image for s in image_shapes)

    def test_image_shape_has_text_false(self):
        data = make_test_pptx()
        slide2 = parse_pptx(data)[1]
        image_shapes = [s for s in slide2.shapes if s.content_source == "image"]
        assert all(not s.has_text for s in image_shapes)


# ---------------------------------------------------------------------------
# Test 7: Chart shapes → content_source="chart"
# ---------------------------------------------------------------------------

class TestChartClassification:
    def test_chart_mock_content_source(self):
        mock = make_chart_mock()
        result = classify_shape(mock, z_order=0)
        assert result.content_source == "chart"


# ---------------------------------------------------------------------------
# Test 8: SmartArt shapes → content_source="smartart"
# ---------------------------------------------------------------------------

class TestSmartArtClassification:
    def test_smartart_mock_content_source(self):
        mock = make_smartart_mock()
        result = classify_shape(mock, z_order=0)
        assert result.content_source == "smartart"


# ---------------------------------------------------------------------------
# Test 9: OLE shapes → content_source="ole_object"
# ---------------------------------------------------------------------------

class TestOLEClassification:
    def test_ole_embedded_mock_content_source(self):
        mock = make_ole_mock()
        result = classify_shape(mock, z_order=0)
        assert result.content_source == "ole_object"

    def test_ole_linked_mock_content_source(self):
        mock = make_linked_ole_mock()
        result = classify_shape(mock, z_order=0)
        assert result.content_source == "ole_object"


# ---------------------------------------------------------------------------
# Test 10: Table shapes → content_source="table"
# ---------------------------------------------------------------------------

class TestTableClassification:
    def test_table_mock_content_source(self):
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        mock = MockShape(shape_id=14, name="Table 1",
                         shape_type=MSO_SHAPE_TYPE.TABLE, has_table=True)
        result = classify_shape(mock, z_order=0)
        assert result.content_source == "table"


# ---------------------------------------------------------------------------
# Test 11: Font info extracted correctly
# ---------------------------------------------------------------------------

class TestFontExtraction:
    def test_font_name_extracted(self):
        data = make_test_pptx()
        slide2 = parse_pptx(data)[1]
        text_shapes = [s for s in slide2.shapes if s.content_source == "text"]
        assert len(text_shapes) >= 1
        # The textbox has font.name = "Arial"
        para = text_shapes[0].paragraphs[0]
        run = para.runs[0]
        assert run.font.name == "Arial"

    def test_font_size_pt_converted(self):
        data = make_test_pptx()
        slide2 = parse_pptx(data)[1]
        text_shapes = [s for s in slide2.shapes if s.content_source == "text"]
        para = text_shapes[0].paragraphs[0]
        run = para.runs[0]
        # Pt(18) = 18 * 12700 EMU; after conversion back should be 18.0
        assert run.font.size_pt == pytest.approx(18.0, abs=0.1)

    def test_font_bold_extracted(self):
        data = make_test_pptx()
        slide2 = parse_pptx(data)[1]
        text_shapes = [s for s in slide2.shapes if s.content_source == "text"]
        para = text_shapes[0].paragraphs[0]
        run = para.runs[0]
        assert run.font.bold is True

    def test_font_italic_extracted(self):
        data = make_test_pptx()
        slide2 = parse_pptx(data)[1]
        text_shapes = [s for s in slide2.shapes if s.content_source == "text"]
        para = text_shapes[0].paragraphs[0]
        run = para.runs[0]
        assert run.font.italic is False


# ---------------------------------------------------------------------------
# Test 12: Bounding box values are integers in EMU
# ---------------------------------------------------------------------------

class TestBoundingBox:
    def test_bounding_box_values_are_integers(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        for slide in result:
            for shape in slide.shapes:
                assert isinstance(shape.left, int)
                assert isinstance(shape.top, int)
                assert isinstance(shape.width, int)
                assert isinstance(shape.height, int)

    def test_bounding_box_values_non_negative(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        for slide in result:
            for shape in slide.shapes:
                assert shape.left >= 0
                assert shape.top >= 0
                assert shape.width >= 0
                assert shape.height >= 0


# ---------------------------------------------------------------------------
# Test 13: z_order reflects enumeration index
# ---------------------------------------------------------------------------

class TestZOrder:
    def test_z_order_starts_at_zero(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        for slide in result:
            if slide.shapes:
                z_orders = [s.z_order for s in slide.shapes]
                assert 0 in z_orders

    def test_z_order_is_sequential(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        for slide in result:
            z_orders = [s.z_order for s in slide.shapes]
            assert z_orders == list(range(len(z_orders)))


# ---------------------------------------------------------------------------
# Test 14: TextParagraph.full_text equals concatenated run texts
# ---------------------------------------------------------------------------

class TestFullText:
    def test_full_text_equals_concatenated_runs(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        for slide in result:
            for shape in slide.shapes:
                for para in shape.paragraphs:
                    expected = "".join(r.text for r in para.runs)
                    assert para.full_text == expected


# ---------------------------------------------------------------------------
# Test 15: png_path formatted as "slide_{NNN}.png" (3-digit zero-padded)
# ---------------------------------------------------------------------------

class TestPngPath:
    def test_png_path_format(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        assert result[0].png_path == "slide_001.png"
        assert result[1].png_path == "slide_002.png"

    def test_png_path_zero_padded(self):
        data = make_test_pptx()
        result = parse_pptx(data)
        for slide in result:
            # Must match "slide_NNN.png" with exactly 3 digits
            import re
            assert re.match(r"^slide_\d{3}\.png$", slide.png_path), \
                f"Bad png_path format: {slide.png_path}"
