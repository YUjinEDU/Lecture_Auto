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

from lecture_auto.tasks.progress import publish_progress

logger = logging.getLogger(__name__)

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
    from lecture_auto.pipeline.tts import merge_audio, synthesize_slide
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
    model = _get_tts()
    ref_path = Path(voice_ref_path) if voice_ref_path else None

    for i, slide in enumerate(slides):
        wav_path = job_paths.audio_dir / f"audio_{slide.slide_number:03d}.wav"

        # RESUMABILITY: skip already-completed slides
        if wav_path.exists() and wav_path.stat().st_size > 0:
            skipped += 1
            publish_progress(job_id, "tts", i + 1, total, "skipped")
            continue

        publish_progress(job_id, "tts", i + 1, total, "processing")

        # Load script text from script_{NNN}.json
        script_path = job_paths.scripts_dir / f"script_{slide.slide_number:03d}.json"
        if not script_path.exists():
            logger.error("No script for slide %d", slide.slide_number)
            publish_progress(job_id, "tts", i + 1, total, "error")
            continue

        script_data = json.loads(script_path.read_text(encoding="utf-8"))
        text = script_data.get("script", "")

        try:
            synthesize_slide(
                model, text, wav_path,
                voice_ref_path=ref_path,
            )
            publish_progress(job_id, "tts", i + 1, total, "done")
        except Exception as exc:
            logger.error("TTS failed on slide %d: %s", slide.slide_number, exc)
            publish_progress(job_id, "tts", i + 1, total, "error")
            raise self.retry(exc=exc, countdown=30)

    # Merge all per-slide WAVs into lecture_merged.wav
    merged_path = job_paths.audio_dir / "lecture_merged.wav"
    merge_audio(job_paths.audio_dir, merged_path)
    logger.info("Merged audio: %s", merged_path)

    # Assemble MP4 video
    png_paths = sorted(job_paths.rendered_dir.glob("slide_*.png"))
    wav_paths_list = sorted(job_paths.audio_dir.glob("audio_*.wav"))
    # Exclude lecture_merged.wav from video assembly
    wav_paths_list = [w for w in wav_paths_list if w.name != "lecture_merged.wav"]
    video_dir = job_paths.artifacts_dir / "video_clips"
    output_video = job_paths.artifacts_dir / f"lecture_{job_id}.mp4"
    assemble_video(png_paths, wav_paths_list, video_dir, output_video, job_id)
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
    from lecture_auto.pipeline.tts import synthesize_slide
    from lecture_auto.storage.jobs import JobPaths

    job_paths = JobPaths(job_id)
    script_path = job_paths.scripts_dir / f"script_{slide_number:03d}.json"
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: script_{slide_number:03d}.json")

    script_data = json.loads(script_path.read_text(encoding="utf-8"))
    text = script_data.get("script", "")

    wav_path = job_paths.audio_dir / f"audio_{slide_number:03d}.wav"
    model = _get_tts()
    ref_path = Path(voice_ref_path) if voice_ref_path else None

    synthesize_slide(model, text, wav_path, voice_ref_path=ref_path)

    return {"job_id": job_id, "slide_number": slide_number, "status": "regenerated"}
