---
phase: 03-script-ui
plan: 01
subsystem: parsing
tags: [pymupdf, pdfplumber, pdf, fitz]

requires:
  - phase: 01-foundation
    provides: SlideManifest/SlideRecord/ShapeRecord schemas, LibreOffice renderer
provides:
  - PyMuPDF-based PDF parser with span-level font metadata
  - Title auto-detection via y-position + font-size + bold flags heuristic
  - pdfplumber table fallback for structured table extraction
  - Dual input support (PPTX via LibreOffice conversion + direct PDF)
affects: [03-02-script-task, vlm-pipeline]

tech-stack:
  added: [PyMuPDF (fitz), pdfplumber]
  patterns: [span-level font metadata extraction, title heuristic detection]

key-files:
  created: [lecture_auto/pipeline/parser_pdf.py, tests/test_parser_pdf.py]
  modified: [pyproject.toml, lecture_auto/pipeline/__init__.py]

key-decisions:
  - "PyMuPDF page.get_text('dict') for block/line/span hierarchy with font metadata"
  - "Title detection: y < page_height*0.25 AND font_size > median*1.3 AND bold flag (& 16)"
  - "pdfplumber used only for table extraction fallback, not primary parsing"
  - "Speaker notes excluded per D-05/D-11"

patterns-established:
  - "PDF span-level parsing: extract font size, bold flags, bbox per text span"
  - "Dual-input pattern: parse_input() dispatches PPTX→LibreOffice→PDF or direct PDF"

requirements-completed: [SCRIPT-01, SCRIPT-02]

duration: 8min
completed: 2026-03-30
---

# Plan 03-01: PyMuPDF PDF Parser Summary

**Replaced python-pptx text extraction with PyMuPDF span-level parser — title auto-detection via font metadata, pdfplumber table fallback, dual PPTX/PDF input.**

## What Was Built

- `parser_pdf.py`: PyMuPDF-based PDF parser using `page.get_text("dict")` for hierarchical block/line/span extraction with font size, bold flags, and bbox positions
- Title heuristic: spans in top 25% of page + font size > 1.3x median + bold flag → automatically tagged as title ShapeRecord
- pdfplumber integration for table-heavy slides: `extract_tables_fallback()` returns structured table text
- `parse_input()` entry point accepts both `.pptx` (converts via LibreOffice) and `.pdf` files
- 16 unit tests covering title detection, table fallback, Korean text, and input dispatch

## Self-Check: PASSED

- [x] `parser_pdf.py` contains `parse_pdf_slides` function
- [x] `parser_pdf.py` contains `is_title_span` heuristic
- [x] `parser_pdf.py` imports `fitz` (PyMuPDF)
- [x] `parser_pdf.py` imports `pdfplumber`
- [x] `parse_input` function handles both `.pptx` and `.pdf`
- [x] 16/16 tests pass
- [x] No speaker notes extraction (D-11)
