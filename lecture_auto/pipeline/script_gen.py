"""
Script generation module — Claude via `claude -p` async subprocess.

Exports:
    SlideScript         — Pydantic schema for per-slide lecture scripts
    build_script_prompt — Build text prompt for Claude with slide context window
    call_claude         — Call `claude -p` via asyncio.create_subprocess_exec
    generate_scripts    — Main entry point: produce SlideScript JSON per slide
"""
from __future__ import annotations

import asyncio
import json
import logging
from asyncio.subprocess import PIPE
from pathlib import Path

from pydantic import BaseModel

from lecture_auto.schemas.manifest import LectureStyle, SlideManifest, SlideRecord

logger = logging.getLogger(__name__)

_PREV_SCRIPT_CONTEXT_CHARS = 100


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class SlideScript(BaseModel):
    slide_index: int
    slide_number: int
    target_seconds: float
    script: str
    keywords: list[str]
    transition_to_next: str


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_script_prompt(
    slide: SlideRecord,
    vlm_note: dict,
    style: LectureStyle,
    target_seconds: float,
    prev_slide: SlideRecord | None,
    next_slide: SlideRecord | None,
    prev_script: str | None,
) -> str:
    """Build a text prompt for Claude to generate one slide's lecture script.

    Implements the context window pattern (SCRIPT-02): includes previous slide
    title + previous script excerpt, current slide content, and next slide title.

    Args:
        slide:          Current SlideRecord.
        vlm_note:       VlmNote dict for the current slide.
        style:          LectureStyle parameters (density, tone, approach).
        target_seconds: Target duration in seconds for this slide.
        prev_slide:     Previous SlideRecord or None.
        next_slide:     Next SlideRecord or None.
        prev_script:    Script text from previous slide or None.

    Returns:
        Formatted string prompt ready to pass to `claude -p`.
    """

    def _extract_slide_title(s: SlideRecord) -> str:
        for shape in s.shapes:
            if shape.text_role == "title" and shape.has_text:
                for para in shape.paragraphs:
                    if para.full_text.strip():
                        return para.full_text.strip()
        # Fallback: first text shape
        for shape in s.shapes:
            if shape.has_text:
                for para in shape.paragraphs:
                    if para.full_text.strip():
                        return para.full_text.strip()
        return f"Slide {s.slide_number}"

    def _extract_all_text(s: SlideRecord) -> str:
        parts: list[str] = []
        for shape in s.shapes:
            if shape.has_text:
                for para in shape.paragraphs:
                    if para.full_text.strip():
                        parts.append(para.full_text.strip())
        return "\n".join(parts) if parts else "(내용 없음)"

    lines: list[str] = []

    # System role
    lines.append("당신은 한국 대학교 교수님의 강의 스크립트를 작성하는 전문 보조입니다.")
    lines.append("")

    # Style parameters
    lines.append(f"[강의 스타일]")
    lines.append(f"- 밀도(density): {style.density}")
    lines.append(f"- 어조(tone): {style.tone}")
    lines.append(f"- 접근법(approach): {style.approach}")
    if style.supplement:
        lines.append(f"- 보충 지시: {style.supplement}")
    lines.append("")

    # Target duration
    lines.append(f"[목표 발화 시간] {target_seconds:.0f}초")
    lines.append("")

    # Previous slide context
    if prev_slide is not None:
        prev_title = _extract_slide_title(prev_slide)
        lines.append(f"[이전 슬라이드 제목] {prev_title}")
        if prev_slide.shapes:
            prev_text = _extract_all_text(prev_slide)
            lines.append(f"[이전 슬라이드 내용]\n{prev_text}")
        if prev_script:
            excerpt = prev_script[-_PREV_SCRIPT_CONTEXT_CHARS:]
            lines.append(f"[이전 스크립트 마지막 부분] ...{excerpt}")
        lines.append("")

    # Current slide
    lines.append(f"[현재 슬라이드 번호] {slide.slide_number}")
    lines.append(f"[현재 슬라이드 내용]\n{_extract_all_text(slide)}")
    lines.append("")

    # VLM visual notes
    if vlm_note:
        lines.append("[VLM 시각 분석]")
        if "visual_summary" in vlm_note:
            lines.append(f"- 요약: {vlm_note['visual_summary']}")
        if "key_elements" in vlm_note:
            lines.append(f"- 핵심 요소: {', '.join(vlm_note.get('key_elements', []))}")
        if "teaching_points" in vlm_note:
            points = vlm_note.get("teaching_points", [])
            if points:
                lines.append(f"- 교육 포인트: {'; '.join(points)}")
        if "possible_confusions" in vlm_note:
            confusions = vlm_note.get("possible_confusions", [])
            if confusions:
                lines.append(f"- 혼동 가능 부분: {'; '.join(confusions)}")
        lines.append("")

    # Next slide context
    if next_slide is not None:
        next_title = _extract_slide_title(next_slide)
        next_text = _extract_all_text(next_slide)
        lines.append(f"[다음 슬라이드 제목] {next_title}")
        lines.append(f"[다음 슬라이드 내용]\n{next_text}")
        lines.append("")

    # Output format instruction
    lines.append("[출력 형식]")
    lines.append("강의 스크립트를 한국어로 작성하세요. 다음 JSON 형식으로만 출력하세요:")
    lines.append(
        '{"slide_index": <int>, "slide_number": <int>, "target_seconds": <float>, '
        '"script": "<강의 스크립트 텍스트>", '
        '"keywords": ["<핵심 키워드1>", ...(3-5개)], '
        '"transition_to_next": "<다음 슬라이드 연결 멘트>"}'
    )
    lines.append("유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude subprocess
# ---------------------------------------------------------------------------

async def call_claude(prompt: str) -> str:
    """Call `claude -p <prompt>` via asyncio subprocess.

    Args:
        prompt: The prompt string to pass to claude -p.

    Returns:
        stdout decoded as UTF-8.

    Raises:
        RuntimeError: If claude exits with non-zero returncode.
    """
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p",
        prompt,
        stdout=PIPE,
        stderr=PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"claude -p exited with code {proc.returncode}: {stderr_text}"
        )

    return stdout_bytes.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def _parse_script_json(text: str, slide_index: int, slide_number: int) -> dict:
    """Parse JSON from Claude output, handling markdown code fences."""
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        end = len(lines) - 1
        while end > 0 and lines[end].strip() in ("```", ""):
            end -= 1
        # Skip the opening fence line
        inner_lines = lines[1 : end + 1]
        text = "\n".join(inner_lines).strip()

    data = json.loads(text)

    # Ensure slide_index and slide_number are present
    data.setdefault("slide_index", slide_index)
    data.setdefault("slide_number", slide_number)

    return data


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_scripts(
    slides: list[SlideRecord],
    vlm_notes: list[dict],
    manifest: SlideManifest,
    scripts_dir: Path,
) -> list[SlideScript]:
    """Generate per-slide lecture scripts via Claude and save to scripts_dir.

    Processing is sequential (not parallel) because each slide's script
    depends on the previous slide's script for transition context (SCRIPT-02).

    Args:
        slides:      List of SlideRecord objects.
        vlm_notes:   List of VlmNote dicts (one per slide, same order).
        manifest:    SlideManifest with style, target_minutes, slide_count etc.
        scripts_dir: Directory to write script_NNN.json outputs.

    Returns:
        List of validated SlideScript objects (one per slide, in order).
    """
    target_seconds = (manifest.target_minutes * 60) / manifest.slide_count
    logger.info(
        "Generating scripts for %d slides @ %.1f sec/slide",
        len(slides),
        target_seconds,
    )

    scripts: list[SlideScript] = []
    prev_script_text: str | None = None

    for i, slide in enumerate(slides):
        logger.info(
            "Generating script for slide %d/%d",
            slide.slide_number,
            len(slides),
        )

        vlm_note = vlm_notes[i] if i < len(vlm_notes) else {}
        prev_slide = slides[i - 1] if i > 0 else None
        next_slide = slides[i + 1] if i < len(slides) - 1 else None

        prompt = build_script_prompt(
            slide=slide,
            vlm_note=vlm_note,
            style=manifest.style,
            target_seconds=target_seconds,
            prev_slide=prev_slide,
            next_slide=next_slide,
            prev_script=prev_script_text,
        )

        raw_output = await call_claude(prompt)
        data = _parse_script_json(raw_output, slide.slide_index, slide.slide_number)
        script = SlideScript(**data)

        # Save to scripts_dir
        out_path = scripts_dir / f"script_{slide.slide_number:03d}.json"
        out_path.write_text(
            json.dumps(script.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved script: %s", out_path)

        # Store for next iteration's context
        prev_script_text = script.script
        scripts.append(script)

    return scripts
