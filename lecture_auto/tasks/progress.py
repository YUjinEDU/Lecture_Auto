"""Redis pub/sub progress publisher for per-slide pipeline events.

Publishes to channel ``job:{job_id}:progress`` and persists the last event
under key ``job:{job_id}:last_progress`` (TTL 24h) so late-joining SSE
clients can catch up.
"""

import json
import os

import redis as redis_lib

_redis_client: redis_lib.Redis | None = None


def _get_redis() -> redis_lib.Redis:
    """Lazy-initialise a Redis connection for the progress DB."""
    global _redis_client
    if _redis_client is None:
        db = int(os.environ.get("REDIS_PROGRESS_DB", "2"))
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        # Replace db number in URL
        base = url.rsplit("/", 1)[0]
        _redis_client = redis_lib.Redis.from_url(f"{base}/{db}")
    return _redis_client


def publish_progress(
    job_id: str, stage: str, current: int, total: int, status: str
) -> None:
    """Publish a progress event to Redis pub/sub and persist last state."""
    event = {
        "job_id": job_id,
        "stage": stage,
        "current": current,
        "total": total,
        "percent": round((current / total) * 100, 1) if total > 0 else 0,
        "status": status,
    }
    r = _get_redis()
    channel = f"job:{job_id}:progress"
    r.publish(channel, json.dumps(event))
    # Also store last progress for late-joining clients
    r.set(f"job:{job_id}:last_progress", json.dumps(event), ex=86400)


def get_last_progress(job_id: str) -> dict | None:
    """Retrieve the last progress event for a job (if any)."""
    r = _get_redis()
    data = r.get(f"job:{job_id}:last_progress")
    if data:
        return json.loads(data)
    return None


def reset_redis_client() -> None:
    """Reset the cached Redis client (for testing)."""
    global _redis_client
    _redis_client = None
