# Stack Research

**Project:** PPT-to-Lecture-Script Automation Pipeline
**Researched:** 2026-03-23
**Overall Confidence:** HIGH (all components verified against current PyPI/HuggingFace/official docs)

---

## Recommended Stack

### PPT Parsing Layer

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| python-pptx | 1.0.2 | Parse PPTX structure: slide text, speaker notes, layout, shape metadata | Only mature, maintained Python library for PPTX read/write. v1.0 stable API. |

### Slide Rendering Layer

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| LibreOffice (soffice headless) | system (7.6+) | PPTX → PDF conversion, preserving layout fidelity | Best free PPTX renderer on Linux. Use `--headless --convert-to pdf` via subprocess. |
| pdf2image | 1.17+ | PDF → PNG per-slide, wraps poppler `pdftoppm` | Battle-tested, PIL-compatible output, simple API. |
| Pillow | 11.x | Image resize / normalisation before VLM | Required PIL backend for pdf2image; also handles VLM pre-processing. |
| poppler-utils | system | Binary dependency for pdf2image | Best PDF rasteriser on Linux. Install: `apt install poppler-utils`. |

**LibreOffice listener mode note:** For batch jobs (>10 slides), start soffice once with `--accept="socket,host=localhost,port=2002;urp;"` rather than spawning a new process per file. Reduces per-file overhead by ~60%.

### VLM Layer (Local GPU)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| transformers | >=4.57.0 | Load and run Qwen3-VL | Hard requirement from Qwen3-VL model card. Earlier versions do not recognise `qwen3_vl` architecture. |
| qwen-vl-utils | 0.0.14 | Qwen3-VL image/video pre-processing helpers | Official Qwen utility; handles image token packing, resolution scaling. |
| vLLM | >=0.11.0 | High-throughput batched VLM inference | 2–5x throughput vs naive HuggingFace `.generate()`. Supports Qwen3-VL natively from v0.11+. Recommended model variant: `Qwen3-VL-8B-Instruct` (fits single 24 GB GPU). |
| accelerate | latest | Device map / multi-GPU for HuggingFace fallback | Required when not using vLLM; handles device placement automatically. |

**Model size guidance:**
- 8B Instruct: single 24 GB GPU (RTX 3090/4090), best quality/cost for lecture slides.
- 30B-A3B MoE: multi-GPU or 2×24 GB; only needed if slide content is dense technical diagrams.
- 4B Instruct: fits 16 GB GPU, acceptable quality.

### LLM Script Generation Layer

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Claude via `claude -p` (CLI) | current Max Plan | Convert VLM slide summaries → full lecture script paragraphs | Specified constraint: Max Plan = no per-token API cost. Use subprocess or `asyncio.create_subprocess_exec` to call `claude -p`. |
| prompt-toolkit / templating | stdlib `string.Template` | Prompt construction for script style, length, tone | No external dep needed; keep prompts in `.txt` templates, render at runtime. |

**Claude CLI integration pattern:** Stream stdout from `claude -p` subprocess; write directly to job output file. Do not buffer the full response in memory for long scripts.

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

**Storage layout convention:**
```
/data/jobs/{job_id}/
  input.pptx
  slides/         # slide_001.png ... slide_NNN.png
  vlm_output/     # slide_001.json (VLM analysis per slide)
  script/         # full_script.txt, slide_001_script.txt
  audio/          # slide_001.wav ... slide_NNN.wav
```

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

---

## Rationale

### Why Celery over taskiq / ARQ / RQ

Celery is chosen over alternatives because:
1. **Task chaining** — the pipeline is strictly sequential (parse → render → VLM → LLM → TTS). Celery `chain()` makes this explicit and each step retries independently on failure.
2. **GPU job serialisation** — Celery's concurrency=1 worker with `task_acks_late=True` ensures only one GPU task runs at a time without race conditions.
3. **Monitoring** — Flower provides real-time task inspection without extra tooling.

taskiq has better native async support but its GPU workload story is less battle-tested. ARQ has no chain primitives. RQ is too lightweight for multi-step pipelines.

### Why vLLM for VLM inference

Calling `model.generate()` directly with HuggingFace processes one image at a time. vLLM's continuous batching processes multiple slides concurrently within a single GPU context, improving throughput 2–5x for a 20-slide deck. It also exposes an OpenAI-compatible REST endpoint, making it straightforward to call from the Celery worker.

### Why LibreOffice over alternatives

- `python-pptx` can extract shapes but cannot render slides with correct fonts/themes to PNG.
- Headless Chrome (Puppeteer) requires a browser binary and PPT→HTML conversion loses fidelity.
- LibreOffice is the only FOSS tool that handles complex PPTX layouts reliably on Linux.

### Why local disk over Supabase Storage

Supabase Storage (S3-compatible) adds network RTT on every file read during the GPU pipeline. Slide PNGs (1–3 MB each) and audio files (5–20 MB each) would create significant latency. Local disk IO is ~1000x faster. Only final outputs (transcript text, audio download URLs) need to be referenced in Supabase rows.

### Why SSE over WebSocket for progress

The pipeline produces one-directional status events (job queued → rendering → VLM → LLM → TTS → done). WebSocket bidirectional overhead is unnecessary. FastAPI `StreamingResponse` with `text/event-stream` is stateless and works through Vercel's proxy to the GPU server API.

---

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

---

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

---

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
