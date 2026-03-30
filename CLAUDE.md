<!-- GSD:project-start source:PROJECT.md -->
## Project

**Lecture Auto — 강의 자동화 파이프라인**

교수님의 PPT 강의자료를 입력하면, 슬라이드별 강의 스크립트와 음성을 자동 생성하는 내부용 파이프라인 시스템. 연구실 내부 포털에 통합되어 교수님이 직접 사용하며, 생성된 스크립트를 검수/편집한 뒤 TTS 음성까지 한 번에 받을 수 있다.

**Core Value:** PPT 한 장을 넣으면 교수님 스타일의 강의 스크립트와 음성이 나온다 — 이 흐름이 끊기지 않아야 한다.

### Constraints

- **GPU 서버**: Qwen3-VL + Qwen3-TTS 동시 구동 가능한 VRAM 필요
- **Vercel 타임아웃**: Next.js API Route는 10-60초 제한 → 비동기 패턴 필수
- **Claude Code**: `claude -p` 파이프 모드로 호출, Max Plan 범위 내 사용
- **인증**: Supabase Auth professor role만 접근 가능
- **재현성**: 같은 입력 + 같은 설정이면 동일 파이프라인 재실행 가능해야 함
- **검수성**: 교수님이 텍스트만 보고 수정 가능한 산출물 형식
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
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
### VLM Layer (Local GPU)
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
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
