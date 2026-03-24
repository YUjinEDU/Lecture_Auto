"""Job submission, status, and SSE progress endpoints.

Exposes the Celery-backed VLM pipeline via REST API:
- POST /jobs/{job_id}/vlm - Submit VLM processing job
- GET /jobs/{job_id}/status - Poll current job status
- GET /jobs/{job_id}/progress - Stream real-time SSE progress
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis as AsyncRedis
from sse_starlette.sse import EventSourceResponse

from lecture_auto.api.deps import get_async_redis
from lecture_auto.storage.jobs import JobPaths
from lecture_auto.tasks.progress import get_last_progress
from lecture_auto.tasks.vlm_tasks import process_slides_task

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/{job_id}/vlm")
async def submit_vlm_job(job_id: str):
    """Submit VLM processing job for a parsed PPTX.

    Requires manifest.json to exist at job's parsed directory.
    Returns immediately with task_id for status tracking.
    """
    job_paths = JobPaths(job_id)
    if not job_paths.manifest_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Manifest not found for job {job_id}. Run parse+render first.",
        )

    task = process_slides_task.apply_async(
        args=[job_id],
        queue="gpu_queue",
    )

    return {"job_id": job_id, "task_id": task.id, "status": "queued"}


@router.get("/{job_id}/status")
async def get_job_status(job_id: str):
    """Get current job status derived from last progress event.

    Returns Celery-compatible status string based on persisted progress.
    Also includes the raw last progress event if available.
    """
    last = get_last_progress(job_id)
    status = "unknown"
    if last:
        if last.get("status") == "done" and last.get("current") == last.get("total"):
            status = "completed"
        elif last.get("status") == "error":
            status = "failed"
        elif last.get("status") in ("processing", "skipped"):
            status = "vlm_processing"
        else:
            status = "queued"
    return {"job_id": job_id, "status": status, "progress": last}


@router.get("/{job_id}/progress")
async def stream_progress(
    job_id: str,
    redis: AsyncRedis = Depends(get_async_redis),
):
    """SSE endpoint for real-time job progress.

    Streams per-slide progress events from Redis pub/sub.
    Sends initial state from persisted last_progress for late joiners.
    Sends keep-alive comments every 15s to prevent proxy timeouts.
    Ends stream on "complete" event (all slides done).
    """

    async def event_generator():
        # Send initial state for late-joining clients
        initial = get_last_progress(job_id)
        if initial:
            yield {
                "event": "initial",
                "data": json.dumps(initial),
            }
            # If already complete, end immediately
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
                    yield {
                        "event": "progress",
                        "data": json.dumps(data),
                    }
                    if (
                        data.get("stage") == "vlm"
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
