"""
Unit tests for lecture_auto/pipeline/script_gen.py
asyncio.create_subprocess_exec is mocked — claude binary not required.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lecture_auto.pipeline.script_gen import (
    SlideScript,
    build_script_prompt,
    call_claude,
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


# ---------------------------------------------------------------------------
# Test 1: generate_scripts returns list[SlideScript] with correct schema
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_scripts_returns_slidescript_schema(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    slides = [_make_slide(0, ["Introduction to ML"])]
    manifest = _make_manifest(slide_count=1, target_minutes=5)
    vlm_notes = [{"slide_index": 0, "visual_summary": "Intro diagram"}]

    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(
        return_value=(
            _valid_script_response(0, 1).encode("utf-8"),
            b"",
        )
    )

    with patch(
        "lecture_auto.pipeline.script_gen.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=mock_process),
    ):
        result = await generate_scripts(slides, vlm_notes, manifest, scripts_dir)

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
    assert "마지막 부분입니다." in prompt  # last 100 chars of prev_script


# ---------------------------------------------------------------------------
# Test 3: target_seconds calculation (target_minutes * 60 / slide_count)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_target_seconds_calculation(tmp_path: Path):
    """30 min / 20 slides = 90 sec/slide."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    slides = [_make_slide(i, [f"Slide {i}"]) for i in range(20)]
    manifest = _make_manifest(slide_count=20, target_minutes=30)
    vlm_notes = [{"slide_index": i, "visual_summary": "vis"} for i in range(20)]

    captured_prompts: list[str] = []

    async def fake_subprocess(*args, **kwargs):
        prompt_text = args[2]  # claude, -p, <prompt>
        captured_prompts.append(prompt_text)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        idx = len(captured_prompts) - 1
        mock_proc.communicate = AsyncMock(
            return_value=(
                _valid_script_response(idx, idx + 1).encode("utf-8"),
                b"",
            )
        )
        return mock_proc

    with patch(
        "lecture_auto.pipeline.script_gen.asyncio.create_subprocess_exec",
        new=fake_subprocess,
    ):
        result = await generate_scripts(slides, vlm_notes, manifest, scripts_dir)

    assert len(result) == 20
    # target_seconds = 30 * 60 / 20 = 90.0 — check it appears in a prompt
    assert "90" in captured_prompts[0]


# ---------------------------------------------------------------------------
# Test 4: Each script saved as script_NNN.json in scripts_dir
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_scripts_writes_json_files(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    n = 3
    slides = [_make_slide(i, [f"Slide {i}"]) for i in range(n)]
    manifest = _make_manifest(slide_count=n, target_minutes=15)
    vlm_notes = [{"slide_index": i} for i in range(n)]

    async def fake_subprocess(*args, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        idx = len(list(scripts_dir.glob("script_*.json")))
        mock_proc.communicate = AsyncMock(
            return_value=(
                _valid_script_response(idx, idx + 1).encode("utf-8"),
                b"",
            )
        )
        return mock_proc

    with patch(
        "lecture_auto.pipeline.script_gen.asyncio.create_subprocess_exec",
        new=fake_subprocess,
    ):
        await generate_scripts(slides, vlm_notes, manifest, scripts_dir)

    assert (scripts_dir / "script_001.json").exists()
    assert (scripts_dir / "script_002.json").exists()
    assert (scripts_dir / "script_003.json").exists()

    data = json.loads((scripts_dir / "script_001.json").read_text())
    assert "script" in data
    assert "keywords" in data


# ---------------------------------------------------------------------------
# Test 5: claude -p subprocess called via asyncio.create_subprocess_exec
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_claude_uses_asyncio_subprocess():
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(
        return_value=(b'{"result": "ok"}', b"")
    )

    with patch(
        "lecture_auto.pipeline.script_gen.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=mock_process),
    ) as mock_exec:
        result = await call_claude("test prompt")

    mock_exec.assert_called_once()
    call_args = mock_exec.call_args
    # First positional args must be "claude", "-p", prompt
    assert call_args.args[0] == "claude"
    assert call_args.args[1] == "-p"
    assert '{"result": "ok"}' == result


# ---------------------------------------------------------------------------
# Test 6: LectureStyle parameters embedded in prompt
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
# Test 7: Handles claude -p failure (non-zero exit) with clear error message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_claude_raises_on_nonzero_exit():
    mock_process = MagicMock()
    mock_process.returncode = 1
    mock_process.communicate = AsyncMock(
        return_value=(b"", b"Error: claude not authenticated")
    )

    with patch(
        "lecture_auto.pipeline.script_gen.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=mock_process),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            await call_claude("some prompt")

    assert "claude" in str(exc_info.value).lower() or "Error" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 8: JSON extraction from markdown code fence output
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_claude_extracts_json_from_markdown_fence(tmp_path: Path):
    """Claude sometimes wraps JSON in ```json ... ``` fences."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    slides = [_make_slide(0, ["Content"])]
    manifest = _make_manifest(slide_count=1, target_minutes=5)
    vlm_notes = [{"slide_index": 0}]

    fenced_output = f"```json\n{_valid_script_response(0, 1)}\n```"

    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(
        return_value=(fenced_output.encode("utf-8"), b"")
    )

    with patch(
        "lecture_auto.pipeline.script_gen.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=mock_process),
    ):
        result = await generate_scripts(slides, vlm_notes, manifest, scripts_dir)

    assert len(result) == 1
    assert isinstance(result[0], SlideScript)
