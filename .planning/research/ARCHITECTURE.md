# Architecture Research

**Project:** PPT-to-Lecture-Script Automation Pipeline
**Researched:** 2026-03-23
**Overall Confidence:** HIGH (pattern is well-established; specifics verified against FastAPI docs and community sources)

---

## Component Overview

### Five distinct components with hard boundaries:

| Component | Runtime | Responsibility |
|-----------|---------|---------------|
| **Next.js Portal** | Vercel (Node) | UI, upload, job status display, download |
| **FastAPI Gateway** | GPU server | HTTP endpoints, job dispatch, status API |
| **Pipeline Worker** | GPU server (same process, thread pool) | Stage execution: parse → render → VLM → script → TTS |
| **Supabase** | Managed cloud | Job state, user auth, metadata persistence |
| **Local File Store** | GPU server disk | Binary artifacts per job (`/data/work/{job_id}/`) |

**Boundary rules:**
- Next.js never touches the GPU server file system directly — all file access goes through FastAPI signed-download endpoints.
- The pipeline worker never calls Supabase directly during stage execution; it updates state only via FastAPI internal calls (or direct Supabase REST if latency demands it — both patterns work).
- Claude `claude -p` and Qwen3-VL/TTS run as subprocess calls inside the worker; they are not separate services.

---

## Data Flow

```
[Browser]
  │ POST /api/jobs  (multipart PPTX)
  ▼
[Next.js API Route]  ←── Supabase Auth JWT validation
  │ POST /jobs  (forward to FastAPI)
  ▼
[FastAPI Gateway]
  │ 1. Write PPTX to /data/work/{job_id}/input.pptx
  │ 2. INSERT job row → Supabase (status: queued)
  │ 3. Enqueue background task
  │ Return 202 { job_id }
  ▼
[Pipeline Worker]  (FastAPI BackgroundTask or ThreadPoolExecutor)
  │
  ├─ Stage 1: Parse PPTX  → extract text/metadata → /data/work/{job_id}/slides.json
  ├─ Stage 2: Render PNG  → LibreOffice/python-pptx → /data/work/{job_id}/slide_NNN.png
  ├─ Stage 3: VLM Notes   → Qwen3-VL subprocess  → /data/work/{job_id}/notes.json
  ├─ Stage 4: Script Gen  → claude -p subprocess  → /data/work/{job_id}/script.md
  ├─ Stage 5: Review      → claude -p or heuristic → /data/work/{job_id}/script_reviewed.md
  └─ Stage 6: TTS         → Qwen3-TTS subprocess  → /data/work/{job_id}/audio_NNN.wav
  │
  │ After each stage: UPDATE job row → Supabase (status: stage_N_complete, progress: %)
  ▼
[Supabase]  ←── polled by Next.js every 3s via /api/jobs/{job_id}
  │
  ▼
[Next.js Portal]  renders progress bar, triggers download when status = complete

[Download]
  Browser → Next.js API Route → FastAPI /jobs/{job_id}/download → stream file from disk
```

**Key data flow constraints:**
- PPTX upload goes browser → Next.js → FastAPI (two hops) to keep auth centralized in Next.js.
- Status polling goes browser → Next.js → Supabase (skip FastAPI for read paths to reduce GPU server load).
- Audio/script download goes browser → Next.js → FastAPI → disk (FastAPI streams the file, never loads it entirely into memory).

---

## Async Job Pattern

**Chosen approach: FastAPI `BackgroundTasks` + in-process `ThreadPoolExecutor`**

Rationale: The pipeline is one job per professor session, not high-throughput multi-tenant. Celery + Redis adds operational overhead (two extra services) with no benefit at this scale. ARQ requires Redis too. FastAPI's built-in `BackgroundTasks` with a bounded thread pool is the correct choice.

```
POST /jobs
  └─ background_tasks.add_task(run_pipeline, job_id)
     └─ executor.submit(stage_runner, job_id, stage)
```

**Job state machine (stored in Supabase `jobs` table):**

```
queued → parsing → rendering → analyzing → scripting → reviewing → tts → complete
                                                                         → failed (any stage)
```

**Job status schema (Supabase `jobs` table):**

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid | job_id |
| `user_id` | uuid | FK to auth.users |
| `status` | text | state machine value above |
| `progress` | int | 0–100 |
| `stage_detail` | text | human-readable current operation |
| `error_message` | text | populated on failure |
| `file_path` | text | `/data/work/{id}/` base path |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

**Error handling:** Each stage catches exceptions, writes `error_message` to Supabase, sets `status = failed`, and returns. The worker does not retry automatically — professor re-submits.

**Cancellation:** DELETE /jobs/{job_id} sets a `cancelled` flag in Supabase; the worker checks this flag between stages and exits cleanly.

---

## Integration with Portal

**Next.js acts as a thin authenticated proxy** — it never exposes the GPU server directly to the browser.

```
Next.js API Routes:
  POST   /api/jobs              → forward multipart to FastAPI POST /jobs
  GET    /api/jobs/{id}         → read from Supabase directly (bypasses FastAPI)
  DELETE /api/jobs/{id}         → forward to FastAPI DELETE /jobs/{id}
  GET    /api/jobs/{id}/download → stream from FastAPI GET /jobs/{id}/download/{file}
```

**Auth flow:**
1. Professor logs in via Supabase Auth (existing portal pattern).
2. Next.js API routes validate the Supabase JWT server-side.
3. Next.js passes a shared server-to-server secret header to FastAPI (not the user JWT) — FastAPI trusts Next.js as its single caller.
4. FastAPI does not run its own auth — it relies on Next.js gating.

**Polling strategy:**
- Next.js frontend polls `GET /api/jobs/{id}` every 3 seconds while status is not terminal.
- On `complete` or `failed`, polling stops and UI updates.
- No WebSocket needed at this scale — polling is simpler and sufficient.

**CORS:** FastAPI sets `allow_origins` to the Next.js Vercel domain only. Direct browser-to-FastAPI calls are blocked.

---

## Build Order

Dependencies determine the order — each layer must exist before the layer above it can be tested end-to-end.

```
Phase 1: Foundation
  ├─ Supabase schema (jobs table, RLS policies)
  ├─ FastAPI skeleton (health check, CORS, auth middleware)
  └─ /data/work/ directory structure + file utilities

Phase 2: Upload + Job Lifecycle
  ├─ POST /jobs endpoint (accept PPTX, write to disk, insert Supabase row, return job_id)
  ├─ GET /jobs/{id} status endpoint
  └─ Next.js API routes (proxy + polling UI)

Phase 3: Pipeline Stages (implement in pipeline order)
  ├─ Stage 1: PPTX parser (python-pptx → slides.json)
  ├─ Stage 2: PNG renderer (LibreOffice headless or python-pptx image export)
  ├─ Stage 3: VLM notes (Qwen3-VL subprocess wrapper)
  ├─ Stage 4: Script generation (claude -p subprocess wrapper)
  ├─ Stage 5: Script review (claude -p second pass)
  └─ Stage 6: TTS (Qwen3-TTS subprocess wrapper)

Phase 4: Download + Polish
  ├─ GET /jobs/{id}/download/{file} streaming endpoint
  ├─ Next.js download UI
  └─ Error display, progress bar, cancellation
```

**Critical dependency:** Stages 3–6 depend on Stage 2 PNG output. Stage 4 depends on Stage 3 notes. Build strictly in order and test each stage in isolation with fixture inputs before wiring to the previous stage.

**Subprocess wrapper pattern (applies to Qwen3-VL, claude -p, Qwen3-TTS):**
```python
async def run_subprocess(cmd: list[str], job_id: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise PipelineStageError(job_id, stage=cmd[0], detail=stderr.decode())
    return stdout.decode()
```

---

## Sources

- [FastAPI BackgroundTasks — official docs](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Managing Background Tasks and Long-Running Operations in FastAPI — Leapcell](https://leapcell.io/blog/managing-background-tasks-and-long-running-operations-in-fastapi)
- [Serving Long-Running Jobs with FastAPI Using Webhooks and Task Polling — Medium](https://medium.com/@bhagyarana80/serving-long-running-jobs-with-fastapi-using-webhooks-and-task-polling-860bb0d3e0f9)
- [BackgroundTasks vs ARQ + Redis — davidmuraya.com](https://davidmuraya.com/blog/fastapi-background-tasks-arq-vs-built-in/)
- [Next.js FastAPI Integration Guide — Restackio](https://www.restack.io/p/fastapi-answer-nextjs-integration)
