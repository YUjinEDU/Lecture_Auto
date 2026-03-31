"""TTS voice registration, audio serving, re-TTS, and SSE progress endpoints.

Provides the backend API for TTS operations:
- POST /jobs/voice/register         -- Register a voice reference (WAV or WebM)
- GET  /jobs/voice/status            -- Check voice registration status
- GET  /jobs/{job_id}/audio/{slide_number}/wav -- Serve individual slide WAV
- POST /jobs/{job_id}/tts/{slide_number}/regenerate -- Re-TTS a single slide
- GET  /jobs/{job_id}/tts/progress   -- SSE progress stream for TTS
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from redis.asyncio import Redis as AsyncRedis
from sse_starlette.sse import EventSourceResponse

from lecture_auto.api.deps import get_async_redis
from lecture_auto.schemas.tts import (
    TTSRegenerateResponse,
    VoiceRegisterResponse,
)
from lecture_auto.storage.jobs import JobPaths
from lecture_auto.storage.voice_store import (
    convert_webm_to_wav,
    get_voice_ref,
    save_voice_ref,
)
from lecture_auto.tasks.progress import get_last_progress
from lecture_auto.tasks.tts_tasks import regenerate_slide_tts_task

router = APIRouter(prefix="/jobs", tags=["tts"])


# ---------------------------------------------------------------------------
# Voice registration
# ---------------------------------------------------------------------------


@router.post("/voice/register", response_model=VoiceRegisterResponse)
async def register_voice(
    audio_file: UploadFile,
    professor_id: str = "default",
):
    """Register a voice reference file for TTS voice cloning.

    Accepts WAV or WebM audio. WebM is automatically converted to WAV
    via ffmpeg (16-bit PCM, 24 kHz, mono).

    Parameters
    ----------
    audio_file:
        Uploaded audio file (WAV or WebM).
    professor_id:
        Professor identifier. Defaults to ``"default"`` for MVP.
    """
    raw_bytes = await audio_file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    content_type = audio_file.content_type or ""
    if "webm" in content_type:
        try:
            wav_bytes = convert_webm_to_wav(raw_bytes)
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    else:
        wav_bytes = raw_bytes

    ref_path = save_voice_ref(professor_id, wav_bytes)
    return VoiceRegisterResponse(
        professor_id=professor_id,
        voice_ref_path=str(ref_path),
        status="registered",
    )


@router.get("/voice/status")
async def voice_status(professor_id: str = Query("default")):
    """Check whether a voice reference is registered for a professor.

    Parameters
    ----------
    professor_id:
        Professor identifier. Defaults to ``"default"``.
    """
    ref_path = get_voice_ref(professor_id)
    return {"professor_id": professor_id, "registered": ref_path is not None}


# ---------------------------------------------------------------------------
# Audio serving
# ---------------------------------------------------------------------------


@router.get("/{job_id}/audio/{slide_number}/wav")
async def serve_slide_wav(job_id: str, slide_number: int):
    """Serve an individual slide's WAV audio file for preview playback.

    Returns 404 if the WAV file does not exist (TTS not yet run for this slide).
    """
    job_paths = JobPaths(job_id)
    wav_path = job_paths.audio_dir / f"audio_{slide_number:03d}.wav"

    if not wav_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Audio not found for slide {slide_number}",
        )

    return FileResponse(str(wav_path), media_type="audio/wav")


# ---------------------------------------------------------------------------
# Re-TTS
# ---------------------------------------------------------------------------


@router.post(
    "/{job_id}/tts/{slide_number}/regenerate",
    response_model=TTSRegenerateResponse,
)
async def regenerate_slide_tts(job_id: str, slide_number: int):
    """Re-generate TTS audio for a single slide after script edit.

    Dispatches a Celery task to the GPU queue and returns immediately.
    """
    voice_ref = get_voice_ref("default")
    task = regenerate_slide_tts_task.apply_async(
        args=[job_id, slide_number, str(voice_ref) if voice_ref else None],
        queue="gpu_queue",
    )
    return TTSRegenerateResponse(
        job_id=job_id,
        slide_number=slide_number,
        task_id=task.id,
        status="regenerating",
    )


# ---------------------------------------------------------------------------
# SSE Progress
# ---------------------------------------------------------------------------


@router.get("/{job_id}/tts/progress")
async def stream_tts_progress(
    job_id: str,
    redis: AsyncRedis = Depends(get_async_redis),
):
    """SSE endpoint for real-time TTS generation progress.

    Follows the same pattern as scripts.py:stream_script_progress but filters
    for ``stage == "tts"`` events. Sends ping every 15 s for keep-alive.
    """

    async def event_generator():
        # Send initial state for late-joining clients
        initial = get_last_progress(job_id)
        if initial and initial.get("stage") == "tts":
            yield {
                "event": "initial",
                "data": json.dumps(initial),
            }
            if (
                initial.get("status") == "done"
                and initial.get("current") == initial.get("total")
            ):
                yield {"event": "complete", "data": json.dumps({"job_id": job_id})}
                return

        pubsub = redis.pubsub()
        await pubsub.subscribe(f"job:{job_id}:progress")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    # Filter: only forward tts-stage events
                    if data.get("stage") != "tts":
                        continue
                    yield {
                        "event": "progress",
                        "data": json.dumps(data),
                    }
                    if (
                        data.get("stage") == "tts"
                        and data.get("status") == "done"
                        and data.get("current") == data.get("total")
                    ):
                        yield {
                            "event": "complete",
                            "data": json.dumps({"job_id": job_id}),
                        }
                        break
        finally:
            await pubsub.unsubscribe(f"job:{job_id}:progress")

    return EventSourceResponse(event_generator(), ping=15)
