<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# lecture_auto — backend package

## Purpose
The Python backend. Contains the **stage modules** that do the real work (`pipeline/`)
and the **three orchestration layers** that drive them: synchronous stages exposed to the
CLI (`run.py`), async Celery tasks behind a FastAPI app (`api/` + `tasks/`), and a
self-contained local demo (`demo/` + `demo_static/`). Cross-cutting concerns live in
`schemas/` (Pydantic models) and `storage/` (disk-path conventions, voice files).

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Package marker (minimal). |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `pipeline/` | The shared stage core: parse → render → VLM → script → TTS → video (see `pipeline/AGENTS.md`). |
| `tasks/` | Celery tasks wrapping the stages with checkpointing + Redis progress (see `tasks/AGENTS.md`). |
| `api/` | FastAPI app: routes for jobs, scripts, TTS, download, demo (see `api/AGENTS.md`). |
| `demo/` | Self-contained demo orchestration with CPU fallbacks (see `demo/AGENTS.md`). |
| `demo_static/` | Vanilla-JS single-page UI for the demo, served by FastAPI (see `demo_static/AGENTS.md`). |
| `schemas/` | Pydantic v2 models shared across layers (manifest, script, tts, job status) (see `schemas/AGENTS.md`). |
| `storage/` | Per-job filesystem path helpers + voice-reference storage (see `storage/AGENTS.md`). |

## For AI Agents

### Working In This Directory
- **Don't put orchestration logic in `pipeline/`.** Stage modules must stay pure and
  driver-agnostic (callable from CLI, Celery, and demo alike). Sequencing, retries,
  progress, and persistence belong in `tasks/`, `demo/`, or `run.py`.
- A stage's atomic unit is **one slide** (e.g. `generate_single_note`,
  `synthesize_slide`, `regenerate_slide_task`) so work is resumable.
- Schemas in `schemas/` are the contract between layers — change them deliberately and
  update both producers (pipeline) and consumers (api/tasks/demo + portal types).

### Testing Requirements
- Every module here has a matching `tests/test_<module>.py`. Run `pytest`; heavy externals
  are mocked.

### Common Patterns
- Pydantic v2 for all I/O; `model_copy(update=...)` for immutable edits.
- Lazy model loading per worker (`_get_vlm`/`_get_tts` singletons) to avoid re-loading GPU weights.

## Dependencies

### Internal
- All layers depend on `pipeline/` and `schemas/`; `tasks/` and `api/` add Redis/Celery.

### External
- See root `AGENTS.md`. This package targets Python 3.11+.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
