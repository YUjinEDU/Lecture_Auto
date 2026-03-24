---
phase: 02-vlm-pipeline
plan: 02
subsystem: api
tags: [fastapi, sse, redis, async, rest-api, cors]

# Dependency graph
requires:
  - phase: 02-vlm-pipeline
    plan: 01
    provides: "process_slides_task, publish_progress, get_last_progress, JobStatus, ProgressEvent"
provides:
  - "FastAPI app with CORS and lifespan"
  - "POST /jobs/{job_id}/vlm endpoint"
  - "GET /jobs/{job_id}/status endpoint"
  - "GET /jobs/{job_id}/progress SSE endpoint"
  - "Async Redis dependency provider"
affects:
  - "Frontend SSE client integration"
  - "Auth middleware (future INFRA-03)"

# Tech stack
added:
  - sse-starlette (SSE streaming for FastAPI)
patterns:
  - "FastAPI lifespan for async resource cleanup"
  - "Redis pub/sub async SSE streaming"
  - "Late-joiner pattern: initial state from persisted progress"
  - "Singleton async Redis dependency via FastAPI Depends"

# Key files
created:
  - lecture_auto/api/__init__.py
  - lecture_auto/api/main.py
  - lecture_auto/api/deps.py
  - lecture_auto/api/routes/__init__.py
  - lecture_auto/api/routes/jobs.py
  - tests/test_jobs_api.py
modified: []

# Decisions
key-decisions:
  - "Status derived from last_progress (not Celery AsyncResult) for simplicity"
  - "SSE ping=15s keep-alive to prevent proxy timeouts"
  - "Auth middleware deferred to INFRA-03 scope"

# Metrics
duration_minutes: 8
completed: "2026-03-24T01:14:00Z"
tasks_completed: 2
tasks_total: 2
files_created: 6
files_modified: 0
---

# Phase 02 Plan 02: FastAPI Job Routes with SSE Progress Summary

FastAPI REST API exposing VLM pipeline via async job submission, status polling, and real-time SSE progress streaming with Redis pub/sub.

## What Was Built

### Task 1: FastAPI App Skeleton + Shared Dependencies
- Created FastAPI application with CORS middleware and async lifespan management
- Async Redis dependency provider (`get_async_redis`) using singleton pattern with configurable DB
- Health endpoint at `/health` returning version info
- Lifespan context manager ensures Redis connection cleanup on shutdown

### Task 2: Job Routes + Integration Tests
- **POST /jobs/{job_id}/vlm**: Validates manifest exists, submits `process_slides_task` to Celery `gpu_queue`, returns `{job_id, task_id, status: "queued"}`
- **GET /jobs/{job_id}/status**: Derives status from persisted last_progress (completed/failed/vlm_processing/unknown)
- **GET /jobs/{job_id}/progress**: SSE stream with initial state for late joiners, live progress from Redis pub/sub, 15s keep-alive ping, auto-terminates on completion
- 10 integration tests covering all endpoints: submit success/404, all status states, SSE content-type and initial event, health check

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created jobs.py in Task 1 instead of Task 2**
- **Found during:** Task 1
- **Issue:** `main.py` imports `jobs.router` at module level; Task 1 verification would fail without it
- **Fix:** Created complete `jobs.py` in Task 1 as part of the import chain
- **Files modified:** lecture_auto/api/routes/jobs.py
- **Commit:** 618ca03

## Verification Results

- All 10 tests pass: `python -m pytest tests/test_jobs_api.py -x -v`
- Routes registered: `/jobs/{job_id}/vlm`, `/jobs/{job_id}/status`, `/jobs/{job_id}/progress`, `/health`
- SSE endpoint returns `text/event-stream` content type
- Late-joiner pattern verified: initial event sent from persisted progress

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | 618ca03 | feat(02-02): FastAPI app skeleton with CORS, lifespan, shared deps, and job routes |
| 2 | 06f6491 | test(02-02): integration tests for job submit, status, SSE progress endpoints |

## Known Stubs

None - all endpoints are fully wired to Celery tasks and Redis progress system.

## Self-Check: PASSED

All 6 created files verified on disk. Both commit hashes (618ca03, 06f6491) found in git log.
