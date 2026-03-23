"""
Unit tests for lecture_auto/pipeline/vlm.py
All vLLM dependencies are mocked — GPU not required.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs for heavy dependencies that are not installed in the test env
# ---------------------------------------------------------------------------

# Stub vllm
vllm_stub = types.ModuleType("vllm")
vllm_stub.LLM = MagicMock
vllm_stub.SamplingParams = MagicMock
sys.modules.setdefault("vllm", vllm_stub)

# Stub qwen_vl_utils
qwen_stub = types.ModuleType("qwen_vl_utils")
sys.modules.setdefault("qwen_vl_utils", qwen_stub)

# Now import the module under test
from lecture_auto.pipeline.vlm import (  # noqa: E402
    VlmNote,
    build_vlm_prompt,
    generate_visual_notes,
    load_vlm,
)
from lecture_auto.schemas.manifest import (  # noqa: E402
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

    mock_llm = MagicMock()
    mock_result = MagicMock()
    mock_result.outputs = [MagicMock(text=_valid_vlm_response(0))]
    mock_llm.generate.return_value = [mock_result]

    notes = generate_visual_notes(mock_llm, [slide], rendered_dir, vlm_dir)

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

    # Text-grounded prompting: parsed text must appear
    assert "Introduction to ML" in str(prompt)
    assert "Key concepts here" in str(prompt)
    assert "Parsed text from this slide" in str(prompt)


# ---------------------------------------------------------------------------
# Test 3: Each output dict validated against VlmNote Pydantic model
# ---------------------------------------------------------------------------

def test_vlmnote_validation_rejects_missing_fields():
    with pytest.raises(Exception):
        VlmNote(
            slide_index=0,
            visual_summary="summary",
            # missing: key_elements, layout_relations, teaching_points, possible_confusions
        )


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

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        [MagicMock(outputs=[MagicMock(text=_valid_vlm_response(i))])] for i in range(3)
    ]

    generate_visual_notes(mock_llm, slides, rendered_dir, vlm_dir)

    # Files must be named vlm_note_001.json, vlm_note_002.json, vlm_note_003.json
    assert (vlm_dir / "vlm_note_001.json").exists()
    assert (vlm_dir / "vlm_note_002.json").exists()
    assert (vlm_dir / "vlm_note_003.json").exists()

    # File content must be valid JSON matching VlmNote
    data = json.loads((vlm_dir / "vlm_note_001.json").read_text())
    assert "visual_summary" in data
    assert "key_elements" in data


# ---------------------------------------------------------------------------
# Test 5: load_vlm accepts model_path parameter with default
# ---------------------------------------------------------------------------

def test_load_vlm_accepts_model_path():
    with patch("lecture_auto.pipeline.vlm.LLM") as mock_llm_cls:
        mock_llm_cls.return_value = MagicMock()
        result = load_vlm(model_path="Qwen/Qwen3-VL-8B-Instruct")
        mock_llm_cls.assert_called_once()
        call_kwargs = mock_llm_cls.call_args
        assert call_kwargs is not None


def test_load_vlm_uses_default_model_path():
    with patch("lecture_auto.pipeline.vlm.LLM") as mock_llm_cls:
        mock_llm_cls.return_value = MagicMock()
        load_vlm()
        mock_llm_cls.assert_called_once()


# ---------------------------------------------------------------------------
# Test 6: generate_visual_notes handles empty slide (no shapes) gracefully
# ---------------------------------------------------------------------------

def test_generate_visual_notes_handles_empty_slide(tmp_path: Path):
    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()
    vlm_dir = tmp_path / "vlm"
    vlm_dir.mkdir()

    slide = _make_slide(0, [])  # no shapes
    (rendered_dir / "slide_001.png").write_bytes(b"fake png")

    mock_llm = MagicMock()
    mock_result = MagicMock()
    mock_result.outputs = [MagicMock(text=_valid_vlm_response(0))]
    mock_llm.generate.return_value = [mock_result]

    notes = generate_visual_notes(mock_llm, [slide], rendered_dir, vlm_dir)

    assert len(notes) == 1
    # Prompt must still work — just no parsed text to include
    prompt = build_vlm_prompt(slide, rendered_dir)
    assert "Parsed text from this slide" in str(prompt)


# ---------------------------------------------------------------------------
# Test 7: Retry on malformed JSON
# ---------------------------------------------------------------------------

def test_generate_visual_notes_retries_on_malformed_json(tmp_path: Path):
    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()
    vlm_dir = tmp_path / "vlm"
    vlm_dir.mkdir()

    slide = _make_slide(0, [_make_shape(has_text=True, texts=["Test content"])])
    (rendered_dir / "slide_001.png").write_bytes(b"fake png")

    # First call returns malformed JSON; second call returns valid JSON
    # generate() returns a list of RequestOutput objects → results[0].outputs[0].text
    bad_result = MagicMock()
    bad_result.outputs = [MagicMock(text="not valid json {{{")]
    good_result = MagicMock()
    good_result.outputs = [MagicMock(text=_valid_vlm_response(0))]

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [[bad_result], [good_result]]

    notes = generate_visual_notes(mock_llm, [slide], rendered_dir, vlm_dir)

    assert len(notes) == 1
    assert mock_llm.generate.call_count == 2  # retried once
