---
phase: 02-vlm-pipeline
verified: 2026-03-24T01:30:00Z
status: passed
score: 4/4 must-haves verified
re_verification: false
---

# Phase 2: VLM Pipeline Verification Report

**Phase Goal:** 재시작 가능한 비동기 작업이 슬라이드별 VLM 시각 노트 JSON을 생성한다
**Verified:** 2026-03-24T01:30:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | PPTX 업로드 후 작업이 큐에 등록되고 UI에서 단계별 진행률(%)을 실시간 확인할 수 있다 | VERIFIED | POST /jobs/{job_id}/vlm calls process_slides_task.apply_async (jobs.py:37), returns job_id + task_id + status=queued. GET /jobs/{job_id}/progress streams SSE via EventSourceResponse with Redis pub/sub (jobs.py:66-119). publish_progress emits percent field per slide (progress.py:28-44). |
| 2 | 파이프라인이 중단 후 재시작되어도 이미 완료된 슬라이드는 건너뛰고 미완료 슬라이드부터 재개된다 | VERIFIED | vlm_tasks.py:70-80 checks note_path.exists() and validates required fields (visual_summary, key_elements, teaching_points) before skipping. Invalid JSON triggers reprocessing. Tests test_skips_completed_slides and test_reprocesses_invalid_json both pass. Celery config: task_acks_late=True, task_reject_on_worker_lost=True (celery_app.py:24,27). |
| 3 | 각 슬라이드에 대해 visual summary, key elements, teaching points를 포함한 VLM 노트 JSON이 생성된다 | VERIFIED | generate_single_note (vlm.py:194-262) builds prompt, runs VLM inference, parses JSON via _parse_vlm_json, creates VlmNote with visual_summary, key_elements, teaching_points fields, writes to vlm_note_{NNN}.json. VlmNote schema validated by Pydantic. Tests confirm JSON write with all required fields. |
| 4 | VLM이 파싱 텍스트와 30% 미만 토큰 겹침을 보이는 슬라이드에 needs_review 플래그가 표시된다 | VERIFIED | compute_token_overlap (vlm.py:156) calculates overlap ratio. generate_single_note (vlm.py:241-252) sets needs_review = (parsed_token_count > 10 and overlap < 0.30). Skips flag for image-heavy slides (<=10 tokens). 7 token overlap test cases pass including Korean text. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `lecture_auto/tasks/celery_app.py` | Celery app with GPU-safe config | VERIFIED | worker_concurrency=1, task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1 |
| `lecture_auto/tasks/vlm_tasks.py` | Resumable VLM Celery task | VERIFIED | process_slides_task with file-based checkpointing, lazy VLM loading, publish_progress per slide |
| `lecture_auto/tasks/progress.py` | Redis pub/sub progress publisher | VERIFIED | publish_progress + get_last_progress + reset_redis_client. Channel format: job:{id}:progress. Last-progress persisted with 24h TTL. |
| `lecture_auto/schemas/job_status.py` | JobStatus enum + ProgressEvent schema | VERIFIED | JobStatus(queued,started,vlm_processing,completed,failed) + ProgressEvent(job_id,stage,current,total,percent,status) |
| `lecture_auto/pipeline/vlm.py` | Extended VlmNote + generate_single_note + compute_token_overlap | VERIFIED | needs_review, token_overlap_ratio fields; generate_single_note atomic function; _extract_slide_text helper; generate_visual_notes preserved for backward compat |
| `lecture_auto/api/main.py` | FastAPI app with CORS and router mounting | VERIFIED | FastAPI app with lifespan, CORS, health endpoint, include_router(jobs.router) |
| `lecture_auto/api/routes/jobs.py` | Job submit, status, SSE progress endpoints | VERIFIED | POST /{job_id}/vlm, GET /{job_id}/status, GET /{job_id}/progress with SSE, late-joiner initial event, ping=15s |
| `lecture_auto/api/deps.py` | Async Redis dependency provider | VERIFIED | get_async_redis singleton, close_async_redis for lifespan cleanup |
| `tests/test_token_overlap.py` | Token overlap + VlmNote + JobStatus tests | VERIFIED | 19 tests covering overlap edge cases, Korean text, VlmNote fields, generate_single_note, JobStatus, ProgressEvent |
| `tests/test_vlm_tasks.py` | Resumability + progress tests | VERIFIED | 4 tests: all slides processed, skip completed, reprocess invalid, correct progress args |
| `tests/test_progress.py` | Redis pub/sub mock tests | VERIFIED | 6 tests: publish channel, persist last progress, percent=0 edge case, get returns parsed JSON/None, reset client |
| `tests/test_jobs_api.py` | API integration tests | VERIFIED | 10 tests: submit success/404, all status states, SSE content-type, initial event, health endpoint |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| vlm_tasks.py | vlm.py | `from lecture_auto.pipeline.vlm import generate_single_note, load_vlm` | WIRED | Lazy import inside function bodies (lines 25, 53) |
| vlm_tasks.py | progress.py | `publish_progress(job_id, ...)` per slide | WIRED | 4 call sites: skipped, processing, done, error (lines 77, 82, 87, 90) |
| vlm_tasks.py | jobs.py (storage) | `from lecture_auto.storage.jobs import JobPaths` | WIRED | Line 55, used for manifest_path and vlm_dir |
| jobs.py (routes) | vlm_tasks.py | `process_slides_task.apply_async` | WIRED | Line 37, submits to gpu_queue |
| jobs.py (routes) | progress.py | `get_last_progress` | WIRED | Lines 52, 81 -- status derivation + SSE initial state |
| jobs.py (routes) | redis.asyncio | `AsyncRedis` via Depends(get_async_redis) | WIRED | Line 12 import, line 69 dependency injection |
| main.py | jobs.py (routes) | `app.include_router(jobs.router)` | WIRED | Line 39 |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| VLM-01 | 02-01 | 슬라이드 이미지를 Qwen3-VL에 입력해 visual summary, key elements 등 생성 | SATISFIED | generate_single_note builds multimodal prompt with slide image, runs VLM inference, outputs VlmNote with all required fields |
| VLM-02 | 02-01 | VLM 입력 시 파싱된 텍스트를 함께 제공해 환각 방지 | SATISFIED | build_vlm_prompt includes parsed slide text (text-grounded prompting, inherited from Phase 01.1). compute_token_overlap detects hallucination via needs_review flag. |
| VLM-03 | 02-01 | VLM 출력을 JSON 스키마로 검증 | SATISFIED | _parse_vlm_json validates structure; VlmNote(**data) enforces Pydantic v2 schema validation; retry on parse failure |
| INFRA-02 | 02-02 | 비동기 작업 패턴(제출 -> 상태 폴링 -> 결과 반환) | SATISFIED | POST /jobs/{job_id}/vlm submits async Celery task; GET /status polls; GET /progress streams SSE. Full submit -> poll -> stream -> result cycle implemented. |

**Orphaned requirements:** None. REQUIREMENTS.md maps VLM-01, VLM-02, VLM-03, INFRA-02 to Phase 2 -- all accounted for in plans 02-01 and 02-02.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | - | - | No TODO/FIXME/PLACEHOLDER/stub patterns found in any phase 02 artifact |

Zero anti-patterns detected across all tasks, api, and schema files.

### Human Verification Required

### 1. SSE Real-Time Streaming

**Test:** Start FastAPI + Redis + Celery worker, submit a VLM job via POST /jobs/{job_id}/vlm, then open GET /jobs/{job_id}/progress in browser/curl
**Expected:** SSE events arrive in real-time showing per-slide progress with percent values incrementing, ending with a "complete" event
**Why human:** Requires running infrastructure (Redis, Celery, GPU) to verify end-to-end SSE streaming behavior

### 2. Late-Joiner SSE Initial State

**Test:** Start a job, wait for partial completion, then connect a new SSE client to /progress
**Expected:** New client receives "initial" event with last known progress before receiving live events
**Why human:** Requires timing coordination between job execution and client connection

### 3. Worker Crash Resumability

**Test:** Start a multi-slide job, kill the Celery worker mid-processing, restart worker
**Expected:** Task resumes from next unprocessed slide; already-completed slides have valid vlm_note_NNN.json files and are skipped
**Why human:** Requires actual process kill/restart to verify crash recovery behavior

### 4. GPU Memory Safety

**Test:** Verify Celery worker runs with concurrency=1 and processes one slide at a time
**Expected:** No GPU OOM errors during processing; single worker process owns the GPU
**Why human:** Requires actual GPU hardware to verify memory behavior

### Gaps Summary

No gaps found. All 4 observable truths verified. All 12 artifacts exist, are substantive, and are properly wired. All 7 key links confirmed. All 4 requirement IDs (VLM-01, VLM-02, VLM-03, INFRA-02) satisfied with implementation evidence. Zero anti-patterns detected. 39/39 tests pass.

The phase goal "재시작 가능한 비동기 작업이 슬라이드별 VLM 시각 노트 JSON을 생성한다" is achieved: a resumable Celery task wraps VLM inference with file-based checkpointing, produces validated VlmNote JSON per slide, publishes real-time progress via Redis pub/sub, and is exposed through FastAPI REST + SSE endpoints.

---

_Verified: 2026-03-24T01:30:00Z_
_Verifier: Claude (gsd-verifier)_
