---
phase: 01-foundation
plan: 03
subsystem: pipeline/rendering
tags: [rendering, libreoffice, pdf2image, tofu-detection, korean-fonts, tdd]
dependency_graph:
  requires: [01-01]
  provides: [render_slides, pptx_to_pdf, pdf_to_pngs, detect_font_issues, check_font_substitution, has_tofu_regions]
  affects: [02-vlm]
tech_stack:
  added: [pdf2image, pillow, numpy]
  patterns: [tdd, subprocess-isolation, pixel-heuristic]
key_files:
  created:
    - lecture_auto/pipeline/tofu_detector.py
    - lecture_auto/pipeline/renderer.py
    - tests/test_tofu_detector.py
    - tests/test_renderer.py
  modified:
    - pyproject.toml
decisions:
  - "Per-job LibreOffice UserInstallation dir prevents lock-file races in concurrent scenarios"
  - "Font issues are warnings only (D-13): pipeline never stops for tofu detection results"
  - "pdf2image DPI defaults from RENDER_DPI env var (150 default) for easy tuning without code changes"
metrics:
  duration: "~20 min"
  completed: "2026-03-23"
  tasks: 2
  files: 5
---

# Phase 01 Plan 03: Slide Rendering Pipeline Summary

**One-liner:** LibreOffice headless PPTX-to-PDF + pdf2image PDF-to-PNG with per-job process isolation and pixel-level Korean tofu detection.

## What Was Built

### Task 1: Korean Font Tofu Detection (`tofu_detector.py`)

Three exported functions:

- `check_font_substitution(soffice_stderr)` — parses LibreOffice stderr for lines containing "substitut", "font not found", "missing", or "fallback" (case-insensitive).
- `has_tofu_regions(img_path, threshold=0.95)` — grayscale pixel heuristic: if >95% of pixels exceed luminance 240, the slide likely has tofu rendering.
- `detect_font_issues(soffice_stderr, png_paths)` — combines both strategies into a single warning list. All results are warnings; pipeline never halts.

### Task 2: Rendering Pipeline (`renderer.py`)

Three exported functions:

- `pptx_to_pdf(pptx_path, output_dir, job_id, timeout=120)` — runs LibreOffice headless with `--env:UserInstallation=file:///tmp/soffice-{job_id}` for process isolation. Cleans up temp dir in `finally`. Raises `RuntimeError` on non-zero exit, `FileNotFoundError` if PDF not produced, `subprocess.TimeoutExpired` on 120s timeout.
- `pdf_to_pngs(pdf_path, output_dir, dpi=None)` — wraps `pdf2image.convert_from_path`, writes `slide_001.png`, `slide_002.png`, etc. DPI defaults to `RENDER_DPI` env var or 150.
- `render_slides(pptx_path, rendered_dir, job_id)` — orchestrates full pipeline, passes soffice stderr to `detect_font_issues`, cleans up intermediate PDF, returns `(png_paths, font_warnings)`.

## Tests

| Suite | Tests | Result |
|-------|-------|--------|
| test_tofu_detector.py | 9 | PASS |
| test_renderer.py | 9 | PASS |
| **Total** | **18** | **PASS** |

All renderer tests use `unittest.mock.patch` — no real LibreOffice or poppler needed.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

### Added Items (Rule 2 — Missing Critical)

- `pyproject.toml` updated with `dependencies` and `[project.optional-dependencies].dev` sections. The file had no dependency declarations; uv requires them for `uv sync`. Added `pillow`, `numpy`, `pdf2image`, plus `pytest` in dev extras.
- Added `[build-system]` section (hatchling) required for editable install under uv.

## Known Stubs

None. Both modules are fully implemented with real logic.

## Self-Check: PASSED

- `lecture_auto/pipeline/tofu_detector.py` — exists, contains all 3 required functions
- `lecture_auto/pipeline/renderer.py` — exists, contains all 3 required functions plus `--env:UserInstallation`, `--headless`, `--norestore`, `shutil.rmtree`, `convert_from_path`, `slide_{idx:03d}.png`, `detect_font_issues`
- `tests/test_tofu_detector.py` — exists, 9 test functions
- `tests/test_renderer.py` — exists, 9 test functions
- Commits: `f5b0020` (tofu detector), `62953e0` (renderer)
