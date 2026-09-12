"""
Script generation module — lecture scripts via the unified LLM client.

Provider/transport lives in :mod:`lecture_auto.llm` (OpenAI by default).

Exports:
    SlideScript         — Pydantic schema for per-slide lecture scripts
    build_script_prompt — Build the text prompt with the slide context window
    generate_scripts    — Main entry point: produce SlideScript JSON per slide
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from pydantic import BaseModel

from lecture_auto.llm import LLMClient, get_llm_client
from lecture_auto.schemas.manifest import LectureStyle, SlideManifest, SlideRecord

logger = logging.getLogger(__name__)

# Measured rendering rate of Raon-Speech-9B on this professor's cloned voice,
# NOT how fast the professor himself talks (he runs 6.46 chars/s over his 32min
# recording). Only the TTS rate determines video length: two gate-passing v7
# generations came out at 5.52 and 5.84 chars/s. The previous 7.0 is why 48
# slides budgeted to exactly 30.0 minutes rendered as 42.2 minutes of audio.
# Keep in sync with _CHARS_PER_SECOND in pipeline/raon_tts.py, which sizes the
# quality gate's duration window around the same rate.
SPEECH_CHARS_PER_SECOND = 5.7

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


def get_professor_system_prompt() -> str:
    """Load the Luna professor instruction prompt + the STT-derived style guide.

    ``luna_professor_instruction.md`` (few-shot examples, negative constraints,
    JSON format) and ``professor_style_guide.md`` (quantitative pacing stats +
    top phrases from the 32-min real-lecture transcript) are complementary, not
    duplicates -- both are loaded so the pacing data actually reaches the prompt.
    """
    prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
    instruction_file = prompts_dir / "luna_professor_instruction.md"
    style_guide_file = prompts_dir / "professor_style_guide.md"

    if instruction_file.exists():
        parts = [instruction_file.read_text(encoding="utf-8")]
    else:
        parts = [
            "당신은 대학 강단에서 학생들을 대상으로 강의를 진행하는 김영국 교수님 본인입니다. "
            "구어체와 스토리텔링 비유를 활용하여 실제 육성 강의처럼 생생하고 자연스러운 대본을 작성하십시오."
        ]
    if style_guide_file.exists():
        parts.append("\n---\n\n" + style_guide_file.read_text(encoding="utf-8"))
    return "\n".join(parts)


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
    lines: list[str] = []

    # System role & Professor Persona
    lines.append("당신은 실제 대학 강의를 진행하는 교수님의 생생한 강의 대본을 작성하는 전문 AI입니다.")
    lines.append("다음 [교수님 고유 강의 발화 스타일]을 반드시 준수하여 실제 육성 강의처럼 자연스럽고 몰입감 있게 작성하세요.")
    lines.append("")
    lines.append("[교수님 고유 강의 발화 스타일 (실제 강의 음성 분석 반영)]")
    lines.append("- 학생 대상 호칭: '여러분', '학생 여러분', 또는 '우리' ('우리가 지난 시간에~', '우리가 한번 살펴보면~')")
    lines.append("- 자주 사용하는 도입/연결 추임새: '자, 안녕하세요', '자, 그럼 이번 장에서는~', '자, 다음으로 보실 내용은~', '그러니까 우리가~', '그 다음에 이제~', '자, 여기 참고로 비유해서 말씀드리면~'")
    lines.append("- 자주 사용하는 문장 종결 어미: '~라고 볼 수가 있겠죠?', '~에 해당되는 거겠죠.', '~라는 이야기이고요.', '~할 수가 있습니다.', '~그렇죠? 바로 이런 문제 상황인 거죠.', '~해야 되는 거죠.'")
    lines.append("- 설명 전개 방식: 슬라이드의 요약 문장을 단순히 읽지 말고, 구체적인 일상 및 현업 사례/비유를 들어가며 학생들에게 질문을 던지듯 흥미진진하게 설명할 것.")
    lines.append("- 톤앤매너: 학문적 전문성을 갖추면서도 친절하고 권위적이지 않은 구어체.")
    lines.append("")

    # Style parameters
    lines.append(f"[강의 설정]")
    lines.append(f"- 밀도: {style.density}, 어조: {style.tone}, 접근법: {style.approach}")
    if style.supplement:
        lines.append(f"- 추가 지침: {style.supplement}")
    lines.append(
        f"- 목표 발화 시간: 약 {target_seconds:.0f}초 "
        f"(초당 약 {SPEECH_CHARS_PER_SECOND}자 기준, 약 {int(target_seconds * SPEECH_CHARS_PER_SECOND)}자 내외)"
    )
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
# Vision-based prompt (no VLM-notes stage -- the slide image goes straight
# into the script-gen call, per the batch generator's direct-vision approach)
# ---------------------------------------------------------------------------

def build_vision_script_prompt(
    slide: SlideRecord,
    style: LectureStyle,
    target_seconds: float,
    prev_slide: SlideRecord | None,
    next_slide: SlideRecord | None,
    prev_script: str | None,
) -> str:
    """Build the text half of a vision-based script prompt.

    Same context (style, prev/next titles, prev script excerpt) as
    :func:`build_script_prompt`, but omits the current slide's text dump and
    VLM-notes block -- the caller attaches the slide PNG as an image content
    part instead, and the model reads the slide directly.
    """
    lines: list[str] = []

    lines.append("당신은 실제 대학 강의를 진행하는 교수님의 생생한 강의 대본을 작성하는 전문 AI입니다.")
    lines.append("첨부된 현재 슬라이드 이미지를 직접 눈으로 보고, 그 안의 도표/그림/텍스트/배치를 반영하여 설명하십시오.")
    lines.append("system 메시지의 [교수님 고유 강의 발화 스타일]을 반드시 준수하여 실제 육성 강의처럼 자연스럽고 몰입감 있게 작성하세요.")
    lines.append("")

    target_chars = round(target_seconds * SPEECH_CHARS_PER_SECOND)
    lines.append("[강의 설정]")
    lines.append(f"- 밀도: {style.density}, 어조: {style.tone}, 접근법: {style.approach}")
    if style.supplement:
        lines.append(f"- 추가 지침: {style.supplement}")
    lines.append(
        f"- 목표 발화 시간: 약 {target_seconds:.0f}초 "
        f"(초당 약 {SPEECH_CHARS_PER_SECOND}자 기준, {round(target_chars * 0.9)}~{round(target_chars * 1.1)}자)"
    )
    lines.append("")

    if prev_slide is not None:
        prev_title = _extract_slide_title(prev_slide)
        lines.append(f"[이전 슬라이드 제목] {prev_title}")
        if prev_script:
            excerpt = prev_script[-_PREV_SCRIPT_CONTEXT_CHARS:]
            lines.append(f"[이전 스크립트 마지막 부분] ...{excerpt}")
        lines.append("")

    lines.append(f"[현재 슬라이드 번호] {slide.slide_number}")
    lines.append(f"[현재 슬라이드 추출 텍스트 (작은 글씨/표 등 이미지에서 놓칠 수 있는 내용 보완용)]\n{_extract_all_text(slide)}")
    lines.append("")

    if next_slide is not None:
        next_title = _extract_slide_title(next_slide)
        lines.append(f"[다음 슬라이드 제목] {next_title}")
        lines.append("")

    lines.append("[출력 형식]")
    lines.append("강의 스크립트를 한국어로 작성하세요. 다음 JSON 형식으로만 출력하세요:")
    lines.append(
        '{"slide_index": <int>, "slide_number": <int>, "target_seconds": <float>, '
        '"script": "<강의 스크립트 텍스트, 다음 슬라이드로의 자연스러운 전환도 이 문장 안에 포함>"}'
    )
    lines.append("유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.")

    return "\n".join(lines)


def generate_script_for_slide_vision(
    client: LLMClient,
    slide: SlideRecord,
    png_path: Path,
    style: LectureStyle,
    target_seconds: float,
    prev_slide: SlideRecord | None,
    next_slide: SlideRecord | None,
    prev_script: str | None,
) -> dict:
    """Generate one slide's script by sending the slide image straight to the LLM.

    Atomic unit for the batch generator: no separate VLM-notes stage, no
    pipeline-wide vlm_notes list to keep in sync -- one image in, one script
    JSON out.
    """
    image_b64 = base64.b64encode(Path(png_path).read_bytes()).decode("utf-8")
    prompt = build_vision_script_prompt(
        slide=slide,
        style=style,
        target_seconds=target_seconds,
        prev_slide=prev_slide,
        next_slide=next_slide,
        prev_script=prev_script,
    )
    messages = [
        {"role": "system", "content": get_professor_system_prompt()},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"}},
                {"type": "text", "text": prompt},
            ],
        },
    ]
    raw_output = client.chat(messages)
    return _parse_script_json(raw_output, slide.slide_index, slide.slide_number)


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def strip_markdown_json_fence(text: str) -> str:
    """Strip a ```json ... ``` (or bare ```) fence the LLM sometimes wraps JSON in."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        end = len(lines) - 1
        while end > 0 and lines[end].strip() in ("```", ""):
            end -= 1
        # Skip the opening fence line
        inner_lines = lines[1 : end + 1]
        text = "\n".join(inner_lines).strip()
    return text


def _parse_script_json(text: str, slide_index: int, slide_number: int) -> dict:
    """Parse JSON from Claude output, handling markdown code fences."""
    data = json.loads(strip_markdown_json_fence(text))

    # Ensure slide_index and slide_number are present
    data.setdefault("slide_index", slide_index)
    data.setdefault("slide_number", slide_number)

    return data


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_scripts(
    slides: list[SlideRecord],
    vlm_notes: list[dict],
    manifest: SlideManifest,
    scripts_dir: Path,
    client: LLMClient | None = None,
) -> list[SlideScript]:
    """Generate per-slide lecture scripts via the LLM client and save to scripts_dir.

    Processing is sequential (not parallel) because each slide's script
    depends on the previous slide's script for transition context (SCRIPT-02).

    Args:
        slides:      List of SlideRecord objects.
        vlm_notes:   List of VlmNote dicts (one per slide, same order).
        manifest:    SlideManifest with style, target_minutes, slide_count etc.
        scripts_dir: Directory to write script_NNN.json outputs.
        client:      An LLMClient; defaults to lecture_auto.llm.get_llm_client().

    Returns:
        List of validated SlideScript objects (one per slide, in order).
    """
    if client is None:
        client = get_llm_client()

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

        system_prompt = get_professor_system_prompt()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        raw_output = client.chat(messages)
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
