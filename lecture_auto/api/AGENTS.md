<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# api — FastAPI application

## Purpose
The HTTP layer. Submits jobs to Celery, serves status + artifacts, streams progress over
SSE, and hosts the demo. The API process is **thin**: it enqueues work and reads
results/checkpoints — it never runs GPU inference itself (that would exhaust the API
server; see `CLAUDE.md`).

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Package docstring marker for the FastAPI app. |
| `main.py` | App entry point: `lifespan` (closes async Redis on shutdown), `/health`, no-cache middleware for demo static assets, router mounting, and demo SPA hosting. |
| `deps.py` | Shared dependency providers: `get_async_redis()` (async client for SSE pub/sub) and `close_async_redis()` (shutdown). |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `routes/` | Endpoint modules: jobs, scripts, tts, download, demo (see `routes/AGENTS.md`). |

## For AI Agents

### Working In This Directory
- Keep handlers **non-blocking**: dispatch to Celery and return a task id; don't run the
  pipeline inline (Vercel/proxy timeouts + GPU exhaustion).
- SSE endpoints use the **async** Redis client from `deps.py` and replay the last
  persisted progress event so late joiners aren't stuck at 0%.
- Validate request/response bodies with the Pydantic models in `schemas/`.

### Testing Requirements
- `tests/test_jobs_api.py`, `tests/test_scripts_api.py` use FastAPI `TestClient` with a
  mocked `JobPaths`. Assert status codes and SSE `text/event-stream` content type.

### Common Patterns
- One router module per resource; mounted in `main.py`.
- File reads tolerate missing/partial artifacts (return `None`/404, never 500 on a missing slide).

## Dependencies

### Internal
- `tasks/` (enqueue), `schemas/` (I/O models), `storage/jobs.py` (paths), `demo/` (demo routes).

### External
- FastAPI, uvicorn, sse-starlette, redis (async), zipstream-ng (download), python-multipart (uploads).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
