"""Resumable script generation Celery task with file-based checkpointing.

The task processes each slide individually via `call_claude()` and skips
slides that already have a valid script_{NNN}.json file on disk.  This makes
the task safely resumable after crashes or worker restarts.

Uses cpu_queue since Claude CLI is CPU-bound (subprocess), not GPU.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from celery import shared_task

from lecture_auto.tasks.progress import publish_progress

logger = logging.getLogger(__name__)


def _load_vlm_note(vlm_dir: Path, slide_number: int) -> dict:
    """Load a VLM note JSON for a given slide number."""
    note_path = vlm_dir / f"vlm_note_{slide_number:03d}.json"
    if note_path.exists():
        return json.loads(note_path.read_text(encoding="utf-8"))
    return {}


def _is_valid_script(path: Path) -> bool:
    """Check if a script JSON file exists and has a non-empty 'script' key."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("script"))
    except (json.JSONDecodeError, KeyError, OSError):
        return False


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via .tmp + os.rename to prevent corrupt checkpoints."""
    tmp_path = str(path) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.rename(tmp_path, str(path))


def _read_script_text(scripts_dir: Path, slide_number: int) -> str | None:
    """Read the script text from an existing script file, or None."""
    path = scripts_dir / f"script_{slide_number:03d}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("script")
    except (json.JSONDecodeError, OSError):
        return None


@shared_task(
    bind=True,
    name="script.generate",
    queue="cpu_queue",
    max_retries=2,
    acks_late=True,
)
def generate_scripts_task(self, job_id: str) -> dict:
    """Generate lecture scripts for all slides with per-slide checkpointing.

    For each slide:
        1. Check if script_{NNN}.json already exists with valid 'script' key.
        2. If valid -> skip (publish 'skipped' progress).
        3. Otherwise -> call Claude, parse JSON, atomic write, publish 'done'.
        4. On error -> publish 'error' progress, retry with backoff.

    Args:
        job_id: Unique job identifier.

    Returns:
        Dict with job_id, total slides, and count of skipped slides.
    """
    from lecture_auto.pipeline.script_gen import (
        build_script_prompt,
        call_claude,
        _parse_script_json,
    )
    from lecture_auto.schemas.manifest import SlideManifest
    from lecture_auto.storage.jobs import JobPaths

    job_paths = JobPaths(job_id)
    manifest = SlideManifest.model_validate_json(
        job_paths.manifest_path.read_text(encoding="utf-8")
    )
    slides = manifest.slides
    total = len(slides)
    skipped = 0

    target_seconds = (manifest.target_minutes * 60) / manifest.slide_count

    for i, slide in enumerate(slides):
        script_path = job_paths.scripts_dir / f"script_{slide.slide_number:03d}.json"

        # RESUMABILITY: skip already-completed slides
        if _is_valid_script(script_path):
            skipped += 1
            publish_progress(job_id, "script", i + 1, total, "skipped")
            continue

        publish_progress(job_id, "script", i + 1, total, "processing")

        try:
            # Load context for prompt building
            vlm_note = _load_vlm_note(job_paths.vlm_dir, slide.slide_number)
            prev_slide = slides[i - 1] if i > 0 else None
            next_slide = slides[i + 1] if i < len(slides) - 1 else None
            prev_script_text = _read_script_text(
                job_paths.scripts_dir,
                slides[i - 1].slide_number,
            ) if i > 0 else None

            prompt = build_script_prompt(
                slide=slide,
                vlm_note=vlm_note,
                style=manifest.style,
                target_seconds=target_seconds,
                prev_slide=prev_slide,
                next_slide=next_slide,
                prev_script=prev_script_text,
            )

            # Call Claude subprocess (async -> sync bridge)
            raw = asyncio.run(call_claude(prompt))
            data = _parse_script_json(raw, slide.slide_index, slide.slide_number)

            # Add edit tracking fields
            data["edited"] = False
            data["edited_at"] = None

            # Atomic write: .tmp + os.rename
            _atomic_write_json(script_path, data)

            publish_progress(job_id, "script", i + 1, total, "done")

        except Exception as exc:
            logger.error(
                "Script generation failed on slide %d: %s",
                slide.slide_number,
                exc,
            )
            publish_progress(job_id, "script", i + 1, total, "error")
            raise self.retry(exc=exc, countdown=60)

    # Final completion progress
    publish_progress(job_id, "script", total, total, "done")
    logger.info(
        "Script generation complete: %d processed, %d skipped",
        total - skipped,
        skipped,
    )
    return {"job_id": job_id, "total": total, "skipped": skipped}


@shared_task(
    bind=True,
    name="script.regenerate_slide",
    queue="cpu_queue",
    max_retries=1,
    acks_late=True,
)
def regenerate_slide_task(
    self, job_id: str, slide_number: int, force: bool = False
) -> dict:
    """Regenerate a single slide's script via Claude.

    Args:
        job_id: Unique job identifier.
        slide_number: 1-based slide number to regenerate.
        force: If True, overwrite even if the script was manually edited.

    Returns:
        Dict with job_id, slide_number, and status.

    Raises:
        ValueError: If the script was edited and force is False.
        FileNotFoundError: If the script file does not exist.
    """
    from lecture_auto.pipeline.script_gen import (
        build_script_prompt,
        call_claude,
        _parse_script_json,
    )
    from lecture_auto.schemas.manifest import SlideManifest
    from lecture_auto.storage.jobs import JobPaths

    job_paths = JobPaths(job_id)
    script_path = job_paths.scripts_dir / f"script_{slide_number:03d}.json"

    if not script_path.exists():
        raise FileNotFoundError(
            f"Script file not found: script_{slide_number:03d}.json"
        )

    existing = json.loads(script_path.read_text(encoding="utf-8"))

    # Respect edited flag
    if existing.get("edited") and not force:
        raise ValueError(
            "Script was manually edited. Use force=True to overwrite."
        )

    # Load manifest and find the slide
    manifest = SlideManifest.model_validate_json(
        job_paths.manifest_path.read_text(encoding="utf-8")
    )
    slides = manifest.slides
    target_seconds = (manifest.target_minutes * 60) / manifest.slide_count

    slide_idx = None
    for idx, s in enumerate(slides):
        if s.slide_number == slide_number:
            slide_idx = idx
            break

    if slide_idx is None:
        raise ValueError(f"Slide number {slide_number} not found in manifest")

    slide = slides[slide_idx]
    vlm_note = _load_vlm_note(job_paths.vlm_dir, slide_number)
    prev_slide = slides[slide_idx - 1] if slide_idx > 0 else None
    next_slide = slides[slide_idx + 1] if slide_idx < len(slides) - 1 else None
    prev_script_text = _read_script_text(
        job_paths.scripts_dir,
        slides[slide_idx - 1].slide_number,
    ) if slide_idx > 0 else None

    prompt = build_script_prompt(
        slide=slide,
        vlm_note=vlm_note,
        style=manifest.style,
        target_seconds=target_seconds,
        prev_slide=prev_slide,
        next_slide=next_slide,
        prev_script=prev_script_text,
    )

    raw = asyncio.run(call_claude(prompt))
    data = _parse_script_json(raw, slide.slide_index, slide.slide_number)
    data["edited"] = False
    data["edited_at"] = None

    _atomic_write_json(script_path, data)

    return {"job_id": job_id, "slide_number": slide_number, "status": "regenerated"}
