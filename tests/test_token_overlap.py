"""
Tests for token overlap computation, extended VlmNote schema,
generate_single_note, and JobStatus/ProgressEvent schemas.

TDD RED phase: these tests define expected behavior before implementation.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs for heavy dependencies not in test env
# ---------------------------------------------------------------------------
vllm_stub = types.ModuleType("vllm")
vllm_stub.LLM = MagicMock
vllm_stub.SamplingParams = MagicMock
sys.modules.setdefault("vllm", vllm_stub)

qwen_stub = types.ModuleType("qwen_vl_utils")
sys.modules.setdefault("qwen_vl_utils", qwen_stub)

from lecture_auto.pipeline.vlm import (  # noqa: E402
    VlmNote,
    compute_token_overlap,
    generate_single_note,
    _extract_slide_text,
)
from lecture_auto.schemas.manifest import (  # noqa: E402
    FontInfo,
    ShapeRecord,
    SlideRecord,
    TextParagraph,
    TextRun,
)
from lecture_auto.schemas.job_status import JobStatus, ProgressEvent  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_shape(has_text: bool = True, texts: list[str] | None = None) -> ShapeRecord:
    paragraphs: list[TextParagraph] = []
    if has_text and texts:
        for t in texts:
            paragraphs.append(
                TextParagraph(
                    full_text=t,
                    runs=[TextRun(text=t, font=FontInfo(name="Arial", size_pt=12.0))],
                )
            )
    return ShapeRecord(
        shape_id=1,
        name="TextBox 1",
        z_order=0,
        left=100,
        top=100,
        width=500,
        height=300,
        content_source="text",
        has_text=has_text,
        has_image=False,
        text_role="body",
        paragraphs=paragraphs,
    )


def _make_slide(
    slide_index: int = 0,
    shapes: list[ShapeRecord] | None = None,
) -> SlideRecord:
    return SlideRecord(
        slide_index=slide_index,
        slide_number=slide_index + 1,
        png_path=f"slide_{slide_index + 1:03d}.png",
        shapes=shapes or [],
    )


def _valid_vlm_response_dict(slide_index: int = 0) -> dict:
    return {
        "slide_index": slide_index,
        "visual_summary": "Overview of neural networks",
        "key_elements": ["diagram", "equations"],
        "layout_relations": "Title at top, diagram center-left",
        "teaching_points": ["Explain backprop", "Show loss curve"],
        "possible_confusions": ["Chain rule sign conventions"],
    }


def _valid_vlm_response(slide_index: int = 0) -> str:
    return json.dumps(_valid_vlm_response_dict(slide_index))


# ---------------------------------------------------------------------------
# compute_token_overlap tests
# ---------------------------------------------------------------------------

class TestComputeTokenOverlap:
    """Token overlap computation edge cases."""

    def test_high_overlap_returns_above_threshold(self):
        """Overlapping tokens between VLM and parsed text yield > 0.3."""
        result = compute_token_overlap(
            "visual summary key elements", "key elements on slide"
        )
        assert result > 0.3

    def test_unrelated_text_returns_below_threshold(self):
        """Completely different texts yield < 0.3."""
        result = compute_token_overlap(
            "completely unrelated hallucinated text",
            "slide about python basics",
        )
        assert result < 0.3

    def test_empty_vlm_text_returns_one(self):
        """No VLM tokens means nothing to check -> 1.0."""
        result = compute_token_overlap("", "any text")
        assert result == 1.0

    def test_empty_parsed_text_returns_zero(self):
        """No parsed text means all VLM-generated -> 0.0."""
        result = compute_token_overlap("some text", "")
        assert result == 0.0

    def test_korean_text_overlap(self):
        """Korean text tokenization produces positive overlap."""
        result = compute_token_overlap("슬라이드 제목 내용", "슬라이드 제목")
        assert result > 0.0

    def test_identical_text_returns_one(self):
        """Identical texts yield 1.0."""
        result = compute_token_overlap("hello world", "hello world")
        assert result == 1.0

    def test_both_empty_returns_one(self):
        """Both empty -> vlm has no tokens -> 1.0."""
        result = compute_token_overlap("", "")
        assert result == 1.0


# ---------------------------------------------------------------------------
# Extended VlmNote schema tests
# ---------------------------------------------------------------------------

class TestExtendedVlmNote:
    """VlmNote with needs_review and token_overlap_ratio."""

    def test_vlmnote_accepts_needs_review_and_overlap(self):
        note = VlmNote(
            slide_index=0,
            visual_summary="summary",
            key_elements=["a"],
            layout_relations="layout",
            teaching_points=["t"],
            possible_confusions=["c"],
            needs_review=True,
            token_overlap_ratio=0.15,
        )
        assert note.needs_review is True
        assert note.token_overlap_ratio == 0.15

    def test_vlmnote_defaults(self):
        note = VlmNote(
            slide_index=0,
            visual_summary="summary",
            key_elements=["a"],
            layout_relations="layout",
            teaching_points=["t"],
            possible_confusions=["c"],
        )
        assert note.needs_review is False
        assert note.token_overlap_ratio == 1.0


# ---------------------------------------------------------------------------
# _extract_slide_text tests
# ---------------------------------------------------------------------------

class TestExtractSlideText:
    def test_extracts_all_paragraph_text(self):
        slide = _make_slide(0, [_make_shape(has_text=True, texts=["Hello", "World"])])
        text = _extract_slide_text(slide)
        assert "Hello" in text
        assert "World" in text

    def test_empty_slide_returns_empty(self):
        slide = _make_slide(0, [])
        text = _extract_slide_text(slide)
        assert text == ""

    def test_no_text_shape_returns_empty(self):
        slide = _make_slide(0, [_make_shape(has_text=False)])
        text = _extract_slide_text(slide)
        assert text == ""


# ---------------------------------------------------------------------------
# generate_single_note tests
# ---------------------------------------------------------------------------

class TestGenerateSingleNote:
    """generate_single_note with mocked LLM."""

    def test_writes_json_with_needs_review_field(self, tmp_path: Path):
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir()
        vlm_dir = tmp_path / "vlm"
        vlm_dir.mkdir()

        # Slide with enough text for token counting (> 10 tokens)
        slide = _make_slide(
            0,
            [_make_shape(
                has_text=True,
                texts=["This is a long enough text with many tokens for overlap check"],
            )],
        )
        (rendered_dir / "slide_001.png").write_bytes(b"fake png")

        # VLM returns unrelated text -> needs_review should be True
        response_data = _valid_vlm_response_dict(0)
        response_data["visual_summary"] = "completely hallucinated unrelated content"
        response_data["key_elements"] = ["fabricated", "nonsense"]
        response_data["teaching_points"] = ["invented point"]

        mock_client = MagicMock()
        mock_client.analyze_image.return_value = json.dumps(response_data)

        note = generate_single_note(mock_client, slide, rendered_dir, vlm_dir)

        # Check file was written
        out_path = vlm_dir / "vlm_note_001.json"
        assert out_path.exists()
        file_data = json.loads(out_path.read_text())
        assert "needs_review" in file_data
        assert "token_overlap_ratio" in file_data

    def test_skips_needs_review_for_image_heavy_slides(self, tmp_path: Path):
        """When parsed_token_count <= 10, needs_review is always False."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir()
        vlm_dir = tmp_path / "vlm"
        vlm_dir.mkdir()

        # Slide with very few tokens (image-heavy)
        slide = _make_slide(0, [_make_shape(has_text=True, texts=["Short"])])
        (rendered_dir / "slide_001.png").write_bytes(b"fake png")

        response_data = _valid_vlm_response_dict(0)
        response_data["visual_summary"] = "totally unrelated hallucinated text"

        mock_client = MagicMock()
        mock_client.analyze_image.return_value = json.dumps(response_data)

        note = generate_single_note(mock_client, slide, rendered_dir, vlm_dir)

        # Image-heavy slide: needs_review should be False regardless
        assert note.needs_review is False

    def test_retries_on_json_failure(self, tmp_path: Path):
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir()
        vlm_dir = tmp_path / "vlm"
        vlm_dir.mkdir()

        slide = _make_slide(0, [_make_shape(has_text=True, texts=["Content"])])
        (rendered_dir / "slide_001.png").write_bytes(b"fake png")

        mock_client = MagicMock()
        mock_client.analyze_image.side_effect = [
            "not valid json {{{",
            _valid_vlm_response(0),
        ]

        note = generate_single_note(mock_client, slide, rendered_dir, vlm_dir)

        assert note is not None
        assert mock_client.analyze_image.call_count == 2


# ---------------------------------------------------------------------------
# JobStatus enum tests
# ---------------------------------------------------------------------------

class TestJobStatus:
    def test_enum_values(self):
        assert JobStatus.queued == "queued"
        assert JobStatus.started == "started"
        assert JobStatus.vlm_processing == "vlm_processing"
        assert JobStatus.completed == "completed"
        assert JobStatus.failed == "failed"

    def test_enum_count(self):
        assert {s.value for s in JobStatus} == {
            "queued",
            "started",
            "vlm_processing",
            "script_generating",
            "script_completed",
            "completed",
            "failed",
        }


# ---------------------------------------------------------------------------
# ProgressEvent schema tests
# ---------------------------------------------------------------------------

class TestProgressEvent:
    def test_schema_fields(self):
        event = ProgressEvent(
            job_id="test-123",
            stage="vlm",
            current=3,
            total=10,
            percent=30.0,
            status="processing",
        )
        assert event.job_id == "test-123"
        assert event.stage == "vlm"
        assert event.current == 3
        assert event.total == 10
        assert event.percent == 30.0
        assert event.status == "processing"

    def test_schema_rejects_missing_fields(self):
        with pytest.raises(Exception):
            ProgressEvent(job_id="test", stage="vlm")
