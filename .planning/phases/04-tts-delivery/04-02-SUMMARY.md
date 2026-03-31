---
phase: 04-tts-delivery
plan: 02
subsystem: api
tags: [fastapi, tts, sse, zipstream, voice-clone, file-upload]

requires:
  - phase: 04-tts-delivery-01
    provides: "TTS pipeline (synthesize_slide, merge_audio), Celery tasks (synthesize_job_task, regenerate_slide_tts_task), voice_store, TTS schemas"
provides:
  - "TTS voice registration endpoint (WAV/WebM upload)"
  - "Individual slide audio serving for preview playback"
  - "TTS progress SSE endpoint filtered for tts stage"
  - "Streaming ZIP download of full lecture package"
  - "Approve endpoint auto-triggers TTS Celery task (D-08)"
affects: [05-integration, frontend-tts-ui]

tech-stack:
  added: [zipstream-ng, python-multipart]
  patterns: [streaming-zip-download, file-upload-with-conversion]

key-files:
  created:
    - lecture_auto/api/routes/tts.py
    - lecture_auto/api/routes/download.py
  modified:
    - lecture_auto/api/routes/scripts.py
    - lecture_auto/api/main.py
    - pyproject.toml

key-decisions:
  - "ZIP_STORED compression for WAV/MP4 (already compressed, no CPU overhead)"
  - "Combined scripts.json array in ZIP instead of per-slide JSON files"

patterns-established:
  - "File upload with auto-conversion: WebM detected by content_type, converted via ffmpeg"
  - "Streaming ZIP via zipstream-ng: no full ZIP buffered in memory"

requirements-completed: [TTS-01, TTS-03, UI-04]

duration: 3min
completed: 2026-03-31
---

# Phase 04 Plan 02: TTS API Routes Summary

**FastAPI endpoints for voice registration, slide audio preview, TTS SSE progress, streaming ZIP download, and approve-to-TTS wiring**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-31T11:11:02Z
- **Completed:** 2026-03-31T11:13:44Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Created TTS router with voice registration (WAV/WebM), audio serving, re-TTS, and SSE progress endpoints
- Created download router with package listing and streaming ZIP generation via zipstream-ng
- Wired approve endpoint to automatically trigger TTS Celery task (D-08 complete)
- Registered both new routers in main.py and bumped API version to 0.4.0

## Task Commits

Each task was committed atomically:

1. **Task 1: Create TTS API routes + download endpoint** - `1dacd98` (feat)
2. **Task 2: Wire approve endpoint to TTS + register new routers** - `4507e6e` (feat)

## Files Created/Modified
- `lecture_auto/api/routes/tts.py` - Voice registration, audio serving, re-TTS dispatch, SSE progress (5 endpoints)
- `lecture_auto/api/routes/download.py` - Package listing and streaming ZIP download (2 endpoints)
- `lecture_auto/api/routes/scripts.py` - approve_scripts() now triggers synthesize_job_task
- `lecture_auto/api/main.py` - Added tts and download router includes, version 0.4.0
- `pyproject.toml` - Added zipstream-ng and python-multipart dependencies
- `uv.lock` - Updated lockfile

## Decisions Made
- ZIP uses STORED compression (no deflate) since WAV and MP4 are already compressed data
- Scripts are combined into a single `scripts.json` array in the ZIP rather than individual per-slide files
- Voice registration uses professor_id="default" for MVP (matches INFRA-03 deferral)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing python-multipart dependency**
- **Found during:** Task 1 (TTS routes creation)
- **Issue:** FastAPI UploadFile requires python-multipart, not in project dependencies
- **Fix:** `uv add python-multipart`
- **Files modified:** pyproject.toml, uv.lock
- **Verification:** Import succeeds, route registration passes
- **Committed in:** 1dacd98 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential dependency for file upload. No scope creep.

## Issues Encountered
None beyond the missing dependency above.

## Known Stubs
None - all endpoints are fully wired to real pipeline functions.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All TTS API endpoints operational (voice, audio, progress, download)
- Approve-to-TTS pipeline fully connected end-to-end
- Ready for Phase 04 Plan 03 (integration tests) or Phase 05 (frontend TTS UI)

---
*Phase: 04-tts-delivery*
*Completed: 2026-03-31*
