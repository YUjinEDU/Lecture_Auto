"""Tests for lecture_auto/tasks/vlm_tasks.py — resumable VLM Celery task."""

from __future__ import annotations

import json
import sys
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub heavy dependencies
# ---------------------------------------------------------------------------
vllm_stub = types.ModuleType("vllm")
vllm_stub.LLM = MagicMock
vllm_stub.SamplingParams = MagicMock
sys.modules.setdefault("vllm", vllm_stub)

qwen_stub = types.ModuleType("qwen_vl_utils")
sys.modules.setdefault("qwen_vl_utils", qwen_stub)

from lecture_auto.schemas.manifest import (  # noqa: E402
    FontInfo,
    LectureStyle,
    ShapeRecord,
    SlideManifest,
    SlideRecord,
    TextParagraph,
    TextRun,
)
from lecture_auto.storage.jobs import JobPaths  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_shape(texts: list[str]) -> ShapeRecord:
    paragraphs = [
        TextParagraph(
            full_text=t,
            runs=[TextRun(text=t, font=FontInfo(name="Arial", size_pt=12.0))],
        )
        for t in texts
    ]
    return ShapeRecord(
        shape_id=1,
        name="TextBox 1",
        z_order=0,
        left=100,
        top=100,
        width=500,
        height=300,
        content_source="text",
        has_text=True,
        has_image=False,
        text_role="body",
        paragraphs=paragraphs,
    )


def _make_manifest(tmp_path: Path, slide_count: int = 2) -> SlideManifest:
    """Create a minimal manifest."""
    slides = []
    for i in range(slide_count):
        slides.append(
            SlideRecord(
                slide_index=i,
                slide_number=i + 1,
                png_path=f"slide_{i + 1:03d}.png",
                shapes=[_make_shape([f"Content for slide {i + 1}"])],
            )
        )
    return SlideManifest(
        job_id=str(uuid.uuid4()),
        file_sha256="abc123",
        lecture_name="Test Lecture",
        subject_name="CS101",
        target_audience="undergrad",
        target_minutes=30,
        style=LectureStyle(density="concise", tone="formal", approach="explanatory"),
        slide_count=slide_count,
        slides=slides,
    )


def _setup_job_dirs(tmp_path: Path, manifest: SlideManifest) -> JobPaths:
    """Create job directory structure with manifest on disk."""
    jp = JobPaths(manifest.job_id, root=tmp_path)
    jp.ensure_dirs()
    jp.manifest_path.write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    for slide in manifest.slides:
        (jp.rendered_dir / slide.png_path).write_bytes(b"fake png")
    return jp


def _run_task(tmp_path, manifest, mock_get_vlm, mock_gen=None):
    """Helper to run process_slides_task with proper patching.

    Uses .run() to call the underlying function directly, bypassing Celery
    task machinery. bind=True means the first arg is self (the task instance).
    """
    from lecture_auto.tasks.vlm_tasks import process_slides_task

    # Patch at source modules because vlm_tasks uses local imports
    with patch("lecture_auto.pipeline.vlm.generate_single_note", mock_gen or MagicMock()) as gen:
        with patch(
            "lecture_auto.storage.jobs.os.environ.get",
            side_effect=lambda k, d=None: str(tmp_path) if k == "JOB_OUTPUT_ROOT" else d,
        ):
            result = process_slides_task.run(manifest.job_id)
    return result, gen


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProcessSlidesTask:
    """process_slides_task with mocked VLM and Redis."""

    @patch("lecture_auto.tasks.vlm_tasks.publish_progress")
    @patch("lecture_auto.tasks.vlm_tasks._get_vlm")
    def test_processes_all_slides(self, mock_get_vlm, mock_publish, tmp_path):
        """All slides processed when no prior vlm_note files exist."""
        manifest = _make_manifest(tmp_path, slide_count=2)
        _setup_job_dirs(tmp_path, manifest)

        mock_llm = MagicMock()
        mock_get_vlm.return_value = mock_llm

        result, mock_gen = _run_task(tmp_path, manifest, mock_get_vlm)

        assert result["total"] == 2
        assert result["skipped"] == 0
        assert mock_gen.call_count == 2

        # Verify progress was published for each slide
        progress_calls = mock_publish.call_args_list
        assert len(progress_calls) == 4  # processing + done for each slide

    @patch("lecture_auto.tasks.vlm_tasks.publish_progress")
    @patch("lecture_auto.tasks.vlm_tasks._get_vlm")
    def test_skips_completed_slides(self, mock_get_vlm, mock_publish, tmp_path):
        """Slides with valid existing vlm_note files are skipped."""
        manifest = _make_manifest(tmp_path, slide_count=2)
        jp = _setup_job_dirs(tmp_path, manifest)

        # Pre-create valid vlm_note_001.json
        valid_note = {
            "slide_index": 0,
            "visual_summary": "Summary",
            "key_elements": ["elem"],
            "layout_relations": "layout",
            "teaching_points": ["point"],
            "possible_confusions": ["conf"],
            "needs_review": False,
            "token_overlap_ratio": 0.9,
        }
        (jp.vlm_dir / "vlm_note_001.json").write_text(
            json.dumps(valid_note), encoding="utf-8"
        )

        mock_llm = MagicMock()
        mock_get_vlm.return_value = mock_llm

        result, mock_gen = _run_task(tmp_path, manifest, mock_get_vlm)

        assert result["skipped"] == 1
        assert mock_gen.call_count == 1  # only slide 2 processed

        # Verify slide 1 got "skipped" status
        skip_calls = [c for c in mock_publish.call_args_list if c[0][4] == "skipped"]
        assert len(skip_calls) == 1

    @patch("lecture_auto.tasks.vlm_tasks.publish_progress")
    @patch("lecture_auto.tasks.vlm_tasks._get_vlm")
    def test_reprocesses_invalid_json(self, mock_get_vlm, mock_publish, tmp_path):
        """Malformed vlm_note files are re-processed."""
        manifest = _make_manifest(tmp_path, slide_count=1)
        jp = _setup_job_dirs(tmp_path, manifest)

        # Pre-create invalid vlm_note_001.json
        (jp.vlm_dir / "vlm_note_001.json").write_text(
            "not valid json {{{", encoding="utf-8"
        )

        mock_llm = MagicMock()
        mock_get_vlm.return_value = mock_llm

        result, mock_gen = _run_task(tmp_path, manifest, mock_get_vlm)

        assert result["skipped"] == 0
        assert mock_gen.call_count == 1  # re-processed

    @patch("lecture_auto.tasks.vlm_tasks.publish_progress")
    @patch("lecture_auto.tasks.vlm_tasks._get_vlm")
    def test_publishes_correct_progress_args(self, mock_get_vlm, mock_publish, tmp_path):
        """publish_progress called with correct (job_id, stage, current, total, status)."""
        manifest = _make_manifest(tmp_path, slide_count=1)
        _setup_job_dirs(tmp_path, manifest)

        mock_llm = MagicMock()
        mock_get_vlm.return_value = mock_llm

        _run_task(tmp_path, manifest, mock_get_vlm)

        # Should have "processing" then "done" calls
        calls = mock_publish.call_args_list
        assert len(calls) == 2

        proc_call = calls[0][0]
        assert proc_call[0] == manifest.job_id  # job_id
        assert proc_call[1] == "vlm"  # stage
        assert proc_call[2] == 1  # current
        assert proc_call[3] == 1  # total
        assert proc_call[4] == "processing"  # status

        done_call = calls[1][0]
        assert done_call[4] == "done"
