# Phase 4: TTS + Delivery - Research

**Researched:** 2026-03-30
**Domain:** TTS voice synthesis, voice cloning, audio delivery pipeline, browser audio recording
**Confidence:** HIGH

## Summary

Phase 4 connects the approved scripts from Phase 3 to Qwen3-TTS for voice synthesis with voice cloning, adds per-slide audio preview, and packages final deliverables (WAV + MP4 + JSON) as a downloadable ZIP. The existing codebase already has the core TTS pipeline (`tts.py`), video assembly (`video.py`), Celery task patterns (`vlm_tasks.py`, `script_tasks.py`), and progress infrastructure (`progress.py`). The primary work is: (1) switching from CustomVoice to Base model for voice cloning support, (2) wrapping TTS in a Celery task on `gpu_queue`, (3) wiring the approve endpoint to trigger TTS, (4) adding voice registration and audio serving endpoints, (5) ZIP package generation, and (6) Next.js UI for voice recording, audio preview, and download.

**Critical discovery:** The existing `tts.py` uses `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` which provides preset speakers but does NOT support voice cloning from reference audio. Voice cloning requires `Qwen/Qwen3-TTS-12Hz-1.7B-Base` with the `qwen-tts` package (`Qwen3TTSModel.generate_voice_clone()`). This is a mandatory model swap.

**Primary recommendation:** Refactor `tts.py` to use `qwen-tts` package with `Qwen3TTSModel` (Base model), implement `generate_voice_clone()` for cloned voice and keep `generate_custom_voice()` as fallback when no voice reference is registered. Follow the exact Celery task pattern from `vlm_tasks.py` for the TTS task.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Voice Clone supports both browser recording and file upload -- professor chooses preferred method
- **D-02:** One-time registration applied to all lectures -- voice_ref stored in professor profile, not per-lecture
- **D-03:** 3-second audio clip (Qwen3-TTS Voice Clone requirement)
- **D-04:** Per-slide playback button -- WAV play control next to each slide
- **D-05:** Individual slide re-TTS possible -- modify script, re-generate that slide only (reuse Phase 3 regeneration pattern)
- **D-06:** Final package includes MP4 video -- script JSON + per-slide WAV + merged WAV + lecture MP4
- **D-07:** ZIP format for one-click download
- **D-08:** Phase 3 approve endpoint triggers TTS Celery task automatically

### Claude's Discretion
- TTS Celery task internal implementation (follow Phase 2 vlm_tasks.py pattern, gpu_queue)
- Voice Clone registration API endpoint design
- Browser recording WebAudio API implementation details
- ZIP package generation method
- MP4 video generation (reuse existing video.py assemble_video)
- Audio preview UI component details

### Deferred Ideas (OUT OF SCOPE)
- Supabase Auth integration -- separate Phase (INFRA-03)
- TTS speed/tone control parameters -- v2 feature
- Multiple professor Voice Clone profile management -- v2 feature
- Real-time TTS streaming playback -- Out of Scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TTS-01 | Generate per-slide audio from approved scripts via Qwen3-TTS | Celery task on gpu_queue wrapping `synthesize_slide()`, Base model with `generate_voice_clone()` |
| TTS-02 | Support voice cloning from 3-second audio registration | `Qwen3TTSModel.generate_voice_clone(ref_audio=path, ref_text=transcript)` with Base model |
| TTS-03 | Per-slide audio preview before full generation | FastAPI FileResponse serving individual WAV files from `audio/` directory |
| TTS-04 | Merge all slide audio into single lecture audio | Existing `synthesize_audio()` pattern + `numpy.concatenate` or ffmpeg concat |
| UI-04 | Download final package (script JSON + audio files) from portal | ZIP streaming via `zipfile` + `StreamingResponse`, includes WAV + MP4 + JSON |
</phase_requirements>

## Standard Stack

### Core (Already in Project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Celery | 5.4.x | TTS async task queue on gpu_queue | Already configured with gpu_queue + cpu_queue routing |
| Redis | 7.x | Broker + progress pub/sub | Already integrated for VLM/script progress |
| FastAPI | 0.135.1 | TTS routes, audio serving, download endpoint | Already running with CORS, lifespan management |
| soundfile | >=0.13.1 | WAV read/write | Already in pyproject.toml dependencies |
| numpy | >=1.26 | Audio array manipulation, concatenation | Already in pyproject.toml dependencies |

### New Dependencies Required
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| qwen-tts | latest (PyPI) | `Qwen3TTSModel` with `generate_voice_clone()` and `generate_custom_voice()` | **Replaces** raw transformers `AutoModelForCausalLM` usage in current `tts.py` |
| python-multipart | >=0.0.9 | FastAPI file upload support (voice reference WAV) | Required for `UploadFile` in voice registration endpoint |
| zipstream-ng | >=1.7 | Streaming ZIP generation without loading all files into memory | Package download endpoint -- streams ZIP on the fly |

### Model Change (CRITICAL)
| Current | New | Why |
|---------|-----|-----|
| `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | CustomVoice has preset speakers only; Base model supports voice cloning via `generate_voice_clone()` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| zipstream-ng | stdlib `zipfile` + `BytesIO` | Works but loads entire ZIP into memory; zipstream-ng streams with ~20MB peak |
| qwen-tts package | Raw transformers generate() | Current approach in tts.py; but `qwen-tts` is the official package with proper voice clone API |
| ffmpeg concat for merged audio | numpy concatenation + soundfile | Both work; numpy is simpler for same-format WAV files, ffmpeg needed only for MP4 |

**Installation:**
```bash
pip install qwen-tts zipstream-ng python-multipart
```

## Architecture Patterns

### Recommended Project Structure (New/Modified Files)
```
lecture_auto/
  pipeline/
    tts.py              # REFACTOR: switch to qwen_tts.Qwen3TTSModel (Base model)
  tasks/
    tts_tasks.py         # NEW: Celery TTS task (gpu_queue), pattern from vlm_tasks.py
    celery_app.py        # MODIFY: add "tts.*" -> gpu_queue routing
  api/routes/
    tts.py               # NEW: voice registration, audio serving, re-TTS
    download.py          # NEW: ZIP package generation + download endpoint
    scripts.py           # MODIFY: approve endpoint triggers TTS task
  schemas/
    tts.py               # NEW: VoiceRegisterRequest, TTSResponse, PackageResponse
  storage/
    voice_store.py       # NEW: voice reference file management (professor profile)
    jobs.py              # MINOR: add video_dir property if needed
```

### Pattern 1: TTS Celery Task (mirror vlm_tasks.py)
**What:** Resumable per-slide TTS with file-based checkpointing
**When to use:** All TTS generation
**Example:**
```python
# lecture_auto/tasks/tts_tasks.py
_tts_model = None

def _get_tts():
    """Lazy-load TTS model (singleton per worker process)."""
    global _tts_model
    if _tts_model is None:
        from lecture_auto.pipeline.tts import load_tts
        _tts_model = load_tts()
    return _tts_model

@shared_task(
    bind=True,
    name="tts.synthesize",
    max_retries=2,
    queue="gpu_queue",
    acks_late=True,
)
def synthesize_job_task(self, job_id: str, voice_ref_path: str | None = None) -> dict:
    """TTS for all slides with per-slide checkpointing."""
    # For each slide:
    #   1. Check if audio_{NNN}.wav exists -> skip
    #   2. Otherwise -> synthesize_slide(), publish progress
    #   3. After all slides -> merge audio -> assemble video -> create ZIP
    ...
```

### Pattern 2: Approve -> TTS Trigger (Chain Pattern)
**What:** Modify existing approve endpoint to dispatch TTS Celery task
**When to use:** When professor clicks "Approve All Scripts"
**Example:**
```python
# In scripts.py approve_scripts endpoint:
from lecture_auto.tasks.tts_tasks import synthesize_job_task

# After validation passes:
voice_ref = _get_voice_ref_path(job_id)  # From professor profile or job config
task = synthesize_job_task.apply_async(
    args=[job_id, str(voice_ref) if voice_ref else None],
    queue="gpu_queue",
)
return ScriptApproveResponse(
    job_id=job_id,
    total_slides=manifest.slide_count,
    tts_task_id=task.id,
    status="approved",
)
```

### Pattern 3: Voice Reference Storage
**What:** Store voice reference WAV on GPU server local disk
**When to use:** Voice clone registration
**Example:**
```python
# Storage path: /data/voices/{professor_id}/voice_ref.wav
# For MVP (no auth yet): /data/voices/default/voice_ref.wav
VOICE_REF_ROOT = Path(os.environ.get("VOICE_REF_ROOT", "/data/voices"))

def save_voice_ref(professor_id: str, audio_bytes: bytes) -> Path:
    """Save voice reference and return path."""
    ref_dir = VOICE_REF_ROOT / professor_id
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_path = ref_dir / "voice_ref.wav"
    ref_path.write_bytes(audio_bytes)
    return ref_path

def get_voice_ref(professor_id: str) -> Path | None:
    """Get voice reference path, None if not registered."""
    ref_path = VOICE_REF_ROOT / professor_id / "voice_ref.wav"
    return ref_path if ref_path.exists() else None
```

### Pattern 4: ZIP Package Generation
**What:** Stream ZIP with all deliverables
**When to use:** Download endpoint
**Example:**
```python
import zipstream

async def generate_package(job_id: str) -> StreamingResponse:
    job_paths = JobPaths(job_id)
    zs = zipstream.ZipFile(mode='w', compression=zipstream.ZIP_STORED)

    # Add per-slide WAV files
    for wav in sorted(job_paths.audio_dir.glob("audio_*.wav")):
        zs.write(str(wav), arcname=f"audio/{wav.name}")

    # Add merged audio
    merged = job_paths.audio_dir / "lecture_merged.wav"
    if merged.exists():
        zs.write(str(merged), arcname="lecture_merged.wav")

    # Add MP4 video
    video = job_paths.artifacts_dir / f"lecture_{job_id}.mp4"
    if video.exists():
        zs.write(str(video), arcname=f"lecture_{job_id}.mp4")

    # Add scripts JSON
    scripts_json = job_paths.artifacts_dir / "scripts.json"
    zs.write(str(scripts_json), arcname="scripts.json")

    return StreamingResponse(
        zs,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=lecture_{job_id}.zip"},
    )
```

### Anti-Patterns to Avoid
- **Loading all WAV files into memory for ZIP:** Use streaming ZIP (zipstream-ng) to keep memory constant
- **Running TTS in FastAPI process:** Always use Celery gpu_queue worker; GPU OOM will kill the API server
- **Concurrent GPU tasks:** gpu_queue concurrency=1; TTS and VLM tasks serialize naturally
- **Storing voice_ref per job:** Voice reference is per-professor, not per-job (D-02)
- **Re-encoding WAV for audio serving:** Serve WAV files directly via FileResponse; browser `<audio>` handles WAV natively

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Voice cloning inference | Custom transformers generate() pipeline | `qwen-tts` package `Qwen3TTSModel.generate_voice_clone()` | Official API handles tokenization, audio decoding, reference embedding extraction |
| Streaming ZIP | In-memory zipfile.ZipFile + BytesIO | zipstream-ng | Memory-safe for large WAV + MP4 packages (could be 100MB+) |
| Browser audio recording | Custom AudioContext + PCM encoding | MediaRecorder API + WebM -> WAV conversion on server | MediaRecorder is natively supported; convert to WAV server-side with soundfile |
| Audio concatenation | Manual sample alignment | numpy.concatenate on float32 arrays + soundfile.write | All slides use same sample rate (24kHz), simple concatenation works |
| MP4 video assembly | Custom ffmpeg wrapper | Existing `video.py` `assemble_video()` | Already implemented and tested in Phase 01.1 |

**Key insight:** Phase 01.1 already built the full TTS + video pipeline as standalone functions. Phase 4's job is to (a) fix the model (CustomVoice -> Base for cloning), (b) wrap in Celery tasks, (c) expose via API, (d) build UI. The core pipeline logic is reusable.

## Common Pitfalls

### Pitfall 1: CustomVoice vs Base Model Confusion
**What goes wrong:** Using `Qwen3-TTS-12Hz-1.7B-CustomVoice` for voice cloning -- it only has preset speakers, no cloning capability.
**Why it happens:** The existing `tts.py` hardcodes `_DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"`. The name "CustomVoice" is misleading.
**How to avoid:** Switch to `Qwen/Qwen3-TTS-12Hz-1.7B-Base` and use `qwen-tts` package's `Qwen3TTSModel.generate_voice_clone()` API.
**Warning signs:** TTS generates audio but ignores the voice reference file entirely.

### Pitfall 2: GPU Queue Contention (VLM + TTS)
**What goes wrong:** TTS task starts while VLM is still running, causing GPU OOM.
**Why it happens:** Both VLM and TTS use gpu_queue, but if concurrency > 1 or tasks are routed incorrectly.
**How to avoid:** Celery gpu_queue already has `worker_concurrency=1`. TTS tasks must use `queue="gpu_queue"` routing. Tasks serialize naturally.
**Warning signs:** CUDA OOM errors when both models try to load simultaneously.

### Pitfall 3: Browser MediaRecorder WAV Format
**What goes wrong:** MediaRecorder outputs WebM/Opus, not WAV. Sending raw MediaRecorder output to TTS fails.
**Why it happens:** MediaRecorder API does not natively support WAV output in most browsers.
**How to avoid:** Accept WebM/Opus from browser, convert server-side to WAV using soundfile or ffmpeg. Alternatively, use `extendable-media-recorder` + `extendable-media-recorder-wav-encoder` on client side for native WAV.
**Warning signs:** TTS model receives incorrect audio format, produces garbage or errors.

### Pitfall 4: Voice Reference Transcript Requirement
**What goes wrong:** Voice cloning quality is poor because `ref_text` (transcript of reference audio) is missing.
**Why it happens:** `generate_voice_clone()` has both `ref_audio` and `ref_text` parameters. Without `ref_text`, it falls back to `x_vector_only_mode` with reduced quality.
**How to avoid:** Either (a) require professor to provide a transcript of their reference audio, or (b) use `x_vector_only_mode=True` which is simpler but lower quality, or (c) run a quick STT on the reference clip to auto-generate transcript.
**Warning signs:** Cloned voice sounds generic or has artifacts.

### Pitfall 5: Large ZIP Download Timeout
**What goes wrong:** ZIP generation takes too long for large lectures (50+ slides with WAV + MP4).
**Why it happens:** Generating ZIP synchronously in the request handler blocks; large WAV files + MP4 can be 200MB+.
**How to avoid:** Use streaming ZIP (zipstream-ng) so bytes start flowing immediately. Do NOT pre-build ZIP on disk -- stream directly. Set appropriate timeout on Nginx/reverse proxy.
**Warning signs:** Client timeout errors on download, high memory usage on API server.

### Pitfall 6: TTS Model Memory Alongside VLM
**What goes wrong:** TTS model (1.7B, ~4.5GB VRAM) stays loaded in GPU memory while VLM (8B) needs the same GPU.
**Why it happens:** Lazy-loaded singletons in worker process stay resident.
**How to avoid:** Since gpu_queue has concurrency=1, tasks run sequentially. Option A: Accept both models loaded (needs ~20GB+ VRAM). Option B: Unload VLM before TTS and vice versa (complex, fragile). Option C: Use separate workers for VLM and TTS with different GPU assignments (if multi-GPU). For single GPU: models load on first use and stay loaded; ensure sufficient VRAM.
**Warning signs:** Out-of-memory when switching between VLM and TTS tasks.

## Code Examples

### Example 1: Refactored tts.py with qwen-tts Package
```python
# lecture_auto/pipeline/tts.py (refactored)
from __future__ import annotations
import logging
from pathlib import Path
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 24000
_DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"  # CHANGED from CustomVoice

try:
    import torch
    from qwen_tts import Qwen3TTSModel
except ImportError:
    torch = None
    Qwen3TTSModel = None


def load_tts(model_path: str = _DEFAULT_MODEL) -> "Qwen3TTSModel":
    """Load Qwen3-TTS Base model for voice cloning."""
    if Qwen3TTSModel is None:
        raise RuntimeError("qwen-tts not installed. Run: pip install qwen-tts")
    model = Qwen3TTSModel.from_pretrained(
        model_path,
        device_map="cuda:0",
        dtype=torch.bfloat16,
    )
    logger.info("TTS model loaded: %s", model_path)
    return model


def synthesize_slide(
    model: "Qwen3TTSModel",
    text: str,
    output_path: Path,
    voice_ref_path: Path | None = None,
    voice_ref_text: str | None = None,
) -> Path:
    """Synthesize audio for a single slide with optional voice cloning."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not text or not text.strip():
        sf.write(str(output_path), np.zeros(24000, dtype=np.float32), 24000)
        return output_path

    if voice_ref_path and voice_ref_path.exists():
        # Voice cloning mode
        wavs, sr = model.generate_voice_clone(
            text=text,
            ref_audio=str(voice_ref_path),
            ref_text=voice_ref_text or "",
            x_vector_only_mode=(voice_ref_text is None),
        )
    else:
        # Fallback: default speaker (no cloning)
        wavs, sr = model.generate_custom_voice(
            text=text,
            speaker="Chelsie",
            language="ko",
        )

    sf.write(str(output_path), wavs[0], sr)
    return output_path
```

### Example 2: Browser Voice Recording (Next.js)
```typescript
// components/VoiceRecorder.tsx
"use client";
import { useState, useRef, useCallback } from "react";

export function VoiceRecorder({ onRecorded }: { onRecorded: (blob: Blob) => void }) {
  const [recording, setRecording] = useState(false);
  const [countdown, setCountdown] = useState(3);
  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  const startRecording = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
    chunks.current = [];

    recorder.ondataavailable = (e) => chunks.current.push(e.data);
    recorder.onstop = () => {
      const blob = new Blob(chunks.current, { type: "audio/webm" });
      onRecorded(blob);
      stream.getTracks().forEach((t) => t.stop());
    };

    recorder.start();
    mediaRecorder.current = recorder;
    setRecording(true);

    // Auto-stop after 3 seconds
    setTimeout(() => {
      recorder.stop();
      setRecording(false);
    }, 3000);
  }, [onRecorded]);

  return (
    <div>
      <button onClick={startRecording} disabled={recording}>
        {recording ? "Recording..." : "Record Voice (3s)"}
      </button>
    </div>
  );
}
```

### Example 3: Server-Side WebM to WAV Conversion
```python
# In voice registration endpoint
import io
import subprocess
import soundfile as sf
import numpy as np

def convert_webm_to_wav(webm_bytes: bytes) -> bytes:
    """Convert WebM/Opus audio to WAV using ffmpeg."""
    result = subprocess.run(
        ["ffmpeg", "-i", "pipe:0", "-f", "wav", "-acodec", "pcm_s16le",
         "-ar", "24000", "-ac", "1", "pipe:1"],
        input=webm_bytes,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr.decode()}")
    return result.stdout
```

### Example 4: Re-TTS Single Slide
```python
# In tts routes
@router.post("/{job_id}/tts/{slide_number}/regenerate")
async def regenerate_slide_tts(job_id: str, slide_number: int):
    """Re-generate TTS for a single slide after script edit."""
    from lecture_auto.tasks.tts_tasks import regenerate_slide_tts_task

    voice_ref = _get_voice_ref_path()
    task = regenerate_slide_tts_task.apply_async(
        args=[job_id, slide_number, str(voice_ref) if voice_ref else None],
        queue="gpu_queue",
    )
    return {"job_id": job_id, "slide_number": slide_number, "task_id": task.id}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| transformers AutoModelForCausalLM for TTS | `qwen-tts` package `Qwen3TTSModel` | Jan 2026 (Qwen3-TTS release) | Official API with proper voice clone, custom voice, voice design methods |
| CustomVoice model for all TTS | Base model for clone, CustomVoice for preset | Jan 2026 | Must use correct model variant per use case |
| Manual tokenizer + generate() | `generate_voice_clone()` / `generate_custom_voice()` | Jan 2026 | Simplified API, handles audio decoding internally |

**Deprecated/outdated:**
- Raw `transformers` usage for Qwen3-TTS: The `qwen-tts` package wraps all complexity. The current `tts.py` pattern (AutoModelForCausalLM + manual tokenization) should be replaced.
- `Qwen3-TTS-12Hz-1.7B-CustomVoice` for voice cloning: Does not support cloning. Use Base model.

## Open Questions

1. **Voice Reference Transcript (ref_text)**
   - What we know: `generate_voice_clone()` accepts `ref_text` for better quality; `x_vector_only_mode=True` skips it but reduces quality
   - What's unclear: How much quality degrades with `x_vector_only_mode`? Is it acceptable for 3-second clips?
   - Recommendation: Start with `x_vector_only_mode=True` (simpler UX -- no transcript needed). If quality is insufficient, add optional transcript input or auto-STT the reference clip.

2. **GPU Memory for VLM + TTS Coexistence**
   - What we know: VLM (8B ~16GB) + TTS (1.7B ~4.5GB) = ~20.5GB on single 24GB GPU. Tight.
   - What's unclear: Whether both models can coexist in GPU memory on the lab's GPU server
   - Recommendation: Implement lazy loading with model unloading between stages. Or if multi-GPU is available, assign VLM to GPU:0 and TTS to GPU:1.

3. **qwen-tts Package Compatibility with Python 3.11**
   - What we know: qwen-tts recommends Python 3.12, supports 3.9-3.13
   - What's unclear: Any edge cases with Python 3.11 (project's current runtime)
   - Recommendation: Test installation early. Python 3.11 is in the supported range, should work.

4. **CustomVoice Fallback When No Voice Ref**
   - What we know: Base model's `generate_voice_clone()` requires ref_audio. Without it, need different method.
   - What's unclear: Can Base model do default TTS without voice ref? Or do we need CustomVoice model as fallback?
   - Recommendation: Use Base model with `generate_voice_clone()` when voice ref exists. For no-ref fallback, Base model likely also has a basic generate method, but verify. Worst case: load CustomVoice model separately for fallback (not ideal for VRAM).

## Sources

### Primary (HIGH confidence)
- [Qwen3-TTS GitHub](https://github.com/QwenLM/Qwen3-TTS) - Official repo, voice clone API, model variants
- [qwen-tts PyPI](https://pypi.org/project/qwen-tts/) - Official Python package for Qwen3-TTS
- [Qwen3-TTS-12Hz-1.7B-Base HuggingFace](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base) - Base model card for voice cloning
- [Qwen3-TTS-12Hz-1.7B-CustomVoice HuggingFace](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) - CustomVoice model card (preset speakers)
- [vLLM-Omni Qwen3-TTS docs](https://docs.vllm.ai/projects/vllm-omni/en/latest/user_guide/examples/online_serving/qwen3_tts/) - vLLM serving option

### Secondary (MEDIUM confidence)
- [Qwen3-TTS Voice Cloning Guide (ocdevel)](https://ocdevel.com/blog/20260302-qwen-tts-voice-cloning) - Reference audio best practices
- [Qwen3-TTS Complete Guide (dev.to)](https://dev.to/czmilo/qwen3-tts-the-complete-2026-guide-to-open-source-voice-cloning-and-ai-speech-generation-1in6) - End-to-end tutorial
- [MediaRecorder API MDN](https://developer.mozilla.org/en-US/docs/Web/API/MediaStream_Recording_API/Using_the_MediaStream_Recording_API) - Browser audio recording
- [zipstream-ng PyPI](https://pypi.org/project/zipstream-ng/) - Streaming ZIP generation
- [FastAPI file downloads guide](https://oneuptime.com/blog/post/2026-02-03-fastapi-file-downloads/view) - FileResponse and StreamingResponse patterns

### Tertiary (LOW confidence)
- [Qwen3-TTS-Openai-Fastapi GitHub](https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi) - Community OpenAI-compatible wrapper (useful reference but not official)

## Existing Code Reuse Map

| Existing Asset | Location | Reuse Strategy |
|----------------|----------|----------------|
| `tts.py` | `lecture_auto/pipeline/tts.py` | **REFACTOR**: Replace transformers with qwen-tts package, switch to Base model |
| `video.py` | `lecture_auto/pipeline/video.py` | **DIRECT REUSE**: `assemble_video()` called from TTS Celery task after audio complete |
| `vlm_tasks.py` | `lecture_auto/tasks/vlm_tasks.py` | **PATTERN CLONE**: Copy structure for `tts_tasks.py` (lazy model load, checkpointing, progress) |
| `progress.py` | `lecture_auto/tasks/progress.py` | **DIRECT REUSE**: `publish_progress(job_id, "tts", ...)` -- just change stage name |
| `celery_app.py` | `lecture_auto/tasks/celery_app.py` | **MODIFY**: Add `"tts.*": {"queue": "gpu_queue"}` to task_routes |
| `scripts.py` routes | `lecture_auto/api/routes/scripts.py` | **MODIFY**: Wire approve endpoint to trigger TTS task (replace "deferred" comment) |
| `jobs.py` routes | `lecture_auto/api/routes/jobs.py` | **PATTERN CLONE**: SSE progress pattern for TTS stage |
| `script.py` schemas | `lecture_auto/schemas/script.py` | **EXTEND**: `ScriptApproveResponse.tts_task_id` already exists, just populate it |
| `jobs.py` storage | `lecture_auto/storage/jobs.py` | **MINOR**: audio_dir and artifacts_dir already defined |
| `main.py` API | `lecture_auto/api/main.py` | **MODIFY**: Include new TTS and download routers |

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries verified, existing patterns well-established
- Architecture: HIGH - Follows exact patterns from Phase 2/3 (Celery task, routes, SSE)
- Model change (CustomVoice -> Base): HIGH - Verified via official docs and multiple sources
- Voice clone API: MEDIUM - `generate_voice_clone()` API confirmed by multiple sources but exact parameter behavior for `x_vector_only_mode` needs runtime validation
- Pitfalls: HIGH - GPU memory, MediaRecorder WAV format, model confusion all documented by community

**Research date:** 2026-03-30
**Valid until:** 2026-04-30 (stable domain, qwen-tts package unlikely to break)
