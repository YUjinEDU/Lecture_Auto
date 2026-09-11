"""Tests for script Celery task with file-based checkpointing and progress."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lecture_auto.schemas.script import (
    ScriptUpdateRequest,
    ScriptResponse,
    ScriptApproveResponse,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestScriptSchemas:
    """Validate Pydantic models for script CRUD."""

    def test_script_update_request_requires_script(self):
        """ScriptUpdateRequest requires 'script' field as string."""
        req = ScriptUpdateRequest(script="Hello world")
        assert req.script == "Hello world"
        assert req.keywords is None
        assert req.transition_to_next is None

    def test_script_update_request_rejects_missing_script(self):
        """ScriptUpdateRequest fails without 'script' field."""
        with pytest.raises(Exception):
            ScriptUpdateRequest()

    def test_script_response_has_edited_fields(self):
        """ScriptResponse includes edited and edited_at fields."""
        resp = ScriptResponse(
            slide_index=0,
            slide_number=1,
            target_seconds=30.0,
            script="test",
            keywords=["a"],
            transition_to_next="next",
        )
        assert resp.edited is False
        assert resp.edited_at is None

    def test_script_response_edited_true(self):
        """ScriptResponse can represent an edited script."""
        resp = ScriptResponse(
            slide_index=0,
            slide_number=1,
            target_seconds=30.0,
            script="edited text",
            keywords=["b"],
            transition_to_next="next",
            edited=True,
            edited_at="2026-03-30T12:00:00",
        )
        assert resp.edited is True
        assert resp.edited_at == "2026-03-30T12:00:00"

    def test_script_approve_response(self):
        """ScriptApproveResponse includes expected fields."""
        resp = ScriptApproveResponse(
            job_id="test-job",
            total_slides=5,
            tts_task_id=None,
            status="approved",
        )
        assert resp.status == "approved"
        assert resp.tts_task_id is None


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
                "left": 0,
                "top": 0,
                "width": 100,
                "height": 100,
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
        "lecture_name": "Test Lecture",
        "subject_name": "Test",
        "target_audience": "students",
        "target_minutes": 10,
        "style": {"density": "concise", "tone": "formal", "approach": "explanatory"},
        "slide_count": slide_count,
        "slides": slides,
    }


def _setup_job_dir(tmp_path: Path, slide_count: int = 3) -> dict:
    """Create a job directory structure for testing."""
    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir(exist_ok=True)
    vlm_dir = tmp_path / "vlm"
    vlm_dir.mkdir(exist_ok=True)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    manifest = _make_manifest(slide_count)
    (parsed_dir / "manifest.json").write_text(json.dumps(manifest))

    for i in range(slide_count):
        vlm_note = {
            "visual_summary": f"Slide {i+1} summary",
            "key_elements": ["element1"],
            "teaching_points": ["point1"],
        }
        (vlm_dir / f"vlm_note_{i+1:03d}.json").write_text(json.dumps(vlm_note))

    return manifest


def _fake_claude_response(slide_index=0, slide_number=1):
    """Return a valid JSON string mimicking Claude output."""
    return json.dumps({
        "slide_index": slide_index,
        "slide_number": slide_number,
        "target_seconds": 200.0,
        "script": "Generated script text",
        "keywords": ["keyword1"],
        "transition_to_next": "Next topic",
    })


def _make_job_paths_mock(tmp_path: Path):
    """Create a mock JobPaths pointing at tmp_path subdirs."""
    mock_paths = MagicMock()
    mock_paths.manifest_path = tmp_path / "parsed" / "manifest.json"
    mock_paths.vlm_dir = tmp_path / "vlm"
    mock_paths.scripts_dir = tmp_path / "scripts"
    return mock_paths


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------

class TestGenerateScriptsTask:
    """Tests for generate_scripts_task Celery task."""

    def _run_task(self, tmp_path, slide_count=3, pre_existing_scripts=None):
        """Helper to run the task with mocked dependencies.

        Args:
            tmp_path: pytest tmp_path fixture.
            slide_count: Number of slides.
            pre_existing_scripts: Dict of {slide_number: script_data} to pre-create.

        Returns:
            Tuple of (result_dict, progress_mock, claude_mock).
        """
        _setup_job_dir(tmp_path, slide_count)
        scripts_dir = tmp_path / "scripts"

        if pre_existing_scripts:
            for sn, data in pre_existing_scripts.items():
                (scripts_dir / f"script_{sn:03d}.json").write_text(json.dumps(data))

        mock_paths = _make_job_paths_mock(tmp_path)

        mock_client = MagicMock()
        mock_client.complete_text.return_value = _fake_claude_response()

        progress_calls = []

        def fake_progress(job_id, stage, current, total, status):
            progress_calls.append((job_id, stage, current, total, status))

        # Import the task module
        from lecture_auto.tasks import script_tasks

        # Patch at the module level for items imported at top-level
        with patch.object(script_tasks, "publish_progress", side_effect=fake_progress):
            # Patch the lazy imports inside the function
            with patch("lecture_auto.storage.jobs.JobPaths", return_value=mock_paths):
                with patch("lecture_auto.llm.get_llm_client", return_value=mock_client):
                    result = script_tasks.generate_scripts_task.__wrapped__(
                        "test-job"
                    )

        return result, progress_calls

    def test_skips_existing_valid_scripts(self, tmp_path):
        """Task skips slides that already have valid script_{NNN}.json (resumability)."""
        existing = {
            1: {
                "slide_index": 0,
                "slide_number": 1,
                "target_seconds": 200.0,
                "script": "Existing script",
                "keywords": ["existing"],
                "transition_to_next": "Next",
                "edited": False,
                "edited_at": None,
            }
        }
        result, progress_calls = self._run_task(
            tmp_path, slide_count=3, pre_existing_scripts=existing
        )

        assert result["skipped"] == 1
        assert result["total"] == 3
        # Verify slide 1 was skipped in progress
        skipped = [c for c in progress_calls if c[4] == "skipped"]
        assert len(skipped) >= 1

    def test_publishes_progress_with_script_stage(self, tmp_path):
        """Task publishes progress with stage='script' for each slide."""
        result, progress_calls = self._run_task(tmp_path, slide_count=2)

        # All progress calls should use stage="script"
        for c in progress_calls:
            assert c[1] == "script", f"Expected stage='script', got {c[1]}"

    def test_returns_expected_dict(self, tmp_path):
        """Task returns dict with job_id, total, and skipped."""
        result, _ = self._run_task(tmp_path, slide_count=2)

        assert result["job_id"] == "test-job"
        assert result["total"] == 2
        assert "skipped" in result

    def test_atomic_write_uses_tmp_rename(self, tmp_path):
        """Task uses .tmp + os.rename for atomic writes."""
        _setup_job_dir(tmp_path, slide_count=1)
        mock_paths = _make_job_paths_mock(tmp_path)

        mock_client = MagicMock()
        mock_client.complete_text.return_value = _fake_claude_response()

        from lecture_auto.tasks import script_tasks

        rename_calls = []
        original_rename = os.rename

        def tracking_rename(src, dst):
            rename_calls.append((src, dst))
            return original_rename(src, dst)

        with patch.object(script_tasks, "publish_progress"):
            with patch("lecture_auto.storage.jobs.JobPaths", return_value=mock_paths):
                with patch("lecture_auto.llm.get_llm_client", return_value=mock_client):
                    with patch.object(script_tasks.os, "rename", side_effect=tracking_rename):
                        script_tasks.generate_scripts_task.__wrapped__(
                            "test-job"
                        )

        assert len(rename_calls) >= 1
        # First arg should end with .tmp
        assert str(rename_calls[0][0]).endswith(".tmp")

    def test_adds_edited_false_to_output(self, tmp_path):
        """Task adds edited=false and edited_at=null to generated scripts."""
        result, _ = self._run_task(tmp_path, slide_count=1)

        script_file = tmp_path / "scripts" / "script_001.json"
        assert script_file.exists()
        data = json.loads(script_file.read_text())
        assert data["edited"] is False
        assert data["edited_at"] is None
