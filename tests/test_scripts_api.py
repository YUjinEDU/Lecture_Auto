"""Integration tests for script API routes.

Tests: list scripts, update script, regenerate, approve, progress SSE, slide PNG.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_manifest(slide_count: int = 3) -> dict:
    """Create a minimal manifest dict."""
    slides = []
    for i in range(slide_count):
        slides.append({
            "slide_index": i,
            "slide_number": i + 1,
            "png_path": f"slide_{i+1:03d}.png",
            "shapes": [{
                "shape_id": 1,
                "name": "Title",
                "z_order": 0,
                "left": 0, "top": 0, "width": 100, "height": 100,
                "content_source": "text",
                "has_text": True,
                "text_role": "title",
                "paragraphs": [{
                    "runs": [{"text": f"Slide {i+1}", "font": {"name": "Arial"}}],
                    "full_text": f"Slide {i+1}",
                }],
            }],
        })
    return {
        "job_id": "test-job",
        "file_sha256": "abc123",
        "lecture_name": "Test",
        "subject_name": "Test",
        "target_audience": "students",
        "target_minutes": 10,
        "style": {"density": "concise", "tone": "formal", "approach": "explanatory"},
        "slide_count": slide_count,
        "slides": slides,
    }


def _make_script(slide_index: int, slide_number: int, script_text: str = "Hello",
                 edited: bool = False, edited_at: str | None = None) -> dict:
    """Create a script JSON dict."""
    return {
        "slide_index": slide_index,
        "slide_number": slide_number,
        "target_seconds": 200.0,
        "script": script_text,
        "keywords": ["test"],
        "transition_to_next": "Next",
        "edited": edited,
        "edited_at": edited_at,
    }


@pytest.fixture
def job_dir(tmp_path):
    """Create a full job directory with manifest and scripts."""
    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir()
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()

    manifest = _make_manifest(3)
    (parsed_dir / "manifest.json").write_text(json.dumps(manifest))

    # Create script files for all 3 slides
    for i in range(3):
        script = _make_script(i, i + 1, f"Script for slide {i + 1}")
        (scripts_dir / f"script_{i+1:03d}.json").write_text(json.dumps(script))

    # Create a PNG for slide 1
    # Write a minimal 1x1 PNG (valid header)
    png_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
        b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
        b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    (rendered_dir / "slide_001.png").write_bytes(png_bytes)

    return tmp_path


@pytest.fixture
def mock_job_paths(job_dir):
    """Create a mock JobPaths pointing at job_dir."""
    mock = MagicMock()
    mock.manifest_path = job_dir / "parsed" / "manifest.json"
    mock.scripts_dir = job_dir / "scripts"
    mock.rendered_dir = job_dir / "rendered"
    return mock


@pytest.fixture
def client(mock_job_paths):
    """FastAPI TestClient with mocked JobPaths."""
    with patch("lecture_auto.api.routes.scripts.JobPaths", return_value=mock_job_paths):
        from lecture_auto.api.main import app
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/scripts
# ---------------------------------------------------------------------------

class TestListScripts:
    """Tests for GET /jobs/{job_id}/scripts."""

    def test_returns_sorted_scripts(self, client):
        """Returns list of ScriptResponse sorted by slide_number."""
        resp = client.get("/jobs/test-job/scripts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        assert data[0]["slide_number"] == 1
        assert data[1]["slide_number"] == 2
        assert data[2]["slide_number"] == 3

    def test_returns_empty_when_no_scripts(self, mock_job_paths, job_dir):
        """Returns empty list when no scripts exist."""
        # Clear scripts dir
        for f in (job_dir / "scripts").iterdir():
            f.unlink()

        with patch("lecture_auto.api.routes.scripts.JobPaths", return_value=mock_job_paths):
            from lecture_auto.api.main import app
            with TestClient(app) as c:
                resp = c.get("/jobs/test-job/scripts")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# PUT /jobs/{job_id}/scripts/{slide_number}
# ---------------------------------------------------------------------------

class TestUpdateScript:
    """Tests for PUT /jobs/{job_id}/scripts/{slide_number}."""

    def test_updates_script_sets_edited(self, client, job_dir):
        """Updates script text and sets edited=true with edited_at timestamp."""
        resp = client.put(
            "/jobs/test-job/scripts/1",
            json={"script": "Updated text"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["script"] == "Updated text"
        assert data["edited"] is True
        assert data["edited_at"] is not None

        # Verify file was updated on disk
        on_disk = json.loads((job_dir / "scripts" / "script_001.json").read_text())
        assert on_disk["script"] == "Updated text"
        assert on_disk["edited"] is True

    def test_returns_404_for_nonexistent(self, client):
        """Returns 404 for non-existent script."""
        resp = client.put(
            "/jobs/test-job/scripts/99",
            json={"script": "text"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /jobs/{job_id}/scripts/{slide_number}/regenerate
# ---------------------------------------------------------------------------

class TestRegenerateScript:
    """Tests for POST /jobs/{job_id}/scripts/{slide_number}/regenerate."""

    def test_returns_409_when_edited(self, client, job_dir):
        """Returns 409 when script is edited and force is not set."""
        # Mark slide 1 as edited
        script_path = job_dir / "scripts" / "script_001.json"
        data = json.loads(script_path.read_text())
        data["edited"] = True
        data["edited_at"] = "2026-03-30T12:00:00"
        script_path.write_text(json.dumps(data))

        resp = client.post("/jobs/test-job/scripts/1/regenerate")
        assert resp.status_code == 409

    def test_force_bypasses_edited_protection(self, client, job_dir):
        """force=true allows regeneration of edited scripts."""
        # Mark slide 1 as edited
        script_path = job_dir / "scripts" / "script_001.json"
        data = json.loads(script_path.read_text())
        data["edited"] = True
        data["edited_at"] = "2026-03-30T12:00:00"
        script_path.write_text(json.dumps(data))

        mock_task = MagicMock()
        mock_task.id = "task-123"

        with patch("lecture_auto.api.routes.scripts.regenerate_slide_task") as mock_regen:
            mock_regen.apply_async.return_value = mock_task
            resp = client.post("/jobs/test-job/scripts/1/regenerate?force=true")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "regenerating"

    def test_returns_404_for_nonexistent(self, client):
        """Returns 404 for non-existent script."""
        resp = client.post("/jobs/test-job/scripts/99/regenerate")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /jobs/{job_id}/scripts/approve
# ---------------------------------------------------------------------------

class TestApproveScripts:
    """Tests for POST /jobs/{job_id}/scripts/approve."""

    def test_returns_400_when_empty_script(self, client, job_dir):
        """Returns 400 when any slide has empty script."""
        # Make slide 2 empty
        script_path = job_dir / "scripts" / "script_002.json"
        data = json.loads(script_path.read_text())
        data["script"] = ""
        script_path.write_text(json.dumps(data))

        resp = client.post("/jobs/test-job/scripts/approve")
        assert resp.status_code == 400

    def test_approve_succeeds_with_all_scripts(self, client):
        """Returns 200 with status=approved when all scripts are non-empty."""
        resp = client.post("/jobs/test-job/scripts/approve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["total_slides"] == 3


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/scripts/progress
# ---------------------------------------------------------------------------

class TestScriptProgress:
    """Tests for GET /jobs/{job_id}/scripts/progress SSE endpoint."""

    def test_returns_sse_content_type(self, mock_job_paths):
        """Response content type is text/event-stream."""
        mock_pubsub = AsyncMock()

        async def empty_listen():
            return
            yield  # make it an async generator that ends immediately

        mock_pubsub.listen = empty_listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()

        mock_redis = MagicMock()  # pubsub() is sync, returns pubsub object
        mock_redis.pubsub.return_value = mock_pubsub

        async def override_redis():
            return mock_redis

        with patch("lecture_auto.api.routes.scripts.JobPaths", return_value=mock_job_paths):
            with patch("lecture_auto.api.routes.scripts.get_last_progress", return_value=None):
                from lecture_auto.api.main import app
                from lecture_auto.api.deps import get_async_redis

                app.dependency_overrides[get_async_redis] = override_redis
                try:
                    with TestClient(app) as c:
                        resp = c.get("/jobs/test-job/scripts/progress")
                        assert "text/event-stream" in resp.headers.get("content-type", "")
                finally:
                    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/slides/{slide_number}/png
# ---------------------------------------------------------------------------

class TestSlidePN:
    """Tests for GET /jobs/{job_id}/slides/{slide_number}/png."""

    def test_serves_existing_png(self, client):
        """Returns PNG for existing slide."""
        resp = client.get("/jobs/test-job/slides/1/png")
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "image/png"

    def test_returns_404_for_missing_png(self, client):
        """Returns 404 for non-existent slide PNG."""
        resp = client.get("/jobs/test-job/slides/99/png")
        assert resp.status_code == 404
