"""
PPTX parsing module — first stage of the lecture automation pipeline.

Converts raw PPTX bytes (or a file path) into a validated list of
SlideRecord objects that feed both the rendering step and the VLM pipeline.

Exports
-------
parse_pptx           -- main entry point
classify_shape       -- per-shape classification
extract_text_content -- text + text_role extraction from a shape
extract_font_info    -- font metadata from a python-pptx Run object
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

from lecture_auto.schemas.manifest import (
    FontInfo,
    ShapeRecord,
    SlideRecord,
    TextParagraph,
    TextRun,
)


# ---------------------------------------------------------------------------
# Font extraction
# ---------------------------------------------------------------------------

def extract_font_info(run) -> FontInfo:
    """Extract font metadata from a python-pptx Run object.

    python-pptx stores font.size in EMU (English Metric Units).
    1 pt = 12700 EMU.  We convert with `font.size / 12700`.
    """
    font = run.font
    size_pt: float | None = None
    if font.size is not None:
        size_pt = round(font.size / 12700, 1)

    return FontInfo(
        name=font.name,
        size_pt=size_pt,
        bold=font.bold,
        italic=font.italic,
    )


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text_content(shape) -> dict:
    """Extract structured text from a shape that has a text_frame.

    Returns a dict suitable for unpacking into ShapeRecord kwargs:
        has_text, text_role, paragraphs
    """
    paragraphs: list[TextParagraph] = []
    for para in shape.text_frame.paragraphs:
        runs: list[TextRun] = []
        for run in para.runs:
            runs.append(TextRun(text=run.text, font=extract_font_info(run)))
        if runs:  # skip empty paragraphs that have no runs
            full_text = "".join(r.text for r in runs)
            paragraphs.append(TextParagraph(runs=runs, full_text=full_text))

    # Determine text_role from placeholder type
    text_role = "other"
    if shape.is_placeholder:
        ph_type = shape.placeholder_format.type
        if ph_type in (
            PP_PLACEHOLDER.TITLE,
            PP_PLACEHOLDER.CENTER_TITLE,
            PP_PLACEHOLDER.SUBTITLE,
        ):
            text_role = "title"
        elif ph_type in (
            PP_PLACEHOLDER.BODY,
            PP_PLACEHOLDER.OBJECT,
        ):
            text_role = "body"

    return {
        "has_text": True,
        "text_role": text_role,
        "paragraphs": paragraphs,
    }


# ---------------------------------------------------------------------------
# Shape classification
# ---------------------------------------------------------------------------

def classify_shape(shape, z_order: int) -> ShapeRecord:
    """Classify a python-pptx shape (or compatible mock) into a ShapeRecord.

    Classification priority (highest first):
        1. SmartArt  — has_smart_art attribute or IGX_GRAPHIC type
        2. Chart     — has_chart attribute
        3. OLE       — EMBEDDED_OLE_OBJECT / LINKED_OLE_OBJECT type
        4. Table     — has_table attribute
        5. Picture   — PICTURE shape type
        6. Text      — shape has a text_frame
        7. Other     — everything else
    """
    base = {
        "shape_id": shape.shape_id,
        "name": shape.name,
        "z_order": z_order,
        "left": int(shape.left or 0),
        "top": int(shape.top or 0),
        "width": int(shape.width or 0),
        "height": int(shape.height or 0),
    }

    # 1. SmartArt — python-pptx 1.0+ exposes has_smart_art; also check enum
    if getattr(shape, "has_smart_art", False):
        return ShapeRecord(**base, content_source="smartart")
    if shape.shape_type == MSO_SHAPE_TYPE.IGX_GRAPHIC:
        return ShapeRecord(**base, content_source="smartart")

    # 2. Chart
    if getattr(shape, "has_chart", False):
        return ShapeRecord(**base, content_source="chart")

    # 3. OLE object (embedded or linked)
    if shape.shape_type in (
        MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT,
        MSO_SHAPE_TYPE.LINKED_OLE_OBJECT,
    ):
        return ShapeRecord(**base, content_source="ole_object")

    # 4. Table
    if getattr(shape, "has_table", False):
        return ShapeRecord(**base, content_source="table")

    # 5. Picture
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        return ShapeRecord(**base, content_source="image", has_image=True)

    # 6. Text frame
    if shape.has_text_frame:
        text_data = extract_text_content(shape)
        return ShapeRecord(**base, content_source="text", **text_data)

    # 7. Fallback
    return ShapeRecord(**base, content_source="other")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_pptx(pptx_data: bytes | Path) -> list[SlideRecord]:
    """Parse a PPTX file into a list of SlideRecord objects.

    Parameters
    ----------
    pptx_data:
        Either raw bytes of a PPTX file or a :class:`pathlib.Path` pointing
        to one on disk.

    Returns
    -------
    list[SlideRecord]
        One record per slide, slide_index is 0-based, slide_number is 1-based.
        png_path is set to ``"slide_{NNN}.png"`` (3-digit zero-padded).
        Speaker notes are intentionally excluded (per D-05).
    """
    if isinstance(pptx_data, Path):
        prs = Presentation(str(pptx_data))
    else:
        prs = Presentation(BytesIO(pptx_data))

    slides: list[SlideRecord] = []
    for slide_idx, slide in enumerate(prs.slides):
        shapes: list[ShapeRecord] = []
        for z_order, shape in enumerate(slide.shapes):
            shapes.append(classify_shape(shape, z_order))

        slides.append(
            SlideRecord(
                slide_index=slide_idx,
                slide_number=slide_idx + 1,
                png_path=f"slide_{slide_idx + 1:03d}.png",
                shapes=shapes,
            )
        )

    return slides
