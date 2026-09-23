"""Resumable TTS Celery task with file-based checkpointing.

The task processes each slide individually and skips slides that already
have a valid audio_{NNN}.wav file on disk. This makes the task
safely resumable after crashes or worker restarts.

Exports:
    synthesize_job_task         -- Full-job TTS for all approved slides
    regenerate_slide_tts_task   -- Single-slide re-TTS after script edit
"""

import json
import logging
from pathlib import Path

from celery import shared_task

from lecture_auto.pipeline.cache import content_hash, is_cache_valid, write_cache_hash
from lecture_auto.tasks.progress import publish_progress

logger = logging.getLogger(__name__)

_tts_engine = None


def _get_tts():
    """Lazy-load the configured TTS engine (singleton per worker process)."""
    global _tts_engine
    if _tts_engine is None:
        from lecture_auto.tts import get_tts_engine

        _tts_engine = get_tts_engine()
    return _tts_engine


def _api_tts_cache_key(engine, script_text: str, ref_bytes: bytes) -> str:
    """TTS cache key for this (API/Celery) resume path -- S6-b/F3.

    Mirrors ``scripts/batch_generate_lectures.py``'s ``_tts_cache_key`` in
    spirit (one function, used by both the resume-skip check and the write
    after synthesis, so they can never drift apart) but is a separate
    function: this driver goes through the pluggable ``TTSEngine``
    (``lecture_auto/tts/``, default ``QwenTTSEngine``), not
    ``pipeline/raon_tts.py`` directly, so it has no ``TTS_MODEL_ID``/
    ``TTS_SEEDS``/``TTS_SYNTH_VERSION`` constants to hash. Engine identity is
    the class name + its resolved model path (``QwenTTSEngine._model_path``,
    itself the ``TTS_MODEL`` env var or a default) -- ``TTSEngine`` has no
    public config accessor, so this reads a private attribute; a future
    engine that wants a cleaner contract should add one to ``TTSEngine``
    instead of every caller reaching in like this.

    NOTE: no on-disk WAV from before this change has a ``.hash`` sidecar (F3
    is new), so the first resume after this ships re-synthesizes every slide
    once -- after that, unchanged slides skip normally.
    """
    model_id = f"{type(engine).__name__}:{getattr(engine, '_model_path', '')}"
    return content_hash(script_text, ref_bytes, model_id)


@shared_task(
    bind=True,
    name="tts.synthesize",
    max_retries=2,
    queue="gpu_queue",
    acks_late=True,
)
def synthesize_job_task(self, job_id: str, voice_ref_path: str | None = None) -> dict:
    """TTS for all approved slides with per-slide checkpointing.

    For each slide:
        1. Check if audio_{NNN}.wav exists -> skip (publish 'skipped').
        2. Otherwise -> load script text, synthesize_slide(), publish 'done'.
        3. On error -> publish 'error', retry with backoff.
    After all slides: merge audio -> assemble video -> publish final 'done'.

    Parameters
    ----------
    job_id:
        Unique job identifier.
    voice_ref_path:
        Optional path to a voice reference WAV for voice cloning.

    Returns
    -------
    dict
        ``{"job_id": ..., "total": ..., "skipped": ...}``
    """
    from lecture_auto.pipeline.tts import merge_audio
    from lecture_auto.pipeline.video import assemble_video
    from lecture_auto.schemas.manifest import SlideManifest
    from lecture_auto.storage.jobs import JobPaths

    job_paths = JobPaths(job_id)
    manifest = SlideManifest.model_validate_json(
        job_paths.manifest_path.read_text(encoding="utf-8")
    )
    slides = manifest.slides
    total = len(slides)
    skipped = 0
    engine = _get_tts()
    ref_path = Path(voice_ref_path) if voice_ref_path else None
    ref_bytes = ref_path.read_bytes() if ref_path and ref_path.exists() else b""

    for i, slide in enumerate(slides):
        wav_path = job_paths.audio_dir / f"audio_{slide.slide_number:03d}.wav"

        # Load script text from script_{NNN}.json. Loaded before the resume
        # check (F3/S6-b): a missing script fails loudly instead of being
        # silently skipped, and the cache key below needs the current text
        # anyway, so there is nothing left for a WAV-existence-only check to
        # decide on its own.
        script_path = job_paths.scripts_dir / f"script_{slide.slide_number:03d}.json"
        if not script_path.exists():
            logger.error("No script for slide %d", slide.slide_number)
            publish_progress(job_id, "tts", i + 1, total, "error")
            raise FileNotFoundError(
                f"No script for slide {slide.slide_number} (job {job_id}, expected {script_path})"
            )

        script_data = json.loads(script_path.read_text(encoding="utf-8"))
        text = script_data.get("script", "")
        cache_key = _api_tts_cache_key(engine, text, ref_bytes)

        # RESUMABILITY (F3): valid only when the *current* script + reference
        # voice + engine config hash to the sidecar written after the last
        # successful synth -- not merely "a WAV file exists" (which used to
        # keep serving audio for a script that had since been edited).
        if is_cache_valid(wav_path, cache_key):
            skipped += 1
            publish_progress(job_id, "tts", i + 1, total, "skipped")
            continue

        publish_progress(job_id, "tts", i + 1, total, "processing")
        try:
            engine.synthesize_slide(
                text, wav_path,
                voice_ref_path=ref_path,
            )
            write_cache_hash(wav_path, cache_key)
            publish_progress(job_id, "tts", i + 1, total, "done")
        except Exception as exc:
            logger.error("TTS failed on slide %d: %s", slide.slide_number, exc)
            publish_progress(job_id, "tts", i + 1, total, "error")
            raise self.retry(exc=exc, countdown=30)

    # Merge all per-slide WAVs into lecture_merged.wav -- an explicit,
    # slide-ordered list (F3/S1's fix, applied here too), not a directory
    # glob that would pick up an unrelated *.wav sitting in the same folder.
    wav_paths_list = [
        job_paths.audio_dir / f"audio_{slide.slide_number:03d}.wav" for slide in slides
    ]
    merged_path = job_paths.audio_dir / "lecture_merged.wav"
    merge_audio(wav_paths_list, merged_path)
    logger.info("Merged audio: %s", merged_path)

    # Assemble MP4 video
    png_paths = sorted(job_paths.rendered_dir.glob("slide_*.png"))
    video_dir = job_paths.artifacts_dir / "video_clips"
    output_video = job_paths.artifacts_dir / f"lecture_{job_id}.mp4"
    assemble_video(png_paths, wav_paths_list, video_dir, output_video, job_id, strict=True)
    logger.info("Video assembled: %s", output_video)

    # Final completion progress
    publish_progress(job_id, "tts", total, total, "done")

    logger.info("TTS complete: %d processed, %d skipped", total - skipped, skipped)
    return {"job_id": job_id, "total": total, "skipped": skipped}


@shared_task(
    bind=True,
    name="tts.regenerate_slide",
    max_retries=1,
    queue="gpu_queue",
    acks_late=True,
)
def regenerate_slide_tts_task(
    self, job_id: str, slide_number: int, voice_ref_path: str | None = None
) -> dict:
    """Re-generate TTS for a single slide after script edit.

    Parameters
    ----------
    job_id:
        Unique job identifier.
    slide_number:
        1-based slide number to re-synthesize.
    voice_ref_path:
        Optional path to a voice reference WAV for voice cloning.

    Returns
    -------
    dict
        ``{"job_id": ..., "slide_number": ..., "status": "regenerated"}``

    Raises
    ------
    FileNotFoundError
        If the script file for the given slide does not exist.
    """
    from lecture_auto.storage.jobs import JobPaths

    job_paths = JobPaths(job_id)
    script_path = job_paths.scripts_dir / f"script_{slide_number:03d}.json"
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: script_{slide_number:03d}.json")

    script_data = json.loads(script_path.read_text(encoding="utf-8"))
    text = script_data.get("script", "")

    wav_path = job_paths.audio_dir / f"audio_{slide_number:03d}.wav"
    engine = _get_tts()
    ref_path = Path(voice_ref_path) if voice_ref_path else None
    ref_bytes = ref_path.read_bytes() if ref_path and ref_path.exists() else b""

    engine.synthesize_slide(text, wav_path, voice_ref_path=ref_path)
    # F3: keep this path's cache hash current too, or a later
    # synthesize_job_task run (which now checks the hash, not just WAV
    # existence) would treat this single-slide regeneration as stale and
    # redo the work.
    write_cache_hash(wav_path, _api_tts_cache_key(engine, text, ref_bytes))

    return {"job_id": job_id, "slide_number": slide_number, "status": "regenerated"}
