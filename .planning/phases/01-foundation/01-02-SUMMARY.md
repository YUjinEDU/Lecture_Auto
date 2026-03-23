---
phase: 01-foundation
plan: 02
subsystem: pipeline/parser
tags: [pptx, parsing, python-pptx, tdd, shape-classification]
completed: "2026-03-23T10:11:37Z"
duration_minutes: 3

dependency_graph:
  requires: ["01-01"]
  provides: ["lecture_auto.pipeline.parser", "parse_pptx", "classify_shape"]
  affects: ["02-vlm", "02-renderer"]

tech_stack:
  added: ["python-pptx>=1.0.2"]
  patterns: ["TDD RED/GREEN", "EMU-to-pt conversion", "placeholder type mapping"]

key_files:
  created:
    - lecture_auto/pipeline/__init__.py
    - lecture_auto/pipeline/parser.py
    - tests/__init__.py
    - tests/test_parser.py
  modified: []

decisions:
  - "PP_PLACEHOLDER.SUBTITLE maps to text_role=title (same as TITLE/CENTER_TITLE) — matches plan spec for title-slide subtitle"
  - "Empty paragraphs (no runs) are silently skipped to avoid empty TextParagraph entries"
  - "EMU conversion: font.size / 12700 (not Pt() constructor which takes points, not EMU)"

metrics:
  duration_minutes: 3
  tasks_completed: 1
  files_created: 4
  files_modified: 0
  tests_written: 29
  tests_passing: 29
---

# Phase 01 Plan 02: PPTX Parser Summary

**One-liner:** python-pptx shape classifier that converts PPTX bytes to typed SlideRecord list with full shape/font/bounding-box metadata.

## What Was Built

`lecture_auto/pipeline/parser.py` — the first stage of the lecture automation pipeline.

### Functions

| Function | Purpose |
|----------|---------|
| `parse_pptx(pptx_data)` | Convert PPTX bytes or Path → `list[SlideRecord]` |
| `classify_shape(shape, z_order)` | Route shape to correct `content_source` category |
| `extract_text_content(shape)` | Extract paragraphs, runs, and `text_role` from text frames |
| `extract_font_info(run)` | Extract `FontInfo` (name, size_pt, bold, italic) from a run |

### Shape Classification Priority

1. SmartArt — `has_smart_art` attr or `IGX_GRAPHIC` shape type
2. Chart — `has_chart` attr
3. OLE — `EMBEDDED_OLE_OBJECT` / `LINKED_OLE_OBJECT` shape type
4. Table — `has_table` attr
5. Picture — `PICTURE` shape type
6. Text — shape has a `text_frame`
7. Other — fallback

### text_role Mapping

| Placeholder type | text_role |
|------------------|-----------|
| TITLE, CENTER_TITLE, SUBTITLE | `"title"` |
| BODY, OBJECT | `"body"` |
| non-placeholder | `"other"` |

## Tests

29 unit tests across 15 behavioral categories:
- Slide indexing (0-based index, 1-based number)
- Shape content_source classification for all 7 types
- text_role assignment (title / body / other)
- Font extraction (name, size_pt, bold, italic)
- Bounding box integers in EMU
- z_order sequential from 0
- TextParagraph.full_text == concatenated run texts
- png_path `"slide_{NNN}.png"` format with 3-digit zero-padding

## Deviations from Plan

None — plan executed exactly as written.

The font.size EMU note in the plan was applied correctly: `font.size / 12700` (not the `Pt()` constructor).

## Known Stubs

None — all plan behaviors are fully wired and tested.

## Self-Check

- [x] `lecture_auto/pipeline/parser.py` exists
- [x] `tests/test_parser.py` exists with 29 test functions
- [x] All 29 tests pass (`29 passed in 1.26s`)
- [x] `from lecture_auto.pipeline.parser import parse_pptx, classify_shape` succeeds
- [x] Parser contains all required acceptance criteria strings

## Self-Check: PASSED
