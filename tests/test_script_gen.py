"""
Unit tests for lecture_auto/pipeline/script_gen.py.

The LLM transport is mocked via a fake LLMClient — no claude CLI / OpenAI required.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from lecture_auto.pipeline.script_gen import (
    SPEECH_CHARS_PER_SECOND,
    SlideScript,
    build_script_prompt,
    build_vision_script_prompt,
    generate_scripts,
)
from lecture_auto.schemas.manifest import (
    FontInfo,
    LectureStyle,
    ShapeRecord,
    SlideManifest,
    SlideRecord,
    TextParagraph,
    TextRun,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_style(
    density: str = "detailed",
    tone: str = "formal",
    approach: str = "explanatory",
) -> LectureStyle:
    return LectureStyle(density=density, tone=tone, approach=approach)


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
        name="TextBox",
        z_order=0,
        left=0,
        top=0,
        width=100,
        height=50,
        content_source="text",
        has_text=True,
        text_role="body",
        paragraphs=paragraphs,
    )


def _make_slide(idx: int, texts: list[str]) -> SlideRecord:
    return SlideRecord(
        slide_index=idx,
        slide_number=idx + 1,
        png_path=f"slide_{idx + 1:03d}.png",
        shapes=[_make_shape(texts)],
    )


def _make_manifest(slide_count: int = 5, target_minutes: int = 25) -> SlideManifest:
    return SlideManifest(
        job_id="test-job-123",
        file_sha256="abc123",
        lecture_name="Machine Learning 101",
        subject_name="Computer Science",
        target_audience="undergraduate",
        target_minutes=target_minutes,
        style=_make_style(),
        slide_count=slide_count,
        slides=[],
    )


def _valid_script_response(slide_index: int = 0, slide_number: int = 1) -> str:
    return json.dumps(
        {
            "slide_index": slide_index,
            "slide_number": slide_number,
            "target_seconds": 300.0,
            "script": "안녕하세요. 오늘은 머신러닝의 기초에 대해 알아보겠습니다.",
            "keywords": ["머신러닝", "지도학습", "손실함수"],
            "transition_to_next": "다음 슬라이드에서는 신경망에 대해 살펴보겠습니다.",
        }
    )


def _client_returning_per_call(capture: list[str] | None = None) -> MagicMock:
    """Fake LLMClient: chat() returns a valid script for each call in order.

    generate_scripts drives the model through chat() with a system+user message
    pair, not complete_text(); ``capture`` collects the user prompt of each call.
    """
    state = {"i": 0}

    def fake_chat(messages, **kwargs):
        if capture is not None:
            capture.append(messages[-1]["content"])
        idx = state["i"]
        state["i"] += 1
        return _valid_script_response(idx, idx + 1)

    client = MagicMock()
    client.chat.side_effect = fake_chat
    return client


# ---------------------------------------------------------------------------
# Test 1: generate_scripts returns list[SlideScript] with correct schema
# ---------------------------------------------------------------------------

def test_generate_scripts_returns_slidescript_schema(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    slides = [_make_slide(0, ["Introduction to ML"])]
    manifest = _make_manifest(slide_count=1, target_minutes=5)
    vlm_notes = [{"slide_index": 0, "visual_summary": "Intro diagram"}]

    client = MagicMock()
    client.chat.return_value = _valid_script_response(0, 1)

    result = generate_scripts(slides, vlm_notes, manifest, scripts_dir, client=client)

    assert len(result) == 1
    script = result[0]
    assert isinstance(script, SlideScript)
    assert script.slide_index == 0
    assert script.slide_number == 1
    assert isinstance(script.target_seconds, float)
    assert isinstance(script.script, str)
    assert isinstance(script.keywords, list)
    assert isinstance(script.transition_to_next, str)


# ---------------------------------------------------------------------------
# Test 2: Prompt includes prev/current/next slide context
# ---------------------------------------------------------------------------

def test_build_script_prompt_includes_context_window():
    current = _make_slide(1, ["Current slide content"])
    prev = _make_slide(0, ["Previous slide content"])
    next_slide = _make_slide(2, ["Next slide content"])
    style = _make_style()
    vlm_note = {"visual_summary": "Chart showing accuracy", "key_elements": ["chart"]}
    prev_script = "이전 슬라이드의 스크립트입니다. 마지막 부분입니다."

    prompt = build_script_prompt(
        slide=current,
        vlm_note=vlm_note,
        style=style,
        target_seconds=90.0,
        prev_slide=prev,
        next_slide=next_slide,
        prev_script=prev_script,
    )

    assert "Current slide content" in prompt
    assert "Previous slide content" in prompt
    assert "Next slide content" in prompt
    assert "마지막 부분입니다." in prompt


# ---------------------------------------------------------------------------
# Test 3: target_seconds calculation (target_minutes * 60 / slide_count)
# ---------------------------------------------------------------------------

def test_target_seconds_calculation(tmp_path: Path):
    """30 min / 20 slides = 90 sec/slide."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    slides = [_make_slide(i, [f"Slide {i}"]) for i in range(20)]
    manifest = _make_manifest(slide_count=20, target_minutes=30)
    vlm_notes = [{"slide_index": i, "visual_summary": "vis"} for i in range(20)]

    captured: list[str] = []
    client = _client_returning_per_call(captured)

    result = generate_scripts(slides, vlm_notes, manifest, scripts_dir, client=client)

    assert len(result) == 20
    assert "90" in captured[0]  # 30 * 60 / 20 = 90.0


# ---------------------------------------------------------------------------
# Test 4: Each script saved as script_NNN.json in scripts_dir
# ---------------------------------------------------------------------------

def test_generate_scripts_writes_json_files(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    n = 3
    slides = [_make_slide(i, [f"Slide {i}"]) for i in range(n)]
    manifest = _make_manifest(slide_count=n, target_minutes=15)
    vlm_notes = [{"slide_index": i} for i in range(n)]

    client = _client_returning_per_call()
    generate_scripts(slides, vlm_notes, manifest, scripts_dir, client=client)

    assert (scripts_dir / "script_001.json").exists()
    assert (scripts_dir / "script_002.json").exists()
    assert (scripts_dir / "script_003.json").exists()

    data = json.loads((scripts_dir / "script_001.json").read_text())
    assert "script" in data
    assert "keywords" in data


# ---------------------------------------------------------------------------
# Test 5: LectureStyle parameters embedded in prompt
# ---------------------------------------------------------------------------

def test_build_script_prompt_includes_style_parameters():
    slide = _make_slide(0, ["Topic introduction"])
    style = LectureStyle(density="concise", tone="casual", approach="socratic")
    vlm_note = {"visual_summary": "slide image description"}

    prompt = build_script_prompt(
        slide=slide,
        vlm_note=vlm_note,
        style=style,
        target_seconds=60.0,
        prev_slide=None,
        next_slide=None,
        prev_script=None,
    )

    assert "concise" in prompt
    assert "casual" in prompt
    assert "socratic" in prompt


# ---------------------------------------------------------------------------
# Test 6: JSON extraction from markdown code fence output
# ---------------------------------------------------------------------------

def test_generate_scripts_extracts_json_from_markdown_fence(tmp_path: Path):
    """The LLM sometimes wraps JSON in ```json ... ``` fences; _parse_script_json strips them."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    slides = [_make_slide(0, ["Content"])]
    manifest = _make_manifest(slide_count=1, target_minutes=5)
    vlm_notes = [{"slide_index": 0}]

    fenced = f"```json\n{_valid_script_response(0, 1)}\n```"
    client = MagicMock()
    client.chat.return_value = fenced

    result = generate_scripts(slides, vlm_notes, manifest, scripts_dir, client=client)

    assert len(result) == 1
    assert isinstance(result[0], SlideScript)


# ---------------------------------------------------------------------------
# Test: vision prompt drops transition_to_next/keywords, uses the 7 chars/sec
# formula, and includes the current slide's extracted text alongside the image.
# ---------------------------------------------------------------------------

def test_build_vision_script_prompt_output_format_and_char_budget():
    slide = _make_slide(0, ["작은 표 안의 텍스트"])
    style = _make_style()

    prompt = build_vision_script_prompt(
        slide=slide,
        style=style,
        target_seconds=100.0,
        prev_slide=None,
        next_slide=None,
        prev_script=None,
    )

    assert "transition_to_next" not in prompt
    assert "keywords" not in prompt
    # Derived from the constant, not hardcoded: the rate is a calibration knob
    # (7.0 -> 5.7 once the model's real rendering rate was measured) and a test
    # that pins the old number just breaks when the knob is legitimately turned.
    budget = 100.0 * SPEECH_CHARS_PER_SECOND
    assert str(round(budget * 0.9)) in prompt
    assert str(round(budget * 1.1)) in prompt
    assert "작은 표 안의 텍스트" in prompt


# ---------------------------------------------------------------------------
# Test 7: defaults to get_llm_client when no client passed
# ---------------------------------------------------------------------------

def test_generate_scripts_defaults_to_factory(tmp_path: Path, monkeypatch):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    slides = [_make_slide(0, ["Content"])]
    manifest = _make_manifest(slide_count=1, target_minutes=5)
    vlm_notes = [{"slide_index": 0}]

    fake_client = MagicMock()
    fake_client.chat.return_value = _valid_script_response(0, 1)

    import lecture_auto.pipeline.script_gen as sg
    monkeypatch.setattr(sg, "get_llm_client", lambda *a, **k: fake_client)

    result = generate_scripts(slides, vlm_notes, manifest, scripts_dir)  # no client
    assert len(result) == 1
    fake_client.chat.assert_called_once()
