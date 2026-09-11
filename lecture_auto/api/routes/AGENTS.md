<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# routes — API endpoint modules

## Purpose
One router module per resource. Together they cover the full review flow: submit a parsed
deck → generate scripts → edit/regenerate/approve → generate + preview TTS → download the
package. The `demo` router is a parallel, self-contained surface for the local demo.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Route package marker. |
| `jobs.py` | `POST` submit VLM job (404 if no manifest), `GET` job status (derived from last progress event), `GET` SSE progress stream. |
| `scripts.py` | Script CRUD + lifecycle: list, `PUT` update (sets `edited`+timestamp), `POST` regenerate (per slide via Claude), `POST` approve (→ TTS), SSE script progress, and slide PNG serving. Uses atomic JSON writes. |
| `tts.py` | Voice registration + status, per-slide WAV serving (preview), single-slide re-TTS after edits, SSE TTS progress. |
| `download.py` | Lists deliverables grouped by category and streams them as a ZIP (`zipstream-ng`). |
| `demo.py` | The demo surface: create/list/get/delete/patch demo jobs, upload/get voice reference, edit slide scripts, rerun/stop a demo job, and serve the demo page. |

## For AI Agents

### Working In This Directory
- Read job artifacts through `storage.jobs.JobPaths`, not hardcoded paths — this is what
  the tests mock.
- Tolerate missing files: a not-yet-generated script/PNG/WAV returns `None`/404, never a 500.
- Write any mutation (script edit, status flip) **atomically** (`.tmp` + `os.rename`) so a
  concurrent reader never sees a half-written file.
- `approve` is the handoff: it flips slide TTS status to `queued` and enqueues the TTS task.

### Testing Requirements
- `tests/test_jobs_api.py`, `tests/test_scripts_api.py`, `tests/demo/test_approve_endpoint.py`.

### Common Patterns
- `_require_job` / `_read_script` / `_read_all_scripts` helpers normalize lookups + sorting
  by `slide_number`.
- SSE handlers emit an initial persisted event, then live events from Redis pub/sub.

## Dependencies

### Internal
- `tasks/` (enqueue + regenerate), `schemas/` (script.py, tts.py, job_status.py),
  `storage/` (jobs paths, voice_store), `demo/` (orchestration, state, jobs).

### External
- FastAPI routing, sse-starlette, zipstream-ng, python-multipart.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
