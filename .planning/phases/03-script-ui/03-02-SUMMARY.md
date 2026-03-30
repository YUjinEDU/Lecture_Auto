---
phase: 03-script-ui
plan: 02
subsystem: api
tags: [celery, fastapi, sse, pydantic, script-generation, crud]

# Dependency graph
requires:
  - phase: 02-vlm-pipeline
    provides: "Celery app, progress publishing, SSE pattern, job routes, JobPaths"
  - phase: 01.1-mvp-demo
    provides: "script_gen.py with call_claude, build_script_prompt, _parse_script_json"
provides:
  - "generate_scripts_task Celery task on cpu_queue with per-slide checkpointing"
  - "regenerate_slide_task for single-slide re-generation with edited flag protection"
  - "Script CRUD API: list, update, regenerate, approve, SSE progress, slide PNG"
  - "ScriptUpdateRequest, ScriptResponse, ScriptApproveResponse Pydantic schemas"
  - "cpu_queue/gpu_queue task routing in Celery config"
  - "script_generating/script_completed JobStatus enum values"
affects: [03-script-ui, 04-tts-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns: [cpu_queue routing for non-GPU tasks, per-slide file-based checkpointing for scripts, edited flag protection with force override]

key-files:
  created:
    - lecture_auto/tasks/script_tasks.py
    - lecture_auto/api/routes/scripts.py
    - lecture_auto/schemas/script.py
    - tests/test_script_tasks.py
    - tests/test_scripts_api.py
  modified:
    - lecture_auto/tasks/celery_app.py
    - lecture_auto/schemas/job_status.py
    - lecture_auto/api/main.py

key-decisions:
  - "cpu_queue for script tasks separates Claude subprocess from GPU workload"
  - "Per-slide checkpointing in task (not wrapping generate_scripts()) for resumability"
  - "Immutable update pattern for script edits (new dict, not mutation)"

patterns-established:
  - "cpu_queue routing: script.* -> cpu_queue, vlm.* -> gpu_queue via task_routes"
  - "Edited flag protection: PUT sets edited=true, regenerate returns 409 unless force=true"
  - "Atomic JSON writes: .tmp + os.rename for crash-safe checkpoints"

requirements-completed: [SCRIPT-01, SCRIPT-02, SCRIPT-03, SCRIPT-04, UI-03, UI-05]

# Metrics
duration: 12min
completed: 2026-03-30
---

# Phase 03 Plan 02: Script Task + API Summary

**Resumable Celery script task on cpu_queue with CRUD/regenerate/approve REST API, edit protection, and SSE progress streaming**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-30T07:51:53Z
- **Completed:** 2026-03-30T08:04:00Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Script generation runs as resumable Celery task with per-slide file-based checkpointing on cpu_queue
- 6 FastAPI endpoints: list scripts, update script, regenerate slide, approve all, SSE progress, serve slide PNG
- Edit protection: PUT marks edited=true, regenerate returns 409 unless force=true, approve validates all non-empty
- Task routing: script.* -> cpu_queue, vlm.* -> gpu_queue configured in celery_app

## Task Commits

Each task was committed atomically:

1. **Task 1: Script Celery task + schemas + Celery cpu_queue routing** - `0917183` (feat)
2. **Task 2: FastAPI script routes + SSE progress + wire into app** - `e6f3f46` (feat)

_Both tasks used TDD: RED (failing tests) -> GREEN (implementation) -> verify_

## Files Created/Modified
- `lecture_auto/tasks/script_tasks.py` - Celery tasks: generate_scripts_task (batch), regenerate_slide_task (single)
- `lecture_auto/api/routes/scripts.py` - 6 REST endpoints for script CRUD + SSE progress + slide PNG
- `lecture_auto/schemas/script.py` - ScriptUpdateRequest, ScriptResponse, ScriptApproveResponse
- `lecture_auto/tasks/celery_app.py` - Added task_routes for cpu_queue/gpu_queue separation
- `lecture_auto/schemas/job_status.py` - Added script_generating, script_completed enum values
- `lecture_auto/api/main.py` - Wired scripts.router, bumped version to 0.3.0
- `tests/test_script_tasks.py` - 10 tests (5 schema, 5 task)
- `tests/test_scripts_api.py` - 12 integration tests for all endpoints

## Decisions Made
- Used cpu_queue for script tasks since Claude CLI is a CPU-bound subprocess, not GPU
- Implemented per-slide loop inside task rather than wrapping generate_scripts() to enable checkpointing
- Used immutable update pattern for script edits (create new dict from existing + changes)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Celery `__wrapped__` with `bind=True` strips `self` parameter -- tests needed to call with just `(job_id)` not `(mock_self, job_id)`
- Late-import mocking: task functions import dependencies inside function body, requiring patches at source module level

## Known Stubs

None - all endpoints are fully functional with real file I/O.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Script CRUD API ready for professor review UI (Plan 03)
- TTS trigger placeholder in approve endpoint ready for Phase 4
- SSE progress stream functional for real-time UI updates

## Self-Check: PASSED

All 5 created files exist. Both task commits (0917183, e6f3f46) verified in git log.

---
*Phase: 03-script-ui*
*Completed: 2026-03-30*
