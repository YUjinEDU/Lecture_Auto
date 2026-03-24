"""Celery task definitions for lecture automation pipeline."""

from lecture_auto.tasks.celery_app import celery_app

__all__ = ["celery_app"]
