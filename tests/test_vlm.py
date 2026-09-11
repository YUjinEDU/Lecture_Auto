"""
Unit tests for lecture_auto/pipeline/vlm.py.

The LLM transport is mocked via a fake LLMClient — no GPU / OpenAI required.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lecture_auto.pipeline.vlm import (
    VlmNote,
    build_vlm_prompt,
    generate_visual_notes,
)
from lecture_auto.schemas.manifest import (
    FontInfo,
    ShapeRecord,
    SlideRecord,
    TextParagraph,
    TextRun,
)


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


def _valid_vlm_response(slide_index: int = 0) -> str:
    return json.dumps(
        {
            "slide_index": slide_index,
            "visual_summary": "Overview of neural networks",
            "key_elements": ["diagram", "equations"],
            "layout_relations": "Title at top, diagram center-left",
            "teaching_points": ["Explain backprop", "Show loss curve"],
            "possible_confusions": ["Chain rule sign conventions"],
        }
    )


def _mock_client(*responses: str) -> MagicMock:
    """A fake LLMClient whose analyze_image returns the given response(s)."""
    client = MagicMock()
    if len(responses) == 1:
        client.analyze_image.return_value = responses[0]
    else:
        client.analyze_image.side_effect = list(responses)
    return client


# ---------------------------------------------------------------------------
# Test 1: generate_visual_notes returns list[VlmNote] with correct schema
# ---------------------------------------------------------------------------

def test_generate_visual_notes_returns_vlmnote_schema(tmp_path: Path):
    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()
    vlm_dir = tmp_path / "vlm"
    vlm_dir.mkdir()

    slide = _make_slide(0, [_make_shape(has_text=True, texts=["Hello World"])])
    (rendered_dir / "slide_001.png").write_bytes(b"fake png")

    client = _mock_client(_valid_vlm_response(0))
    notes = generate_visual_notes(client, [slide], rendered_dir, vlm_dir)

    assert len(notes) == 1
    note = notes[0]
    assert isinstance(note, VlmNote)
    assert note.slide_index == 0
    assert isinstance(note.visual_summary, str)
    assert isinstance(note.key_elements, list)
    assert isinstance(note.layout_relations, str)
    assert isinstance(note.teaching_points, list)
    assert isinstance(note.possible_confusions, list)


# ---------------------------------------------------------------------------
# Test 2: VLM prompt includes parsed text from SlideRecord shapes
# ---------------------------------------------------------------------------

def test_build_vlm_prompt_includes_parsed_text(tmp_path: Path):
    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()
    (rendered_dir / "slide_001.png").write_bytes(b"fake png")

    slide = _make_slide(
        0,
        [_make_shape(has_text=True, texts=["Introduction to ML", "Key concepts here"])],
    )

    prompt = build_vlm_prompt(slide, rendered_dir)

    assert "Introduction to ML" in prompt
    assert "Key concepts here" in prompt
    assert "Parsed text from this slide" in prompt


# ---------------------------------------------------------------------------
# Test 3: Each output dict validated against VlmNote Pydantic model
# ---------------------------------------------------------------------------

def test_vlmnote_validation_rejects_missing_fields():
    with pytest.raises(Exception):
        VlmNote(slide_index=0, visual_summary="summary")


def test_vlmnote_validation_accepts_valid_data():
    note = VlmNote(
        slide_index=0,
        visual_summary="Overview",
        key_elements=["item1"],
        layout_relations="title top",
        teaching_points=["teach this"],
        possible_confusions=["confusion point"],
    )
    assert note.slide_index == 0


# ---------------------------------------------------------------------------
# Test 4: Output JSON files written to vlm_dir with correct naming
# ---------------------------------------------------------------------------

def test_generate_visual_notes_writes_json_files(tmp_path: Path):
    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()
    vlm_dir = tmp_path / "vlm"
    vlm_dir.mkdir()

    slides = []
    for i in range(3):
        slide = _make_slide(i, [_make_shape(has_text=True, texts=[f"Slide {i+1} content"])])
        (rendered_dir / f"slide_{i+1:03d}.png").write_bytes(b"fake png")
        slides.append(slide)

    client = _mock_client(*[_valid_vlm_response(i) for i in range(3)])
    generate_visual_notes(client, slides, rendered_dir, vlm_dir)

    assert (vlm_dir / "vlm_note_001.json").exists()
    assert (vlm_dir / "vlm_note_002.json").exists()
    assert (vlm_dir / "vlm_note_003.json").exists()

    data = json.loads((vlm_dir / "vlm_note_001.json").read_text())
    assert "visual_summary" in data
    assert "key_elements" in data


# ---------------------------------------------------------------------------
# Test 5: client receives the slide image path
# ---------------------------------------------------------------------------

def test_generate_visual_notes_passes_image_path(tmp_path: Path):
    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()
    vlm_dir = tmp_path / "vlm"
    vlm_dir.mkdir()

    slide = _make_slide(0, [_make_shape(has_text=True, texts=["x"])])
    (rendered_dir / "slide_001.png").write_bytes(b"fake png")

    client = _mock_client(_valid_vlm_response(0))
    generate_visual_notes(client, [slide], rendered_dir, vlm_dir)

    args, kwargs = client.analyze_image.call_args
    assert args[0] == rendered_dir / "slide_001.png"


# ---------------------------------------------------------------------------
# Test 6: empty slide (no shapes) handled gracefully
# ---------------------------------------------------------------------------

def test_generate_visual_notes_handles_empty_slide(tmp_path: Path):
    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()
    vlm_dir = tmp_path / "vlm"
    vlm_dir.mkdir()

    slide = _make_slide(0, [])  # no shapes
    (rendered_dir / "slide_001.png").write_bytes(b"fake png")

    client = _mock_client(_valid_vlm_response(0))
    notes = generate_visual_notes(client, [slide], rendered_dir, vlm_dir)

    assert len(notes) == 1
    prompt = build_vlm_prompt(slide, rendered_dir)
    assert "Parsed text from this slide" in prompt


# ---------------------------------------------------------------------------
# Test 7: Retry once on malformed JSON
# ---------------------------------------------------------------------------

def test_generate_visual_notes_retries_on_malformed_json(tmp_path: Path):
    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()
    vlm_dir = tmp_path / "vlm"
    vlm_dir.mkdir()

    slide = _make_slide(0, [_make_shape(has_text=True, texts=["Test content"])])
    (rendered_dir / "slide_001.png").write_bytes(b"fake png")

    # First response malformed, second valid -> exactly one retry.
    client = _mock_client("not valid json {{{", _valid_vlm_response(0))
    notes = generate_visual_notes(client, [slide], rendered_dir, vlm_dir)

    assert len(notes) == 1
    assert client.analyze_image.call_count == 2
