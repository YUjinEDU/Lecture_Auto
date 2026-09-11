<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# Lecture Auto — 강의 자동화 파이프라인

## Purpose
Internal pipeline that turns a professor's lecture slides (PPTX/PDF) into per-slide
lecture **scripts** and **TTS audio** (and an assembled MP4). One shared pipeline core
(`parse → render → VLM → script → TTS → video`) is driven by **three independent
orchestration layers**:

| Driver | Entry point | Use case |
|--------|-------------|----------|
| **Interactive CLI** | `run.py` | Local, human-in-the-loop 6-stage run with `[y/n]` gates |
| **Async API + workers** | `lecture_auto/api/` + `lecture_auto/tasks/` | Production: FastAPI + Celery/Redis, SSE progress, resumable checkpoints |
| **Demo workflow** | `lecture_auto/demo/` + `lecture_auto/demo_static/` | Self-contained presentation demo with CPU fallbacks (no GPU/Redis required) |

The **core value**: a professor drops in slides, reviews/edits the generated script as
plain text, and gets cloned-voice audio — this flow must never break.

## Key Files
| File | Description |
|------|-------------|
| `CLAUDE.md` | Project constitution: tech stack, version pins, rationale, "what NOT to use", GSD workflow rules. Read first. |
| `run.py` | Interactive CLI orchestrator — runs the 6-stage pipeline with confirmation prompts, SHA-256 input hashing, and a summary JSON. |
| `pyproject.toml` | Package metadata, runtime deps, pytest config (`testpaths=["tests"]`, `Test*`/`test_*` discovery). |
| `requirements.txt` | Pinned runtime dependencies (mirror of `pyproject` deps). |
| `uv.lock` | `uv` resolver lockfile. |
| `.env.example` | Template for required env vars (Redis URL, Supabase, model paths). |
| `api.txt` | ⚠️ **LEAKED SECRET** — contains an OpenAI API key. Must be removed from git and the key rotated. Do not read/echo its contents. |
| `=2.0.0` | Junk file (stray `pip install` error output). Safe to delete. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `lecture_auto/` | Python backend package — pipeline core + all three drivers (see `lecture_auto/AGENTS.md`). |
| `portal/` | Next.js pages/components to drop into the lab's **existing** portal (see `portal/AGENTS.md`). |
| `tests/` | Pytest suite mirroring the backend modules (see `tests/AGENTS.md`). |
| `data/` | **Runtime output, not source** — `data/work/<id>/` and `data/demo_jobs/<id>/` hold per-job `input/parsed/vlm/scripts/audio` artifacts. Never hand-edit; regenerate via the pipeline. |
| `docs/` | Superpowers planning artifacts (UX redesign plans/specs). |
| `lecture_automation_docs/` | Korean project docs (기획서, 요구사항 명세서). |
| `PPTX/` | Sample input decks for manual testing. |

## For AI Agents

### Working In This Directory
- **GSD workflow is enforced** (per `CLAUDE.md`): start file-changing work through a GSD
  command (`/gsd:quick`, `/gsd:debug`, `/gsd:execute-phase`) unless the user explicitly
  asks to bypass it. Direct edits to `AGENTS.md`/`CLAUDE.md`/`.claude/**`/`.omc/**` are exempt.
- **Reproducibility is a hard constraint**: same input + same settings must re-run to the
  same result. The pipeline keys on SHA-256 of the input file.
- **Reviewability is a hard constraint**: script artifacts are plain-text/JSON the
  professor can edit by hand — keep output formats human-legible.
- Treat `data/` as ephemeral. The three drivers share the `pipeline/` core but persist
  state differently (CLI = files only; API = Redis + files; demo = JSON snapshots).

### Testing Requirements
- Run `pytest` from repo root (config in `pyproject.toml`). Lint with `ruff check`.
- Tests mock all heavy externals (vLLM, Qwen-TTS, `claude -p`, `soffice`, `ffmpeg`) — no
  GPU or network needed for the suite.

### Common Patterns
- Pydantic v2 schemas at module boundaries (`lecture_auto/schemas/`).
- Atomic JSON writes (`.tmp` + `os.rename`) for any checkpoint/artifact.
- Immutable updates (`model_copy(update=...)`) over in-place mutation.

## Dependencies

### External
- **VLM/TTS (GPU):** vLLM + Qwen3-VL-8B-Instruct, qwen-tts + Qwen3-TTS.
- **Rendering:** LibreOffice (`soffice` headless) → PDF, `pdf2image`/poppler → PNG, `ffmpeg` → MP4.
- **Parsing:** PyMuPDF + pdfplumber (PDF), python-pptx (PPTX metadata).
- **Backend:** FastAPI, Celery[redis], Redis, sse-starlette, Pydantic v2, Supabase.
- **Script gen:** Claude via `claude -p` subprocess (primary); `openai` SDK is also a dep.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
