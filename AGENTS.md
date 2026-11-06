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
| **Batch production CLI** | `scripts/batch_generate_lectures.py` + `scripts/produce.py` | Production: per-slide cached scripts/TTS/QC, approvals, video assembly |
| **Professor web UI** | `lecture_auto/web/` | FastAPI + static UI over the batch CLI: upload, review, approve, queued GPU jobs (`docs/WEB_UI.md`) |

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
| `.env.example` | Template for the env vars the code reads (`FACTCHAT_*` LLM gateway, `LECTURE_WEB_*`, rendering). |
| `api.txt`, `=2.0.0` | Removed. Neither was ever tracked by git (`.env` is git-ignored too). If a key was ever kept in a local `api.txt`, confirm it was rotated. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `lecture_auto/` | Python backend package — pipeline core + all three drivers (see `lecture_auto/AGENTS.md`). |
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
  state on disk (`data/work_batch/<id>/`, `output/<id>/`; the web UI adds `data/web/`).

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
- **TTS (GPU):** Raon-Speech-9B (`pipeline/raon_tts.py`, CC BY-NC 4.0). There is no local VLM: slide analysis goes through the OpenAI-compatible client. The old Qwen3-TTS path survives only in `pipeline/tts.py` / `run.py`.
- **Rendering:** LibreOffice (`soffice` headless) → PDF, `pdf2image`/poppler → PNG, `ffmpeg` → MP4.
- **Parsing:** PyMuPDF + pdfplumber (PDF), python-pptx (PPTX metadata).
- **Backend:** FastAPI (professor web UI, `lecture_auto/web/`), Pydantic v2. Celery/Redis/Supabase/sse-starlette were dropped on 2026-10-25.
- **Script gen:** OpenAI-compatible gateway (`FACTCHAT_*`; models `gpt-5.6-luna` / `gpt-5.4-mini`), not `claude -p`.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
