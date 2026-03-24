# Phase 2: VLM Pipeline - Research

**Researched:** 2026-03-24
**Domain:** Async task queue (Celery + Redis), resumable GPU inference, real-time progress streaming (SSE), token overlap analysis
**Confidence:** HIGH

## Summary

Phase 2 evolves the existing synchronous VLM module (`vlm.py`) into a production-grade asynchronous pipeline. The core additions are: (1) Celery task queue with Redis broker for GPU-safe background processing, (2) resumable slide-by-slide processing that survives restarts, (3) real-time progress streaming via SSE backed by Redis Pub/Sub, and (4) a `needs_review` flag based on token overlap between VLM output and parsed slide text.

The existing `vlm.py` already handles model loading, prompt construction (text-grounded), vLLM inference, JSON parsing with retry, and per-slide file output. Phase 2 wraps this logic in Celery tasks without rewriting the inference core. The key architectural challenge is making GPU inference resumable -- since vLLM loads the model once and processes slides sequentially (concurrency=1 on GPU worker), the resumability pattern is file-based: check if `vlm_note_{NNN}.json` exists and is valid before processing each slide.

**Primary recommendation:** Use Celery 5.4.x with Redis 7.x broker, `sse-starlette` for SSE endpoints, file-existence-based resumability (not Celery chain state), and simple set-intersection token overlap for the `needs_review` flag. Keep GPU worker at `concurrency=1`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VLM-01 | 모든 슬라이드 이미지를 Qwen3-VL에 입력해 visual summary, key elements, layout relations, teaching points, possible confusions 생성 | Existing vlm.py already implements this via vLLM offline inference. Phase 2 wraps in Celery task. |
| VLM-02 | VLM 입력 시 파싱된 텍스트를 함께 제공해 환각 방지 (text-grounded prompting) | Existing `build_vlm_prompt()` already implements text-grounded prompting. No changes needed. |
| VLM-03 | VLM 출력을 JSON 스키마로 검증 | Existing `VlmNote` Pydantic model validates output. Phase 2 adds `needs_review` field. |
| INFRA-02 | 비동기 작업 패턴(제출 -> 상태 폴링 -> 결과 반환) 지원 | Celery + Redis + SSE architecture. Job submission via FastAPI, progress via SSE, results on local disk. |
</phase_requirements>

## Prerequisite Warning

**Phase 1 Plan 04 is NOT yet completed.** The `lecture_auto/api/` directory does not exist. Phase 2 depends on:
- FastAPI application skeleton (`api/main.py`)
- JWT auth dependency (`api/deps.py`)
- Upload endpoint (`api/routes/upload.py`)

Phase 2 plans MUST either (a) assume Plan 01-04 is completed first, or (b) include the FastAPI skeleton setup as a Wave 0 prerequisite task.

## Decision Clarification: Celery vs BackgroundTasks

STATE.md records an early Init decision: "FastAPI BackgroundTasks 사용 (Celery 불필요, 단일 교수 워크플로우)". However, CLAUDE.md explicitly lists "FastAPI BackgroundTasks for GPU jobs" in the "What NOT to Use" table with rationale: "BackgroundTasks run in the same process; GPU memory exhaustion will kill the API server."

**Resolution:** CLAUDE.md's technology stack mandates Celery 5.4.x for GPU pipeline tasks. The Init decision was made before the full architecture was established. Phase 2 introduces Celery as specified in CLAUDE.md. This is consistent with INFRA-02 requirements and the ROADMAP description ("비동기 작업 시스템").

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| celery | 5.4.x | Async task queue for GPU pipeline stages | Production-mature, task chaining with `chain()`/`chord()`, retry/backoff, acks_late for crash safety. Mandated by CLAUDE.md. |
| redis (redis-py) | >=5.0 | Celery broker + result backend + SSE pub/sub channel | Fastest broker for single-server setup. Built-in async support via `redis.asyncio` (aioredis merged into redis-py 4.2+). |
| sse-starlette | >=2.0 | SSE endpoint for real-time progress streaming | Standard SSE library for FastAPI/Starlette. Provides `EventSourceResponse` that wraps async generators. |
| vllm | >=0.11.0 | Qwen3-VL inference (already installed) | Already in use from Phase 01.1. No version change needed. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| redis (server) | 7.x | Message broker + pub/sub | Always -- runs as Docker container on GPU server |
| flower | >=2.0 | Celery monitoring dashboard (optional) | Development/debugging -- monitor task states, worker health |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Celery | FastAPI BackgroundTasks | REJECTED by CLAUDE.md -- GPU OOM kills API server |
| Celery | ARQ / RQ | No native task-chain primitives; too lightweight for 5-step pipeline. REJECTED by CLAUDE.md. |
| Redis pub/sub for SSE | Polling Celery result backend | Higher latency, no streaming granularity. Redis pub/sub gives per-slide events. |
| sse-starlette | Raw StreamingResponse | sse-starlette handles W3C SSE spec compliance, reconnection, keep-alive automatically |

### Installation

```bash
pip install "celery[redis]>=5.4,<6.0" "redis>=5.0" "sse-starlette>=2.0"
```

Add to `pyproject.toml` dependencies:
```toml
"celery[redis]>=5.4,<6.0",
"redis>=5.0",
"sse-starlette>=2.0",
```

## Architecture Patterns

### Recommended Project Structure

```
lecture_auto/
  api/
    main.py              # FastAPI app (from Phase 1 Plan 04)
    deps.py              # JWT auth dependency
    routes/
      upload.py           # POST /upload (existing)
      jobs.py             # GET /jobs/{id}/status, GET /jobs/{id}/progress (NEW)
  pipeline/
    vlm.py               # VLM inference (existing, minor additions)
    parser.py             # PPTX parser (existing)
    renderer.py           # Slide renderer (existing)
    ...
  tasks/
    __init__.py           # Celery app instance
    celery_app.py         # Celery configuration
    vlm_tasks.py          # VLM Celery task definitions
    progress.py           # Redis pub/sub progress helper
  schemas/
    manifest.py           # Existing schemas
    job_status.py         # Job status enum + progress schema (NEW)
  storage/
    jobs.py               # JobPaths (existing)
```

### Pattern 1: Celery App Configuration

**What:** Single Celery app instance configured for GPU-safe operation.
**When to use:** Always -- this is the entry point for all async tasks.

```python
# lecture_auto/tasks/celery_app.py
from celery import Celery

celery_app = Celery(
    "lecture_auto",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,           # Acknowledge after completion (crash safety)
    worker_prefetch_multiplier=1,  # Don't prefetch extra tasks
    worker_concurrency=1,          # GPU: one task at a time
    task_reject_on_worker_lost=True,  # Re-queue if worker dies
    task_track_started=True,       # Track STARTED state
    result_expires=86400,          # Results expire after 24h
)
```

**Critical config for GPU workers:**
- `worker_concurrency=1` -- GPU cannot run parallel inference tasks
- `task_acks_late=True` -- if worker crashes mid-slide, task is re-queued
- `task_reject_on_worker_lost=True` -- pairs with acks_late for crash recovery
- `worker_prefetch_multiplier=1` -- don't prefetch; GPU tasks are long-running

### Pattern 2: Resumable VLM Task (File-Based Checkpointing)

**What:** Each slide's VLM note is checkpointed to disk. On restart, completed slides are skipped.
**When to use:** VLM inference task -- the most expensive step.

```python
# lecture_auto/tasks/vlm_tasks.py
import json
import logging
from pathlib import Path
from celery import shared_task
from lecture_auto.tasks.progress import publish_progress

logger = logging.getLogger(__name__)

@shared_task(bind=True, name="vlm.process_slides", max_retries=2)
def process_slides_task(self, job_id: str) -> dict:
    """Process all slides through VLM with resumability.

    Checkpointing strategy:
    - Each completed slide writes vlm_note_{NNN}.json to disk
    - On restart, existing valid JSON files are skipped
    - Progress is published to Redis pub/sub per slide
    """
    from lecture_auto.pipeline.vlm import load_vlm, generate_single_note
    from lecture_auto.storage.jobs import JobPaths
    from lecture_auto.schemas.manifest import SlideManifest

    job_paths = JobPaths(job_id)
    manifest = SlideManifest.model_validate_json(
        job_paths.manifest_path.read_text()
    )

    slides = manifest.slides
    total = len(slides)
    completed = []
    skipped = 0

    # Load VLM model once for entire job
    llm = load_vlm()

    for i, slide in enumerate(slides):
        note_path = job_paths.vlm_dir / f"vlm_note_{slide.slide_number:03d}.json"

        # RESUMABILITY: Skip if already completed
        if note_path.exists():
            try:
                existing = json.loads(note_path.read_text())
                # Validate it has required fields
                if all(k in existing for k in ("visual_summary", "key_elements", "teaching_points")):
                    skipped += 1
                    publish_progress(job_id, "vlm", i + 1, total, "skipped")
                    completed.append(existing)
                    continue
            except (json.JSONDecodeError, KeyError):
                pass  # Invalid file, re-process

        # Process this slide
        publish_progress(job_id, "vlm", i + 1, total, "processing")
        note = generate_single_note(llm, slide, job_paths.rendered_dir, job_paths.vlm_dir)
        completed.append(note.model_dump())
        publish_progress(job_id, "vlm", i + 1, total, "done")

    logger.info("VLM complete: %d processed, %d skipped (resumed)", total - skipped, skipped)
    return {"job_id": job_id, "total": total, "skipped": skipped}
```

### Pattern 3: Redis Pub/Sub Progress Publishing

**What:** Celery task publishes per-slide progress events to a Redis channel. SSE endpoint subscribes.
**When to use:** Any long-running task that needs real-time UI progress.

```python
# lecture_auto/tasks/progress.py
import json
import redis

_redis_client = None

def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(host="localhost", port=6379, db=2)
    return _redis_client

def publish_progress(job_id: str, stage: str, current: int, total: int, status: str) -> None:
    """Publish progress event to Redis pub/sub channel.

    Channel: job:{job_id}:progress
    """
    event = {
        "job_id": job_id,
        "stage": stage,
        "current": current,
        "total": total,
        "percent": round((current / total) * 100, 1) if total > 0 else 0,
        "status": status,  # "processing" | "done" | "skipped" | "error"
    }
    get_redis().publish(
        f"job:{job_id}:progress",
        json.dumps(event),
    )
```

### Pattern 4: SSE Endpoint with Redis Subscription

**What:** FastAPI SSE endpoint that subscribes to Redis pub/sub and streams events to client.
**When to use:** Frontend progress display.

```python
# lecture_auto/api/routes/jobs.py
import json
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse
from redis.asyncio import Redis as AsyncRedis

router = APIRouter(prefix="/jobs", tags=["jobs"])

async def _progress_generator(job_id: str):
    """Async generator that yields SSE events from Redis pub/sub."""
    r = AsyncRedis(host="localhost", port=6379, db=2)
    pubsub = r.pubsub()
    await pubsub.subscribe(f"job:{job_id}:progress")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                yield {
                    "event": "progress",
                    "data": json.dumps(data),
                }
                # End stream when all stages complete
                if data.get("stage") == "vlm" and data.get("status") == "done" and data.get("current") == data.get("total"):
                    yield {"event": "complete", "data": json.dumps({"job_id": job_id})}
                    break
    finally:
        await pubsub.unsubscribe(f"job:{job_id}:progress")
        await r.aclose()

@router.get("/{job_id}/progress")
async def stream_progress(job_id: str):
    """SSE endpoint for real-time job progress."""
    return EventSourceResponse(_progress_generator(job_id))
```

### Pattern 5: Token Overlap for needs_review Flag

**What:** Compare VLM-generated text tokens against parsed slide text tokens. Flag slides where VLM output has less than 30% overlap with parsed text.
**When to use:** Post-VLM validation step, per-slide.

```python
# lecture_auto/pipeline/vlm.py (addition to existing module)
import re

def compute_token_overlap(vlm_text: str, parsed_text: str) -> float:
    """Compute token overlap ratio between VLM output and parsed slide text.

    Uses simple whitespace + punctuation tokenization.
    Returns ratio in [0.0, 1.0] representing fraction of VLM tokens
    found in parsed text tokens.

    Low overlap (<0.30) suggests VLM may be hallucinating content
    not present in the original slide.
    """
    def tokenize(text: str) -> set[str]:
        # Normalize: lowercase, split on whitespace and punctuation
        tokens = re.findall(r'[\w]+', text.lower())
        return set(tokens)

    vlm_tokens = tokenize(vlm_text)
    parsed_tokens = tokenize(parsed_text)

    if not vlm_tokens:
        return 1.0  # No VLM tokens = nothing to check
    if not parsed_tokens:
        return 0.0  # No parsed text = VLM generated everything from image only

    overlap = vlm_tokens & parsed_tokens
    # Ratio: what fraction of VLM tokens appear in parsed text
    return len(overlap) / len(vlm_tokens)
```

**Rationale for this approach:**
- Simple set intersection -- no external NLP library needed
- `re.findall(r'[\w]+', text.lower())` handles Korean (Hangul matched by `\w`) and English
- Ratio denominator is VLM token count: "what fraction of what VLM said came from the slide text"
- Threshold 30% means VLM is introducing 70%+ new content not in the text -- likely visual-only or hallucinated

### Pattern 6: Extended VlmNote Schema with needs_review

```python
# Updated VlmNote in vlm.py
class VlmNote(BaseModel):
    slide_index: int
    visual_summary: str
    key_elements: list[str]
    layout_relations: str
    teaching_points: list[str]
    possible_confusions: list[str]
    needs_review: bool = False
    token_overlap_ratio: float = 1.0
```

### Anti-Patterns to Avoid

- **Multiple Celery workers on single GPU:** `concurrency > 1` will OOM or deadlock GPU. Always use `concurrency=1`.
- **Celery chain state for resumability:** Celery chains do not persist intermediate results across worker restarts. Use file-based checkpointing instead.
- **Loading VLM model per-slide:** vLLM model loading takes 30-60 seconds. Load once at task start, process all slides, then unload. Never load inside a loop.
- **Polling Celery result backend for progress:** Result backend only stores final results. For per-slide granularity, use Redis pub/sub.
- **WebSocket for one-way progress:** SSE is simpler, works through HTTP proxies, sufficient for server-to-client progress updates. CLAUDE.md explicitly rejects WebSocket for this use case.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Task queue | Custom subprocess manager | Celery 5.4.x | Retry, backoff, crash recovery, task chaining, monitoring |
| SSE protocol | Raw `StreamingResponse` with manual formatting | `sse-starlette` EventSourceResponse | W3C spec compliance, reconnection, keep-alive |
| Message broker | File-based IPC or database polling | Redis 7.x | Sub-millisecond pub/sub, built-in Celery support |
| Progress tracking | Database polling loop | Redis pub/sub channels | Real-time, no polling latency, no DB load |
| Token overlap | Heavy NLP pipeline (spaCy, NLTK) | Simple `re.findall` + set intersection | Korean text works with `\w`, no extra dependencies |

**Key insight:** The VLM inference logic already exists in `vlm.py`. Phase 2 is primarily an infrastructure/orchestration phase wrapping existing logic in async patterns. Resist rewriting the inference core.

## Common Pitfalls

### Pitfall 1: VLM Model Loading in Wrong Scope

**What goes wrong:** Model loaded per-task invocation, adding 30-60s overhead per restart.
**Why it happens:** Celery tasks are functions; developers load resources at function level.
**How to avoid:** Load model once at worker startup or at first task execution, cache in module-level variable. Use `@worker_process_init.connect` signal or lazy singleton pattern.
**Warning signs:** Task execution time includes 30-60s overhead on first slide.

### Pitfall 2: Redis Pub/Sub Message Loss

**What goes wrong:** Client connects to SSE after task starts; misses early progress events.
**Why it happens:** Redis pub/sub is fire-and-forget; no message persistence.
**How to avoid:** Store latest progress state in a Redis key (`SET job:{id}:last_progress ...`). SSE endpoint reads initial state from key, then subscribes to pub/sub for live updates.
**Warning signs:** UI shows 0% then jumps to 40% on first SSE event received.

### Pitfall 3: Stale Checkpoint Files

**What goes wrong:** VLM note JSON exists but is from a previous run with different model/prompt settings.
**Why it happens:** File existence check doesn't validate provenance.
**How to avoid:** Include a checksum or version marker in each VLM note file (e.g., `"model_version": "Qwen3-VL-8B-Instruct"`, `"prompt_version": "v1"`). On restart, compare markers. If mismatch, re-process.
**Warning signs:** Resumed job produces inconsistent results across slides.

### Pitfall 4: GPU OOM on Worker Restart

**What goes wrong:** Worker crashes, restarts, and immediately reloads model + starts processing.
**Why it happens:** Previous process didn't release GPU memory cleanly.
**How to avoid:** Add a startup delay or GPU memory check before model loading. Use `torch.cuda.empty_cache()` at worker init. Consider `CUDA_VISIBLE_DEVICES` env var to pin GPU.
**Warning signs:** Worker enters crash loop with CUDA OOM errors.

### Pitfall 5: SSE Connection Timeout

**What goes wrong:** Long-running VLM jobs (30+ slides) cause SSE connections to time out.
**Why it happens:** HTTP proxies or load balancers timeout idle connections.
**How to avoid:** Send periodic keep-alive comments (`:keep-alive\n\n`) every 15 seconds. `sse-starlette` supports this via `ping` parameter.
**Warning signs:** Frontend loses connection mid-job, shows stale progress.

### Pitfall 6: Token Overlap False Positives on Image-Heavy Slides

**What goes wrong:** Slides with diagrams/images and minimal text get flagged as `needs_review` because VLM describes visual content not in parsed text.
**Why it happens:** Image-heavy slides legitimately have low text overlap -- VLM is describing what it sees.
**How to avoid:** Only flag if slide has substantial text (`parsed_text` token count > 10) AND overlap < 30%. For image-only slides (token count <= 10), skip the check or use a lower threshold.
**Warning signs:** Most diagram slides incorrectly flagged.

## Code Examples

### Celery Worker Startup Command

```bash
# Start single-GPU worker with concurrency=1
celery -A lecture_auto.tasks.celery_app worker \
    --loglevel=info \
    --concurrency=1 \
    --pool=solo \
    -Q gpu_queue \
    -n gpu_worker@%h
```

**Notes:**
- `--pool=solo` -- single-threaded, avoids fork issues with CUDA
- `-Q gpu_queue` -- dedicated queue for GPU tasks
- `--concurrency=1` -- one task at a time

### Job Submission Flow

```python
# In upload endpoint (after parse + render complete)
from lecture_auto.tasks.vlm_tasks import process_slides_task

@router.post("/upload")
async def upload_pptx(...):
    # ... parse PPTX, render slides (synchronous in Phase 1) ...

    # Submit VLM task to Celery queue
    task = process_slides_task.apply_async(
        args=[job_id],
        queue="gpu_queue",
    )

    # Store task_id for status lookup
    # (write to Supabase or Redis)

    return {"job_id": job_id, "task_id": task.id, "status": "queued"}
```

### Refactoring vlm.py: Extract Single-Slide Function

The existing `generate_visual_notes()` processes all slides in a loop. For resumability, extract single-slide logic:

```python
# lecture_auto/pipeline/vlm.py (refactored)
def generate_single_note(
    llm: LLM,
    slide: SlideRecord,
    rendered_dir: Path,
    vlm_dir: Path,
) -> VlmNote:
    """Generate VLM note for a single slide. Writes JSON to disk.

    This is the atomic unit of work for resumability.
    """
    prompt = build_vlm_prompt(slide, rendered_dir)
    sampling_params = SamplingParams(temperature=0.3, max_tokens=1024)
    results = llm.generate(prompt, sampling_params)
    response_text = results[0].outputs[0].text

    try:
        data = _parse_vlm_json(response_text, slide.slide_index)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        # Retry with lower temperature
        retry_params = SamplingParams(temperature=0.1, max_tokens=1024)
        retry_results = llm.generate(prompt, retry_params)
        data = _parse_vlm_json(retry_results[0].outputs[0].text, slide.slide_index)

    # Compute token overlap for needs_review flag
    vlm_text = f"{data.get('visual_summary', '')} {' '.join(data.get('key_elements', []))} {' '.join(data.get('teaching_points', []))}"
    parsed_text = _extract_slide_text(slide)
    overlap = compute_token_overlap(vlm_text, parsed_text)

    parsed_token_count = len(re.findall(r'[\w]+', parsed_text.lower()))
    data["needs_review"] = (parsed_token_count > 10 and overlap < 0.30)
    data["token_overlap_ratio"] = round(overlap, 3)

    note = VlmNote(**data)

    # Write to disk (checkpoint)
    out_path = vlm_dir / f"vlm_note_{slide.slide_number:03d}.json"
    out_path.write_text(
        json.dumps(note.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return note
```

### Redis Docker Setup

```bash
# docker-compose.yml addition for GPU server
docker run -d \
    --name lecture-auto-redis \
    --restart unless-stopped \
    -p 6379:6379 \
    redis:7-alpine \
    redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| aioredis (separate package) | redis-py `redis.asyncio` | redis-py 4.2+ (2022) | Use `redis.asyncio.Redis` instead of `aioredis.Redis` |
| Celery ResultBackend polling | Redis Pub/Sub + SSE | Current best practice | Real-time progress without polling overhead |
| WebSocket for progress | SSE for one-way streams | Industry consensus | Simpler, HTTP-proxy friendly, sufficient for progress |
| Complex NLP for text comparison | Simple set-intersection tokenization | Pragmatic for this use case | No extra deps, handles Korean via `\w` regex |

## Open Questions

1. **Phase 1 Plan 04 completion**
   - What we know: `api/` directory does not exist. FastAPI skeleton not yet created.
   - What's unclear: Whether Plan 04 will be completed before Phase 2 starts.
   - Recommendation: Phase 2 Wave 0 should verify FastAPI skeleton exists and create it if needed, OR explicitly require Plan 01-04 as a prerequisite gate.

2. **VLM model loading strategy for Celery worker**
   - What we know: `load_vlm()` takes 30-60s. Must load once, reuse across slides.
   - What's unclear: Best Celery pattern -- worker process init signal vs. lazy singleton vs. pre-loaded module variable.
   - Recommendation: Use lazy singleton pattern in `vlm_tasks.py` (load on first task, cache in module variable). Simpler than Celery signals, compatible with `--pool=solo`.

3. **GPU server second GPU availability**
   - What we know: STATE.md notes blocker: "GPU 서버 2번째 GPU 유무 확인 필요 (VLM+TTS 동시 구동 가능 여부)"
   - What's unclear: Whether VLM and TTS will need to share a single GPU.
   - Recommendation: Phase 2 only uses VLM. Design for single GPU (`CUDA_VISIBLE_DEVICES=0`). TTS GPU allocation is a Phase 4 concern.

4. **Token overlap threshold tuning**
   - What we know: 30% threshold is specified in Success Criteria #4.
   - What's unclear: Whether 30% is optimal for Korean academic slides.
   - Recommendation: Implement with configurable threshold (env var or config), default 0.30. Log all overlap ratios for post-hoc analysis and threshold tuning.

## Sources

### Primary (HIGH confidence)
- [Celery 5.6.x documentation - Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html) -- acks_late, task configuration, idempotency guidance
- [Celery 5.6.x documentation - Canvas/Workflows](https://docs.celeryq.dev/en/stable/userguide/canvas.html) -- chain, chord, group primitives
- [FastAPI official SSE tutorial](https://fastapi.tiangolo.com/tutorial/server-sent-events/) -- native SSE support in FastAPI
- [redis-py asyncio documentation](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) -- async Redis pub/sub
- [sse-starlette PyPI](https://pypi.org/project/sse-starlette/) -- EventSourceResponse for FastAPI
- CLAUDE.md technology stack -- Celery 5.4.x, Redis 7.x mandated
- Existing `vlm.py` source code -- current inference implementation

### Secondary (MEDIUM confidence)
- [Celery + Redis + FastAPI production guide 2025](https://medium.com/@dewasheesh.rana/celery-redis-fastapi-the-ultimate-2025-production-guide-broker-vs-backend-explained-5b84ef508fa7) -- integration patterns verified against official docs
- [SSE in FastAPI using Redis Pub/Sub](https://medium.com/deepdesk/server-sent-events-in-fastapi-using-redis-pub-sub-eba1dbfe8031) -- architecture pattern verified with FastAPI official docs
- [Resumable tasks in Celery (dev.to)](https://dev.to/totally_chase/how-you-can-implement-resumable-tasks-in-celery-3nk5) -- chain-based resumability pattern (adapted to simpler file-based approach)
- [Real-Time Celery Progress Bars with FastAPI](https://celery.school/celery-progress-bars-with-fastapi-htmx) -- progress streaming pattern

### Tertiary (LOW confidence)
- Token overlap threshold of 30% -- specified in requirements but not empirically validated. Needs tuning with real Korean academic slides.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- Celery + Redis + SSE is well-documented, mandated by CLAUDE.md
- Architecture: HIGH -- File-based resumability is simple and proven; Redis pub/sub for SSE is standard pattern
- Pitfalls: HIGH -- GPU worker constraints, model loading scope, pub/sub message loss are well-known issues
- Token overlap: MEDIUM -- Simple implementation is sound, but 30% threshold needs empirical validation

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable stack, no fast-moving components)
