<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# tasks — Celery async driver

## Purpose
Wraps the `pipeline/` stages as **resumable Celery tasks** with file-based checkpointing
and Redis pub/sub progress. This is the production driver: long GPU jobs run in worker
processes (never in the API process), survive crashes, and stream progress to the portal
over SSE.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Marks the Celery task package (autodiscovered). |
| `celery_app.py` | The `celery_app` instance. **GPU-safe config**: `worker_concurrency=1`, `worker_prefetch_multiplier=1`, `task_acks_late`, `task_reject_on_worker_lost`. Routes `vlm.*`/`tts.*` → `gpu_queue`, `script.*` → `cpu_queue`. |
| `progress.py` | Redis progress publisher: `publish_progress()` (pub/sub + persist last event), `get_last_progress()` (for late SSE joiners), `reset_redis_client()` (tests). |
| `vlm_tasks.py` | `process_slides_task` — all slides through VLM, resumable; `_get_vlm()` lazy per-worker model singleton. |
| `script_tasks.py` | `generate_scripts_task` (per-slide checkpointing) + `regenerate_slide_task`; skips slides whose script JSON already exists and is non-empty. |
| `tts_tasks.py` | `synthesize_job_task` (per-slide checkpointing) + `regenerate_slide_tts_task`; `_get_tts()` lazy model singleton. |

## For AI Agents

### Working In This Directory
- **Never raise GPU concurrency.** `worker_concurrency=1` is deliberate — multiple workers
  on one GPU will OOM/deadlock (see `CLAUDE.md` "What NOT to Use"). Scale with more GPUs,
  not more concurrency.
- **Resumability is the core feature.** A task must check for a valid existing artifact and
  skip it; only (re)compute missing/invalid slides. Write checkpoints atomically
  (`.tmp` + `os.rename`) so a crash mid-write never leaves a corrupt JSON.
- Load models lazily and once per worker (`_get_vlm`/`_get_tts`) — never per task call.
- Publish progress after each slide via `progress.publish_progress()` so SSE clients and
  late joiners stay current.

### Testing Requirements
- `tests/test_vlm_tasks.py`, `tests/test_script_tasks.py`, `tests/test_progress.py`. Run
  tasks synchronously with mocked models + fake Redis; assert checkpoint/skip behavior.

### Common Patterns
- Task name prefixes (`vlm.`/`script.`/`tts.`) drive queue routing in `celery_app.py`.
- Progress events conform to `schemas/job_status.py::ProgressEvent`.

## Dependencies

### Internal
- `pipeline/` (the actual work), `schemas/job_status.py`, `storage/jobs.py` (paths).

### External
- Celery[redis], Redis. Broker/backend from `REDIS_URL` / `CELERY_RESULT_BACKEND`.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
