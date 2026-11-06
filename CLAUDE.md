# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Lecture Auto — 강의 자동화 파이프라인**

교수님의 PPT 강의자료를 입력하면, 슬라이드별 강의 스크립트와 음성을 자동 생성하는 내부용 파이프라인 시스템. 연구실 내부 포털에 통합되어 교수님이 직접 사용하며, 생성된 스크립트를 검수/편집한 뒤 TTS 음성까지 한 번에 받을 수 있다.

**Core Value:** PPT 한 장을 넣으면 교수님 스타일의 강의 스크립트와 음성이 나온다 — 이 흐름이 끊기지 않아야 한다.

### Constraints

- **GPU 서버**: VLM + TTS 동시 구동 가능한 VRAM 필요
- **Vercel 타임아웃**: Next.js API Route는 10-60초 제한 → 비동기 패턴 필수
- **인증**: Supabase Auth professor role만 접근 가능
- **재현성**: 같은 입력 + 같은 설정이면 동일 파이프라인 재실행 가능해야 함
- **검수성**: 교수님이 텍스트만 보고 수정 가능한 산출물 형식

### Implementation status vs. this doc's stack tables

The "Recommended Stack" tables below are the original planning doc and don't all match what's
implemented today:

- **The local-GPU VLM stack (vLLM + Qwen3-VL-8B + transformers + qwen-vl-utils + accelerate)
  was discarded, not swapped for a pinned alternative.** `lecture_auto/pipeline/vlm.py` now
  calls the same unified OpenAI client used for script generation (`LLMClient.analyze_image`)
  — there is no local vision model in the loop at all. The "VLM Layer (Local GPU)" table below
  is dead; don't reintroduce those deps or plan GPU capacity around them without asking first.
- Script generation also runs through **OpenAI** (`lecture_auto/llm/openai_client.py`, models
  `gpt-5.6-luna` / `gpt-5.4-mini`, overridable via `LLM_SCRIPT_MODEL` / `LLM_VLM_MODEL`), not
  `claude -p`.
- TTS runs through `pipeline/raon_tts.py` (Raon-Speech) — see `lecture_auto/tts/` and
  `pipeline/AGENTS.md`.
- **The FastAPI+Celery job API, the demo driver, the review page and `portal/` were deleted
  (2026-10-25).** The web UI is now `lecture_auto/web/`, a thin layer over the batch/produce
  engine (`docs/WEB_UI.md`). Celery/Redis/Supabase/Next.js rows below are history only.
- PPTX parsing has already been supplemented with a PDF parser (`pipeline/parser_pdf.py` +
  PyMuPDF/pdfplumber), matching the "Phase 3" note in the python-pptx row below.

Treat the tables as historical rationale for *why* a technology was chosen, not as a live
description of what's wired up — check `lecture_auto/*/AGENTS.md` and the code for current state.

## Workflow

- Edit files directly; no wrapper workflow command is required before changing code.
- Do multi-commit work on a feature branch in its own git worktree (e.g. `feat/product` in
  `../Lecture_Auto_wt_product`) so `master` and the running web UI stay untouched.
- Before a commit: `.venv/bin/python -m pytest -q` passes and changed files are `ruff`-clean.

## Commands

```bash
# Install (uv-managed; lockfile is uv.lock)
uv sync --extra dev

# Run the whole test suite (config in pyproject.toml, testpaths=["tests"]).
# Use the venv python: a bare `pytest` may resolve to a system/anaconda one that
# lacks the deps (24 collection errors). From a git worktree, `python -m` makes
# the worktree's lecture_auto win over the editable install of the main checkout.
.venv/bin/python -m pytest -q
# Run one file / one test
.venv/bin/python -m pytest tests/test_script_gen.py
.venv/bin/python -m pytest tests/test_script_gen.py::test_build_prompt_includes_style -v

# Interactive CLI pipeline (local, human-in-the-loop, 6 stages)
python run.py --pptx path/to/lecture.pptx

# Professor web UI (docs/WEB_UI.md) -- jobs run one at a time on GPU 0
LECTURE_WEB_PASSWORD=... .venv/bin/python -m lecture_auto.web --host 0.0.0.0 --port 8800

# Production CLI (what the web UI's buttons run)
.venv/bin/python -m scripts.batch_generate_lectures --status

# Real-model smoke tests (hit OpenAI / GPU — not run in CI)
python scripts/smoke_e2e.py --stage script   # OPENAI_API_KEY only, no GPU
python scripts/produce.py --only <lec> --slides 1,2,3   # few-slide real TTS + video via the batch
```

No linter config is committed; `uvx ruff check <paths>` works with ruff defaults (pre-existing
findings remain in older modules -- keep new/changed files clean).

## Architecture

One shared pipeline core; production is driven by the batch CLI, and the web UI drives the CLI:

```
parse → render → VLM → script → TTS → video      (lecture_auto/pipeline/*.py)
         ↑
   lecture_auto/production/batch.py (CLI: scripts/batch_generate_lectures.py) + scripts/produce.py
         ↑ job spec -> python -m lecture_auto.core.worker (serial queue, GPU 0)
   lecture_auto/core/   (project.json per lecture in data/projects, job specs, worker, migrate)
   lecture_auto/web/  (FastAPI + static HTML/JS, professor login)     run.py (old interactive CLI)
```

- `lecture_auto/pipeline/` — pure, driver-agnostic stage functions (one slide = one atomic
  unit, e.g. `generate_single_note`, `synthesize_slide`). No orchestration or persistence
  logic belongs here; that lives in the three drivers above it.
- `lecture_auto/schemas/` — Pydantic v2 models that are the contract between every layer
.
- `lecture_auto/storage/` — per-job filesystem path helpers; job artifacts live under
  `data/work/<id>/{input,parsed,vlm,scripts,audio}` and are regenerated, never hand-edited.
- `lecture_auto/web/` — the professor's web UI. It never re-implements pipeline steps: jobs are
  worker subprocesses fed a typed job spec; approvals run in-process through the same batch
  functions the CLI uses, and the only other direct write is a
  script edit saved as a hand edit. Public access goes through the lab homepage as a reverse
  proxy; the GPU box is never exposed directly.

**Documentation map:** almost every directory here has its own `AGENTS.md` (Purpose / Key
Files / Subdirectories / For AI Agents / Dependencies), generated and kept current as the
code changes. Start at root `AGENTS.md`, then follow into the relevant subdirectory's
`AGENTS.md` before making changes — it is more current and more detailed than this file for
anything below the top-level tech/constraint decisions.

## Technology Stack

## Recommended Stack
### PPT Parsing Layer
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| python-pptx | 1.0.2 | Parse PPTX structure: slide text, layout, shape metadata (speaker notes 제외 — D-05) | Only mature, maintained Python library for PPTX read/write. v1.0 stable API. PDF 파서로 전환 예정 — Phase 3에서 교체. |
### Slide Rendering Layer
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| LibreOffice (soffice headless) | system (7.6+) | PPTX → PDF conversion, preserving layout fidelity | Best free PPTX renderer on Linux. Use `--headless --convert-to pdf` via subprocess. |
| pdf2image | 1.17+ | PDF → PNG per-slide, wraps poppler `pdftoppm` | Battle-tested, PIL-compatible output, simple API. |
| Pillow | 11.x | Image resize / normalisation before VLM | Required PIL backend for pdf2image; also handles VLM pre-processing. |
| poppler-utils | system | Binary dependency for pdf2image | Best PDF rasteriser on Linux. Install: `apt install poppler-utils`. |
### VLM Layer (Local GPU) — ❌ DEPRECATED, discarded in favor of OpenAI vision (see Implementation status above)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| transformers | >=4.57.0 | Load and run Qwen3-VL | Hard requirement from Qwen3-VL model card. Earlier versions do not recognise `qwen3_vl` architecture. |
| qwen-vl-utils | 0.0.14 | Qwen3-VL image/video pre-processing helpers | Official Qwen utility; handles image token packing, resolution scaling. |
| vLLM | >=0.11.0 | High-throughput batched VLM inference | 2–5x throughput vs naive HuggingFace `.generate()`. Supports Qwen3-VL natively from v0.11+. Recommended model variant: `Qwen3-VL-8B-Instruct` (fits single 24 GB GPU). |
| accelerate | latest | Device map / multi-GPU for HuggingFace fallback | Required when not using vLLM; handles device placement automatically. |
- 8B Instruct: single 24 GB GPU (RTX 3090/4090), best quality/cost for lecture slides.
- 30B-A3B MoE: multi-GPU or 2×24 GB; only needed if slide content is dense technical diagrams.
- 4B Instruct: fits 16 GB GPU, acceptable quality.
### LLM Script Generation Layer
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Claude via `claude -p` (CLI) | current Max Plan | Convert VLM slide summaries → full lecture script paragraphs | Specified constraint: Max Plan = no per-token API cost. Use subprocess or `asyncio.create_subprocess_exec` to call `claude -p`. |
| prompt-toolkit / templating | stdlib `string.Template` | Prompt construction for script style, length, tone | No external dep needed; keep prompts in `.txt` templates, render at runtime. |
### TTS Layer (Local GPU)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Qwen3-TTS | `Qwen3-TTS-12Hz-1.7B-CustomVoice` | Text → speech with voice clone | Official Qwen TTS; supports 3-second voice cloning, 10 languages, streaming generation. 1.7B model (4.5 GB) fits on same GPU as 8B VLM if sequential; else dedicate second GPU. |
| vLLM-Omni | latest | Serve Qwen3-TTS for offline batch inference | Recommended by QwenLM for production deployment; reduces per-utterance latency vs pure HuggingFace. |
| soundfile / scipy | latest | Write WAV/OGG output, sample-rate conversion | Lightweight, no additional system deps. |
### Pipeline Backend
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.11 | Runtime | 3.11 is the stable, performance-optimised LTS. 3.12/3.13 are viable but less tested with GPU stack. |
| FastAPI | 0.135.1 | REST API, job submission, status endpoints | Current stable (released 2026-03-01). Native async, auto-docs, minimal overhead. |
| Celery | 5.4.x | Async job queue: PPT parse → render → VLM → LLM → TTS | Production-mature, handles long-running GPU tasks, retry/backoff, task chaining with `chain()` and `chord()`. |
| Redis | 7.x | Celery broker + result backend + job status cache | Fastest broker for single-server setup. Also used for SSE/WebSocket progress events. |
| uvicorn | 0.x (latest) | ASGI server for FastAPI | Standard ASGI server; use with `--workers 1` on GPU server (GPU is not shared). |
| python-dotenv | 1.x | Environment variable loading | `.env` file management for secrets (Supabase URL/key, paths). |
| pydantic | 2.x | Request/response schemas, config validation | Bundled with FastAPI 0.100+; v2 is 5–20x faster validation than v1. |
### Database / Auth
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| supabase (Python client) | 2.28.3 | PostgreSQL operations: job records, user auth, output metadata | Current stable (2026-03-20). Async-compatible. Wraps `postgrest-py` and `gotrue`. |
| PostgreSQL (via Supabase) | 15+ | Persistent storage for jobs, slide metadata, transcripts | Managed by Supabase; no self-hosting overhead. |
### File Storage
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Local disk (GPU server) | — | Slide PNGs, generated audio WAV/OGG, intermediate PDFs | GPU-local IO is fastest for pipeline hot path. No S3 latency during processing. |
| pathlib (stdlib) | — | Path management | No dep needed. Prefer `pathlib.Path` over `os.path` throughout. |
### Frontend Integration
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Next.js | 15.x (existing) | Lab homepage portal; job submission UI, progress display | Existing asset; do not replace. |
| REST + SSE | — | Job status streaming to frontend | Server-Sent Events via FastAPI `StreamingResponse` is simpler than WebSocket for one-way progress updates. |
### Deployment
| Component | Target | Why |
|-----------|--------|-----|
| FastAPI + Celery workers | GPU server (bare metal / Docker) | GPU access requires direct host or NVIDIA Container Toolkit. |
| Redis | Same GPU server (Docker container) | Low-latency IPC with Celery workers. |
| Next.js portal | Vercel | Existing deployment; no change. |
| Environment config | `.env` file on GPU server | Supabase URL/anon key, model paths, job output root. |
## Rationale
### Why Celery over taskiq / ARQ / RQ
### Why vLLM for VLM inference
### Why LibreOffice over alternatives
- `python-pptx` can extract shapes but cannot render slides with correct fonts/themes to PNG.
- Headless Chrome (Puppeteer) requires a browser binary and PPT→HTML conversion loses fidelity.
- LibreOffice is the only FOSS tool that handles complex PPTX layouts reliably on Linux.
### Why local disk over Supabase Storage
### Why SSE over WebSocket for progress
## What NOT to Use
| Rejected Option | Category | Why Rejected |
|-----------------|----------|--------------|
| Celery `--concurrency > 1` for GPU workers | Config | Multiple workers will OOM-kill or deadlock the GPU. Use `concurrency=1` per GPU. |
| Supabase Storage for pipeline intermediates | File I/O | Network latency degrades pipeline throughput. Use only for final artefact URLs. |
| `python-pptx` for slide rendering | Rendering | It has no rendering engine. Text extraction only. Always pair with LibreOffice for images. |
| HuggingFace `.generate()` for batch VLM | Inference | Sequential processing; no batching. Use vLLM for anything beyond single-slide demos. |
| Qwen3-VL-30B on single 24 GB GPU | Model sizing | Will OOM. Use 8B-Instruct on single GPU; 30B requires 2× 24 GB minimum. |
| FastAPI BackgroundTasks for GPU jobs | Task queue | BackgroundTasks run in the same process; GPU memory exhaustion will kill the API server. Use Celery workers as separate processes. |
| ARQ or RQ as task queue | Task queue | No native task-chain primitives; too lightweight for 5-step sequential GPU pipeline. |
| WebSocket for job status | Protocol | Overkill for one-way progress events; SSE is simpler and works through standard HTTP proxies. |
| Next.js API Routes calling GPU directly | Architecture | Vercel functions have 10s/60s timeout limits; GPU pipeline takes minutes. Always go through async job API. |
| pptxtoimages package | Rendering | Thin wrapper with no added value; exposes subprocess directly. Implement LibreOffice + pdf2image directly for control over resolution, DPI, error handling. |
## Confidence Levels
| Component | Confidence | Source | Notes |
|-----------|------------|--------|-------|
| python-pptx 1.0.2 | HIGH | PyPI official | Verified current version |
| FastAPI 0.135.1 | HIGH | PyPI + GitHub releases | Verified 2026-03-01 release |
| Celery 5.4.x + Redis | HIGH | PyPI + multiple production references | Long-established production stack |
| transformers >=4.57.0 | HIGH | Qwen3-VL official model card + HuggingFace docs | Hard requirement, documented |
| vLLM >=0.11.0 for Qwen3-VL | HIGH | vLLM recipes docs + QwenLM GitHub | Documented minimum version |
| qwen-vl-utils 0.0.14 | HIGH | QwenLM GitHub install instructions | Pinned version in official quickstart |
| Qwen3-TTS-12Hz-1.7B-CustomVoice | HIGH | HuggingFace model card + QwenLM GitHub | Released Jan 2026; voice clone confirmed |
| supabase 2.28.3 | HIGH | PyPI (verified 2026-03-20 release) | Current stable |
| pdf2image + poppler | HIGH | PyPI + project GitHub | Actively maintained, standard PPTX-to-image path |
| LibreOffice headless rendering | MEDIUM | Community documentation + forum posts | Fidelity on complex PPTX varies; test with representative slides |
| vLLM-Omni for Qwen3-TTS | MEDIUM | QwenLM GitHub mention | Less documentation than vLLM core; offline inference confirmed supported |
| Claude CLI `claude -p` subprocess | MEDIUM | Project constraint (Max Plan) | Functional but not a documented API; subprocess stdout streaming assumed stable |
## Sources
- [python-pptx PyPI](https://pypi.org/project/python-pptx/)
- [FastAPI PyPI](https://pypi.org/project/fastapi/)
- [FastAPI GitHub Releases](https://github.com/fastapi/fastapi/releases)
- [Qwen3-VL HuggingFace](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)
- [Qwen3-VL GitHub](https://github.com/QwenLM/Qwen3-VL)
- [vLLM Qwen3-VL Recipes](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3-VL.html)
- [Qwen3-TTS HuggingFace Collection](https://huggingface.co/collections/Qwen/qwen3-tts)
- [Qwen3-TTS GitHub](https://github.com/QwenLM/Qwen3-TTS)
- [supabase-py PyPI](https://pypi.org/project/supabase/)
- [pdf2image PyPI](https://pypi.org/project/pdf2image/)
- [Celery + Redis + FastAPI production guide 2025](https://medium.com/@dewasheesh.rana/celery-redis-fastapi-the-ultimate-2025-production-guide-broker-vs-backend-explained-5b84ef508fa7)
- [Python task queue comparison 2025](https://devproportal.com/languages/python/python-background-tasks-celery-rq-dramatiq-comparison-2025/)

## Conventions

- Pydantic v2 schemas (`lecture_auto/schemas/`) are the I/O contract at every module
  boundary; change them deliberately and update all producers/consumers together.
- Atomic JSON writes for any checkpoint/artifact: write to `.tmp` then `os.rename`.
- Immutable updates via `model_copy(update=...)`, not in-place mutation, on schema objects.
- Lazy singleton model loading per worker (`_get_vlm`/`_get_tts`-style) so GPU weights load
  once, not per call.
- Tests mock every heavy external (OpenAI/VLM/TTS calls, `subprocess` for `soffice`/`ffmpeg`,
  Redis) — the suite needs no GPU, network, or Redis to run.

## Architecture

See the "Architecture" section above (shared pipeline core + three drivers) and the
per-directory `AGENTS.md` files, which are the maintained source of truth for module-level
detail.

## Known issues

- None open. (`api.txt` key was revoked and purged from history on 2026-09-23; stray root files removed.)

## Production batch workflow (scripts/batch_generate_lectures.py)

Hardening work is tracked in `docs/hardening/` (status board in its `README.md`). Key rules:
- Existing slide WAVs are never overwritten by resynthesis — new takes go to `slide_NNN.cand.wav`.
- Human-approved audio lives in `data/work_batch/<lec>/approved.json` (sha256-pinned) and is never
  resynthesized unless named in `--slides`; `--promote N` swaps a candidate in.
- `--approve`, `--approve-passing`, `--promote`, `--assemble-only` need `--only <lecture>` and load
  no TTS model / LLM. Unapproved + cache-invalid audio yields `<name>_DRAFT.mp4`; every assembly
  writes `<mp4 stem>.timeline.json`.
- STT fidelity check is ON by default in the batch (`--no-stt` to skip); each WAV gets a `.qc.json`.
  Pronunciation overrides live in `config/pronunciation.yaml` (only `approved: true` entries apply).
- Lectures live in `data/projects/<id>/project.json` (`lecture_auto/core/project.py`); run
  `python -m lecture_auto.core.migrate` once on a checkout that predates them. `--only` takes exact ids or 1-based indexes.
- S19 restyle (opt-in): a lecture whose project.json has `"restyle": true` runs `pipeline/restyle.py` once per section after script generation
  (cache `sections/section_NNN.restyled.json`, report `restyle_report.json`); the result is written as our own script (`.hash` matches, not hand-edited). No key = unchanged.
- S19 `--suggest-pron --only <id>`: one text-LLM call for Korean readings of unlisted Latin tokens -> `data/work_batch/<id>/pronunciation_suggestions.yaml`
  (`approved: false`, `source: llm`; never edits `config/pronunciation.yaml`, loads no TTS model). A human copies approved entries over.
- S17 one-command run: `python scripts/produce.py --only 7,8,9 --gpus 0,1 [--workers-per-gpu N] [--slides ..] [--no-stt] [--max-restarts 2] [--fix-failed] [--dry-run]`.
  Spawns `--claim <run_id>` workers (dynamic per-slide flock claim in `audio/.claim/`, longest script first; replaces static `--shard`, which still works but is mutually exclusive), restarts crashed workers, then assembles each lecture once and prints the status table (exit 1 if any lecture is not final).
- `--only` accepts comma lists (`7,8,9`, `08,09`); approval commands still need exactly one lecture. `--fix-failed` moves unapproved slides with an invalid cache to `audio/failed_<ts>/` (+`MOVED.txt`, never deletes) before resynthesis.
