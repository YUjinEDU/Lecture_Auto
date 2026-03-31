"""Script CRUD, regeneration, approval, SSE progress, and slide PNG endpoints.

Provides the backend API that the professor's review UI consumes:
- GET  /jobs/{job_id}/scripts              — List all slide scripts
- PUT  /jobs/{job_id}/scripts/{slide_num}  — Update a slide's script
- POST /jobs/{job_id}/scripts/{slide_num}/regenerate — Re-generate one slide
- POST /jobs/{job_id}/scripts/approve      — Approve all scripts for TTS
- GET  /jobs/{job_id}/scripts/progress     — SSE progress stream
- GET  /jobs/{job_id}/slides/{slide_num}/png — Serve rendered slide PNG
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from redis.asyncio import Redis as AsyncRedis
from sse_starlette.sse import EventSourceResponse

from lecture_auto.api.deps import get_async_redis
from lecture_auto.schemas.manifest import SlideManifest
from lecture_auto.schemas.script import (
    ScriptApproveResponse,
    ScriptResponse,
    ScriptUpdateRequest,
)
from lecture_auto.storage.jobs import JobPaths
from lecture_auto.storage.voice_store import get_voice_ref
from lecture_auto.tasks.progress import get_last_progress
from lecture_auto.tasks.script_tasks import regenerate_slide_task
from lecture_auto.tasks.tts_tasks import synthesize_job_task

router = APIRouter(prefix="/jobs", tags=["scripts"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_script(scripts_dir: Path, slide_number: int) -> dict | None:
    """Read a script JSON file, returning None if not found or invalid."""
    path = scripts_dir / f"script_{slide_number:03d}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _read_all_scripts(scripts_dir: Path) -> list[dict]:
    """Read all script_{NNN}.json files from a directory, sorted by slide_number."""
    if not scripts_dir.exists():
        return []
    scripts = []
    for path in sorted(scripts_dir.glob("script_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            scripts.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    scripts.sort(key=lambda s: s.get("slide_number", 0))
    return scripts


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via .tmp + os.rename."""
    tmp_path = str(path) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.rename(tmp_path, str(path))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{job_id}/scripts", response_model=list[ScriptResponse])
async def list_scripts(job_id: str):
    """List all slide scripts for a job, sorted by slide_number.

    Returns empty list if no scripts exist yet.
    """
    job_paths = JobPaths(job_id)
    scripts = _read_all_scripts(job_paths.scripts_dir)
    return scripts


@router.put("/{job_id}/scripts/{slide_number}", response_model=ScriptResponse)
async def update_script(job_id: str, slide_number: int, body: ScriptUpdateRequest):
    """Update a slide's script text. Sets edited=true and records timestamp.

    Uses immutable update pattern: creates new dict from existing + updates.
    Atomic write via .tmp + os.rename to prevent corruption.
    """
    job_paths = JobPaths(job_id)
    script_path = job_paths.scripts_dir / f"script_{slide_number:03d}.json"

    existing = _read_script(job_paths.scripts_dir, slide_number)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Script not found for slide {slide_number}")

    # Immutable update: create new dict
    updated = {
        **existing,
        "script": body.script,
        "edited": True,
        "edited_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.keywords is not None:
        updated = {**updated, "keywords": body.keywords}
    if body.transition_to_next is not None:
        updated = {**updated, "transition_to_next": body.transition_to_next}

    _atomic_write_json(script_path, updated)
    return updated


@router.post("/{job_id}/scripts/{slide_number}/regenerate")
async def regenerate_script(
    job_id: str,
    slide_number: int,
    force: bool = Query(False),
):
    """Regenerate a single slide's script via Claude.

    Returns 409 if the script was manually edited and force is not True.
    Returns 404 if the script file does not exist.
    """
    job_paths = JobPaths(job_id)
    existing = _read_script(job_paths.scripts_dir, slide_number)

    if existing is None:
        raise HTTPException(status_code=404, detail=f"Script not found for slide {slide_number}")

    if existing.get("edited") and not force:
        raise HTTPException(
            status_code=409,
            detail="Script was manually edited. Use ?force=true to overwrite.",
        )

    task = regenerate_slide_task.apply_async(
        args=[job_id, slide_number, force],
        queue="cpu_queue",
    )

    return {
        "job_id": job_id,
        "slide_number": slide_number,
        "task_id": task.id,
        "status": "regenerating",
    }


@router.post("/{job_id}/scripts/approve", response_model=ScriptApproveResponse)
async def approve_scripts(job_id: str):
    """Approve all scripts for TTS generation.

    Validates that all slides have non-empty scripts before approval.
    On approval, triggers TTS Celery task automatically (D-08).
    """
    job_paths = JobPaths(job_id)

    # Load manifest for expected slide count
    if not job_paths.manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manifest not found")
    manifest = SlideManifest.model_validate_json(
        job_paths.manifest_path.read_text(encoding="utf-8")
    )

    scripts = _read_all_scripts(job_paths.scripts_dir)

    # Validate completeness
    if len(scripts) < manifest.slide_count:
        raise HTTPException(
            status_code=400,
            detail=f"Only {len(scripts)}/{manifest.slide_count} scripts found. All slides must have scripts.",
        )

    # Validate non-empty
    empty_slides = [s["slide_number"] for s in scripts if not s.get("script", "").strip()]
    if empty_slides:
        raise HTTPException(
            status_code=400,
            detail=f"Slides {empty_slides} have empty scripts. All slides must have non-empty scripts before approval.",
        )

    # D-08: Trigger TTS Celery task on approval
    voice_ref = get_voice_ref("default")  # MVP: single professor
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


@router.get("/{job_id}/scripts/progress")
async def stream_script_progress(
    job_id: str,
    redis: AsyncRedis = Depends(get_async_redis),
):
    """SSE endpoint for real-time script generation progress.

    Follows the same pattern as jobs.py:stream_progress but filters
    for stage='script' events only. Sends ping every 15s for keep-alive.
    """

    async def event_generator():
        # Send initial state for late-joining clients
        initial = get_last_progress(job_id)
        if initial and initial.get("stage") == "script":
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
                    # Filter: only forward script-stage events
                    if data.get("stage") != "script":
                        continue
                    yield {
                        "event": "progress",
                        "data": json.dumps(data),
                    }
                    if (
                        data.get("stage") == "script"
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


@router.get("/{job_id}/slides/{slide_number}/png")
async def serve_slide_png(job_id: str, slide_number: int):
    """Serve rendered slide PNG image.

    Returns FileResponse with image/png content type.
    404 if the file does not exist.
    """
    job_paths = JobPaths(job_id)
    png_path = job_paths.rendered_dir / f"slide_{slide_number:03d}.png"

    if not png_path.exists():
        raise HTTPException(status_code=404, detail=f"Slide PNG not found: slide {slide_number}")

    return FileResponse(str(png_path), media_type="image/png")
