"""Integration tests for job routes (submit, status, SSE progress).

Tests use FastAPI TestClient with mocked Celery tasks and Redis dependencies.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lecture_auto.api.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# POST /jobs/{job_id}/vlm
# ---------------------------------------------------------------------------


def test_submit_vlm_job_success(tmp_path: Path):
    """Submit VLM job returns 200 with job_id, task_id, status=queued."""
    manifest_dir = tmp_path / "parsed"
    manifest_dir.mkdir(parents=True)
    manifest_file = manifest_dir / "manifest.json"
    manifest_file.write_text(json.dumps({"slides": []}))

    mock_task_result = MagicMock()
    mock_task_result.id = "task-123"

    with (
        patch(
            "lecture_auto.api.routes.jobs.JobPaths"
        ) as mock_jp_cls,
        patch(
            "lecture_auto.api.routes.jobs.process_slides_task"
        ) as mock_task,
    ):
        mock_jp = MagicMock()
        mock_jp.manifest_path = manifest_file
        mock_jp_cls.return_value = mock_jp
        mock_task.apply_async.return_value = mock_task_result

        resp = client.post("/jobs/job-001/vlm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "job-001"
    assert data["task_id"] == "task-123"
    assert data["status"] == "queued"


def test_submit_vlm_job_no_manifest(tmp_path: Path):
    """Submit VLM job returns 404 when manifest does not exist."""
    missing_manifest = tmp_path / "parsed" / "manifest.json"

    with patch(
        "lecture_auto.api.routes.jobs.JobPaths"
    ) as mock_jp_cls:
        mock_jp = MagicMock()
        mock_jp.manifest_path = missing_manifest
        mock_jp_cls.return_value = mock_jp

        resp = client.post("/jobs/job-missing/vlm")

    assert resp.status_code == 404
    assert "Manifest not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/status
# ---------------------------------------------------------------------------


def test_get_job_status_vlm_processing():
    """Status returns vlm_processing when progress shows processing."""
    progress = {
        "job_id": "job-001",
        "stage": "vlm",
        "current": 3,
        "total": 10,
        "percent": 30.0,
        "status": "processing",
    }
    with patch(
        "lecture_auto.api.routes.jobs.get_last_progress",
        return_value=progress,
    ):
        resp = client.get("/jobs/job-001/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "vlm_processing"
    assert data["progress"]["current"] == 3


def test_get_job_status_completed():
    """Status returns completed when all slides are done."""
    progress = {
        "job_id": "job-001",
        "stage": "vlm",
        "current": 10,
        "total": 10,
        "percent": 100.0,
        "status": "done",
    }
    with patch(
        "lecture_auto.api.routes.jobs.get_last_progress",
        return_value=progress,
    ):
        resp = client.get("/jobs/job-001/status")

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_get_job_status_failed():
    """Status returns failed when progress shows error."""
    progress = {
        "job_id": "job-001",
        "stage": "vlm",
        "current": 5,
        "total": 10,
        "percent": 50.0,
        "status": "error",
    }
    with patch(
        "lecture_auto.api.routes.jobs.get_last_progress",
        return_value=progress,
    ):
        resp = client.get("/jobs/job-001/status")

    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


def test_get_job_status_no_progress():
    """Status returns unknown when no progress data exists."""
    with patch(
        "lecture_auto.api.routes.jobs.get_last_progress",
        return_value=None,
    ):
        resp = client.get("/jobs/job-001/status")

    assert resp.status_code == 200
    assert resp.json()["status"] == "unknown"
    assert resp.json()["progress"] is None


def test_get_job_status_skipped():
    """Status returns vlm_processing when slides are being skipped (resumed)."""
    progress = {
        "job_id": "job-001",
        "stage": "vlm",
        "current": 2,
        "total": 10,
        "percent": 20.0,
        "status": "skipped",
    }
    with patch(
        "lecture_auto.api.routes.jobs.get_last_progress",
        return_value=progress,
    ):
        resp = client.get("/jobs/job-001/status")

    assert resp.status_code == 200
    assert resp.json()["status"] == "vlm_processing"


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/progress (SSE)
# ---------------------------------------------------------------------------


def test_stream_progress_endpoint_exists():
    """SSE progress endpoint returns text/event-stream content type."""
    # Mock get_last_progress to return completed state so stream ends immediately
    completed = {
        "job_id": "job-sse",
        "stage": "vlm",
        "current": 5,
        "total": 5,
        "percent": 100.0,
        "status": "done",
    }
    with patch(
        "lecture_auto.api.routes.jobs.get_last_progress",
        return_value=completed,
    ):
        resp = client.get("/jobs/job-sse/progress")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")


def test_stream_progress_initial_event():
    """SSE sends initial event with persisted progress for late joiners."""
    progress = {
        "job_id": "job-late",
        "stage": "vlm",
        "current": 5,
        "total": 5,
        "percent": 100.0,
        "status": "done",
    }
    with patch(
        "lecture_auto.api.routes.jobs.get_last_progress",
        return_value=progress,
    ):
        resp = client.get("/jobs/job-late/progress")

    body = resp.text
    assert "event: initial" in body
    assert "event: complete" in body


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def test_health_endpoint():
    """Health check returns ok status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.2.0"
