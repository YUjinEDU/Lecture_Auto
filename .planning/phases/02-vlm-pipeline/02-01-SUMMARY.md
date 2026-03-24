---
phase: 02-vlm-pipeline
plan: 01
subsystem: pipeline
tags: [celery, redis, vlm, qwen3-vl, pydantic, async-tasks, sse]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: "SlideManifest, SlideRecord, JobPaths, VlmNote, load_vlm, build_vlm_prompt"
  - phase: 01.1-mvp-demo
    provides: "VLM visual notes generation, generate_visual_notes"
provides:
  - "Celery app with GPU-safe config (concurrency=1, acks_late)"
  - "Resumable VLM task (process_slides_task) with file-based checkpointing"
  - "Redis pub/sub progress publisher (publish_progress, get_last_progress)"
  - "Extended VlmNote with needs_review + token_overlap_ratio"
  - "generate_single_note atomic function for per-slide VLM inference"
  - "compute_token_overlap for hallucination detection"
  - "JobStatus enum + ProgressEvent schema"
affects: [02-02-PLAN, 03-script-ui]

# Tech tracking
tech-stack:
  added: ["celery[redis]>=5.4", "redis>=5.0", "sse-starlette>=2.0"]
  patterns: ["GPU-safe Celery worker (concurrency=1)", "file-based resumability", "Redis pub/sub for progress events", "token overlap hallucination detection"]

key-files:
  created:
    - lecture_auto/tasks/__init__.py
    - lecture_auto/tasks/celery_app.py
    - lecture_auto/tasks/vlm_tasks.py
    - lecture_auto/tasks/progress.py
    - lecture_auto/schemas/job_status.py
    - tests/test_vlm_tasks.py
    - tests/test_progress.py
    - tests/test_token_overlap.py
  modified:
    - lecture_auto/pipeline/vlm.py
    - lecture_auto/schemas/__init__.py
    - pyproject.toml
    - requirements.txt
    - .env.example

key-decisions:
  - "Token overlap threshold 0.30 for needs_review flag (balances false positives vs missed hallucinations)"
  - "Image-heavy slides (parsed_token_count <= 10) skip needs_review to avoid false flags"
  - "Redis db=2 for progress events, separate from Celery broker (db=0) and result backend (db=1)"
  - "Last-progress persistence via Redis SET with 24h TTL for late-joining SSE clients"

patterns-established:
  - "GPU-safe Celery: concurrency=1, acks_late=True, reject_on_worker_lost=True, prefetch_multiplier=1"
  - "File-based resumability: check for existing valid JSON before processing each slide"
  - "Lazy VLM model loading: singleton _vlm_model loaded on first task execution"
  - "Progress pub/sub channel format: job:{job_id}:progress"

requirements-completed: [VLM-01, VLM-02, VLM-03]

# Metrics
duration: 15min
completed: 2026-03-24
---

# Phase 2 Plan 01: Celery Infrastructure + VLM Refactoring Summary

**Celery task infrastructure with GPU-safe config, resumable VLM task with file-based checkpointing, Redis progress publisher, and token overlap hallucination detection**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-24
- **Completed:** 2026-03-24
- **Tasks:** 2
- **Files modified:** 15

## Accomplishments
- Extended VlmNote with needs_review + token_overlap_ratio fields for hallucination detection
- Extracted generate_single_note as atomic unit; compute_token_overlap handles Korean + English + edge cases
- Celery app configured for GPU-safe operation (concurrency=1, acks_late, reject_on_worker_lost)
- Resumable VLM task skips completed slides based on file existence + field validation
- Redis pub/sub progress publisher with last-progress persistence for late-joining clients
- JobStatus enum + ProgressEvent schema for pipeline status tracking
- 29 tests covering all new functionality

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend VlmNote + compute_token_overlap + generate_single_note + JobStatus** - `c569268` (test) + `d9ba527` (feat) — TDD: failing tests then implementation
2. **Task 2: Celery app + resumable VLM task + Redis progress publisher** - `7098e87` (feat)

## Files Created/Modified
- `lecture_auto/tasks/__init__.py` - Celery tasks package init, exports celery_app
- `lecture_auto/tasks/celery_app.py` - Celery app with GPU-safe config (concurrency=1)
- `lecture_auto/tasks/vlm_tasks.py` - process_slides_task with file-based resumability
- `lecture_auto/tasks/progress.py` - Redis pub/sub progress publisher + get_last_progress
- `lecture_auto/schemas/job_status.py` - JobStatus enum + ProgressEvent schema
- `lecture_auto/pipeline/vlm.py` - Extended VlmNote, compute_token_overlap, generate_single_note, _extract_slide_text
- `lecture_auto/schemas/__init__.py` - Added JobStatus + ProgressEvent exports
- `pyproject.toml` - Added celery[redis], redis, sse-starlette deps
- `requirements.txt` - Added celery[redis], redis, sse-starlette deps
- `.env.example` - Added REDIS_URL, CELERY_RESULT_BACKEND, REDIS_PROGRESS_DB
- `tests/test_token_overlap.py` - Token overlap, VlmNote extension, generate_single_note, JobStatus tests
- `tests/test_vlm_tasks.py` - Resumability, progress publishing, error handling tests
- `tests/test_progress.py` - Redis pub/sub mock tests, reset_redis_client test

## Decisions Made
- Token overlap threshold set to 0.30 for needs_review (balances sensitivity vs false positives)
- Image-heavy slides (parsed_token_count <= 10) skip needs_review to avoid false flags on diagram slides
- Redis db=2 for progress events, separate from Celery broker (db=0) and result backend (db=1)
- Last-progress persistence via Redis SET with 24h TTL enables late-joining SSE clients to get current state

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required. Redis environment variables added to .env.example for future deployment.

## Next Phase Readiness
- Celery task infrastructure ready for 02-02 (FastAPI job routes + SSE progress streaming)
- process_slides_task can be called from FastAPI endpoints via `.delay(job_id)`
- Progress events available via Redis pub/sub for SSE streaming
- JobStatus + ProgressEvent schemas ready for API response models

## Self-Check: PASSED

- All 8 created files verified on disk
- All 3 task commits verified in git log (c569268, d9ba527, 7098e87)
- 29/29 tests passing

---
*Phase: 02-vlm-pipeline*
*Completed: 2026-03-24*
