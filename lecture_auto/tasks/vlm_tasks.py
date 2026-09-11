"""Resumable VLM Celery task with file-based checkpointing.

The task processes each slide individually and skips slides that already
have a valid vlm_note_{NNN}.json file on disk.  This makes the task
safely resumable after crashes or worker restarts.
"""

import json
import logging
from pathlib import Path

from celery import shared_task

from lecture_auto.tasks.progress import publish_progress

logger = logging.getLogger(__name__)

_llm_client = None


def _get_vlm():
    """Lazy-init the LLM client (singleton per worker process)."""
    global _llm_client
    if _llm_client is None:
        from lecture_auto.llm import get_llm_client

        _llm_client = get_llm_client()
    return _llm_client


@shared_task(
    bind=True,
    name="vlm.process_slides",
    max_retries=2,
    queue="gpu_queue",
    acks_late=True,
)
def process_slides_task(self, job_id: str) -> dict:
    """Process all slides through VLM with resumability.

    For each slide:
        1. Check if vlm_note_{NNN}.json already exists with required fields.
        2. If valid -> skip (publish 'skipped' progress).
        3. Otherwise -> run generate_single_note, publish 'done' progress.
        4. On error -> publish 'error' progress, retry with backoff.

    Args:
        job_id: Unique job identifier.

    Returns:
        Dict with job_id, total slides, and count of skipped slides.
    """
    from lecture_auto.pipeline.vlm import generate_single_note
    from lecture_auto.schemas.manifest import SlideManifest
    from lecture_auto.storage.jobs import JobPaths

    job_paths = JobPaths(job_id)
    manifest = SlideManifest.model_validate_json(
        job_paths.manifest_path.read_text()
    )
    slides = manifest.slides
    total = len(slides)
    skipped = 0

    client = _get_vlm()

    for i, slide in enumerate(slides):
        note_path = job_paths.vlm_dir / f"vlm_note_{slide.slide_number:03d}.json"

        # RESUMABILITY: skip already-completed slides
        if note_path.exists():
            try:
                existing = json.loads(note_path.read_text())
                required = ("visual_summary", "key_elements", "teaching_points")
                if all(k in existing for k in required):
                    skipped += 1
                    publish_progress(job_id, "vlm", i + 1, total, "skipped")
                    continue
            except (json.JSONDecodeError, KeyError):
                pass  # Invalid file, re-process

        publish_progress(job_id, "vlm", i + 1, total, "processing")
        try:
            generate_single_note(
                client, slide, job_paths.rendered_dir, job_paths.vlm_dir
            )
            publish_progress(job_id, "vlm", i + 1, total, "done")
        except Exception as exc:
            logger.error("VLM failed on slide %d: %s", slide.slide_number, exc)
            publish_progress(job_id, "vlm", i + 1, total, "error")
            raise self.retry(exc=exc, countdown=30)

    logger.info("VLM complete: %d processed, %d skipped", total - skipped, skipped)
    return {"job_id": job_id, "total": total, "skipped": skipped}
