---
phase: 01-foundation
plan: 01
subsystem: infra
tags: [pydantic, python, schemas, fastapi, job-paths]

requires: []
provides:
  - "Pydantic v2 models: FontInfo, TextRun, TextParagraph, ShapeRecord, SlideRecord, LectureStyle, SlideManifest"
  - "JobPaths class managing /data/work/{job_id}/ with 8 subdirectories"
  - "UploadResponse API response model"
  - "requirements.txt with pinned Python dependencies"
  - ".env.example documenting all required environment variables"
affects: [02-parse, 03-render, 04-api]

tech-stack:
  added: [pydantic>=2.0, python-pptx==1.0.2, fastapi==0.135.1, supabase>=2.28.3, PyJWT>=2.9.0]
  patterns: ["Pydantic v2 BaseModel for all data contracts", "pathlib.Path throughout for filesystem ops", "Literal types for constrained fields"]

key-files:
  created:
    - lecture_auto/__init__.py
    - lecture_auto/schemas/manifest.py
    - lecture_auto/schemas/request.py
    - lecture_auto/schemas/__init__.py
    - lecture_auto/storage/jobs.py
    - lecture_auto/storage/__init__.py
    - requirements.txt
    - pyproject.toml
    - .env.example
  modified: []

key-decisions:
  - "ShapeRecord stores bounding box in EMU (left/top/width/height) per D-04"
  - "No speaker_notes field in any schema per D-05 — VLM handles visual content"
  - "has_image bool flag on ShapeRecord, no image binary extraction per D-06"
  - "text_role Literal['title','body','other'] discriminates text box types per D-07"
  - "LectureStyle has exactly 3 axes: density/tone/approach per D-01/D-02/D-03"
  - "JobPaths has 8 subdirs: input, parsed, rendered, vlm, scripts, audio, logs, artifacts"

patterns-established:
  - "Pydantic v2 BaseModel: use Field(default_factory=...) for mutable defaults"
  - "JobPaths: pass root= in tests with tempfile.TemporaryDirectory() to avoid /data/work dependency"
  - "package imports: re-export from __init__.py using __all__"

requirements-completed: [PARSE-03, INFRA-04, INPUT-02]

duration: 12min
completed: 2026-03-23
---

# Phase 01 Plan 01: Foundation — Project Skeleton Summary

**Pydantic v2 SlideManifest type contracts with 7 models, JobPaths directory manager for /data/work/{job_id}/, and pinned Python dependency manifest**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-03-23T09:40:00Z
- **Completed:** 2026-03-23T09:52:00Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Python package `lecture_auto/` created and importable with schemas and storage submodules
- Pydantic v2 models covering the full slide manifest structure (FontInfo → SlideManifest), validated against sample data
- JobPaths helper creates all 8 pipeline subdirectories atomically under /data/work/{job_id}/
- requirements.txt with exact pinned versions for all Phase 1 dependencies
- .env.example documenting every required environment variable (SUPABASE_JWT_SECRET, JOB_OUTPUT_ROOT, RENDER_DPI, etc.)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create project skeleton, dependencies, and env template** - `37f7898` (chore)
2. **Task 2: Create Pydantic v2 Slide Manifest schemas and storage helper** - `e197be6` (feat)

## Files Created/Modified
- `lecture_auto/__init__.py` - Package marker
- `lecture_auto/schemas/manifest.py` - Pydantic v2 models: FontInfo, TextRun, TextParagraph, ShapeRecord, SlideRecord, LectureStyle, SlideManifest
- `lecture_auto/schemas/request.py` - UploadResponse model for API responses
- `lecture_auto/schemas/__init__.py` - Public re-exports with __all__
- `lecture_auto/storage/jobs.py` - JobPaths class with 8 subdirectory properties and ensure_dirs()
- `lecture_auto/storage/__init__.py` - Public re-exports
- `requirements.txt` - All Phase 1 Python dependencies pinned
- `pyproject.toml` - Project metadata, requires-python>=3.11, pytest config
- `.env.example` - Environment variable template for GPU server deployment

## Decisions Made
- No speaker_notes anywhere in schema (D-05) — VLM handles visual interpretation directly
- ShapeRecord bounding box stored in EMU (integer) matching python-pptx native units (D-04)
- LectureStyle supplement field added as free-text override alongside 3 Literal axes
- JobPaths root defaults to JOB_OUTPUT_ROOT env var falling back to /data/work

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- System Python had no pydantic installed. Used `pip3 install pydantic --break-system-packages` for local verification. This is expected on a fresh GPU server; production deployment will use a virtual environment per requirements.txt.

## User Setup Required

None — no external service configuration required for this plan. Environment variables are documented in `.env.example` for GPU server deployment.

## Next Phase Readiness
- All type contracts established; parse plan (01-02) can import SlideManifest directly
- JobPaths tested and ready for pipeline workers to call ensure_dirs()
- No blockers for 01-02 (PPTX parser) or 01-03 (LibreOffice renderer)

---
*Phase: 01-foundation*
*Completed: 2026-03-23*
