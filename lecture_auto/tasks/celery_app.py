"""Celery application instance with GPU-safe configuration.

Key settings:
    - worker_concurrency=1: One task at a time per GPU worker (prevent OOM).
    - task_acks_late=True: Acknowledge only after completion (crash-safe).
    - task_reject_on_worker_lost=True: Re-queue on unexpected worker death.
    - worker_prefetch_multiplier=1: Don't prefetch extra tasks.
"""

import os

from celery import Celery

celery_app = Celery(
    "lecture_auto",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=1,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    result_expires=86400,
)

celery_app.autodiscover_tasks(["lecture_auto.tasks"])
