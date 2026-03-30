"""
PDF parsing module -- replacement for python-pptx text extraction.

Uses PyMuPDF (fitz) for span-level font metadata extraction, enabling
automatic title detection via y-position + font-size + bold heuristic.
pdfplumber provides table extraction as a fallback for table-heavy slides.

Exports
-------
parse_pdf                -- parse a PDF file into list[SlideRecord]
parse_pdf_page           -- parse a single PDF page into a SlideRecord
is_title_span            -- heuristic: is this span a title?
extract_tables_fallback  -- pdfplumber-based table extraction
parse_input              -- dispatch PPTX or PDF to appropriate parser
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pdfplumber
import pymupdf

from lecture_auto.schemas.manifest import (
    FontInfo,
    ShapeRecord,
    SlideRecord,
    TextParagraph,
    TextRun,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMU_PER_POINT = 12700
"""Conversion factor: 1 PDF point = 12700 EMU (English Metric Units)."""

TITLE_Y_FRACTION = 0.25
"""Title heuristic: span must be in top 25% of page height."""

TITLE_MIN_FONT_SIZE = 18.0
"""Title heuristic: minimum font size (pt) to qualify as title."""

BOLD_FLAG = 16
"""PyMuPDF span flags bitmask for bold (superscript=1, italic=2, serif=4, mono=8, bold=16)."""

ITALIC_FLAG = 2
"""PyMuPDF span flags bitmask for italic."""


# ---------------------------------------------------------------------------
# Title detection heuristic (D-08)
# ---------------------------------------------------------------------------

def is_title_span(span: dict, page_height: float) -> bool:
    """Determine if a text span is a title based on position and font.

    A span qualifies as title if ALL of:
      1. Its y-position (bbox[1]) is in the top 25% of the page
    AND ANY of:
      2a. Font size >= 18.0 pt
      2b. Bold flag set (flags & 16)
      2c. Font name contains "Bold" (secondary signal per RESEARCH.md Pitfall 1)

    Parameters
    ----------
    span : dict
        PyMuPDF span dict with keys: bbox, size, flags, font
    page_height : float
        Total page height in points.

    Returns
    -------
    bool
    """
    y_top = span["bbox"][1]
    if y_top >= page_height * TITLE_Y_FRACTION:
        return False

    font_size = span.get("size", 0.0)
    flags = span.get("flags", 0)
    font_name = span.get("font", "")

    if font_size >= TITLE_MIN_FONT_SIZE:
        return True
    if bool(flags & BOLD_FLAG):
        return True
    if "Bold" in font_name:
        return True

    return False


# ---------------------------------------------------------------------------
# Single-page parser
# ---------------------------------------------------------------------------

def parse_pdf_page(page, page_num: int) -> SlideRecord:
    """Parse a single PyMuPDF page into a SlideRecord.

    Text blocks (type==0) become text ShapeRecords with font metadata.
    Image blocks (type==1) become image ShapeRecords.
    Bounding boxes are converted from PDF points to EMU.

    Parameters
    ----------
    page : pymupdf.Page
        An open PyMuPDF page object.
    page_num : int
        Zero-based page index.

    Returns
    -------
    SlideRecord
    """
    page_height = page.rect.height
    text_dict = page.get_text("dict")
    blocks = text_dict.get("blocks", [])

    shapes: list[ShapeRecord] = []
    shape_id = 0

    for block in blocks:
        block_type = block.get("type", 0)
        bbox = block.get("bbox", (0, 0, 0, 0))

        # Convert bbox from points to EMU
        left = int(bbox[0] * EMU_PER_POINT)
        top = int(bbox[1] * EMU_PER_POINT)
        width = int((bbox[2] - bbox[0]) * EMU_PER_POINT)
        height = int((bbox[3] - bbox[1]) * EMU_PER_POINT)

        if block_type == 1:
            # Image block
            shapes.append(ShapeRecord(
                shape_id=shape_id,
                name=f"image_{shape_id}",
                z_order=shape_id,
                left=left,
                top=top,
                width=width,
                height=height,
                content_source="image",
                has_image=True,
            ))
            shape_id += 1
            continue

        if block_type != 0:
            # Unknown block type -- skip
            continue

        # Text block (type==0)
        lines = block.get("lines", [])
        paragraphs: list[TextParagraph] = []
        block_is_title = False

        for line in lines:
            spans = line.get("spans", [])
            runs: list[TextRun] = []

            for span in spans:
                text = span.get("text", "")
                if not text.strip():
                    continue

                font_name = span.get("font", None)
                font_size = round(span.get("size", 0.0), 1)
                flags = span.get("flags", 0)
                is_bold = bool(flags & BOLD_FLAG) or ("Bold" in (font_name or ""))
                is_italic = bool(flags & ITALIC_FLAG)

                runs.append(TextRun(
                    text=text,
                    font=FontInfo(
                        name=font_name,
                        size_pt=font_size,
                        bold=is_bold,
                        italic=is_italic,
                    ),
                ))

                # Check title heuristic for any span in the block
                if is_title_span(span, page_height):
                    block_is_title = True

            if runs:
                full_text = "".join(r.text for r in runs)
                paragraphs.append(TextParagraph(runs=runs, full_text=full_text))

        if not paragraphs:
            continue

        text_role = "title" if block_is_title else "body"

        shapes.append(ShapeRecord(
            shape_id=shape_id,
            name=f"text_{shape_id}",
            z_order=shape_id,
            left=left,
            top=top,
            width=width,
            height=height,
            content_source="text",
            has_text=True,
            text_role=text_role,
            paragraphs=paragraphs,
        ))
        shape_id += 1

    return SlideRecord(
        slide_index=page_num,
        slide_number=page_num + 1,
        png_path=f"slide_{page_num + 1:03d}.png",
        shapes=shapes,
    )


# ---------------------------------------------------------------------------
# Full PDF parser
# ---------------------------------------------------------------------------

def parse_pdf(pdf_path: str | Path) -> list[SlideRecord]:
    """Parse a PDF file into a list of SlideRecord objects.

    Parameters
    ----------
    pdf_path : str | Path
        Path to the PDF file.

    Returns
    -------
    list[SlideRecord]
        One record per page, with font metadata at span level.
    """
    doc = pymupdf.open(str(pdf_path))
    try:
        slides: list[SlideRecord] = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            slides.append(parse_pdf_page(page, page_num))
        return slides
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Table fallback via pdfplumber (D-09)
# ---------------------------------------------------------------------------

def extract_tables_fallback(
    pdf_path: str | Path,
    page_num: int,
) -> list[list[list[str]]]:
    """Extract tables from a specific PDF page using pdfplumber.

    Parameters
    ----------
    pdf_path : str | Path
        Path to the PDF file.
    page_num : int
        Zero-based page index.

    Returns
    -------
    list[list[list[str]]]
        List of tables, each table is a list of rows, each row is a list
        of cell strings. Returns empty list if no tables detected.
    """
    with pdfplumber.open(str(pdf_path)) as pdf:
        if page_num >= len(pdf.pages):
            return []
        page = pdf.pages[page_num]
        tables = page.extract_tables()
        if not tables:
            return []
        # Normalize None cells to empty strings
        return [
            [[cell if cell is not None else "" for cell in row] for row in table]
            for table in tables
        ]


# ---------------------------------------------------------------------------
# Input dispatcher (D-10)
# ---------------------------------------------------------------------------

def parse_input(input_path: Path) -> list[SlideRecord]:
    """Parse either a PPTX or PDF file into SlideRecord list.

    - .pdf  => parse_pdf directly
    - .pptx => convert via LibreOffice headless to PDF, then parse_pdf

    Parameters
    ----------
    input_path : Path
        Path to the input file (.pdf or .pptx).

    Returns
    -------
    list[SlideRecord]

    Raises
    ------
    ValueError
        If the file extension is not supported.
    subprocess.CalledProcessError
        If LibreOffice conversion fails.
    """
    input_path = Path(input_path)
    suffix = input_path.suffix.lower()

    if suffix == ".pdf":
        return parse_pdf(input_path)

    if suffix == ".pptx":
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Per existing pattern: per-job UserInstallation dir to prevent lock-file races
            user_install = Path(tmp_dir) / "user_install"
            user_install.mkdir()

            subprocess.run(
                [
                    "soffice",
                    "--headless",
                    f"-env:UserInstallation=file://{user_install}",
                    "--convert-to", "pdf",
                    "--outdir", tmp_dir,
                    str(input_path),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )

            # Find the converted PDF
            pdf_files = list(Path(tmp_dir).glob("*.pdf"))
            if not pdf_files:
                msg = f"LibreOffice conversion produced no PDF for {input_path}"
                raise RuntimeError(msg)

            return parse_pdf(pdf_files[0])

    raise ValueError(f"Unsupported file extension: {suffix!r}. Expected .pdf or .pptx")
