"""Whole-lecture planning + section-based script generation.

Generating one slide's script at a time (script_gen.build_vision_script_prompt)
only ever sees the previous/next slide titles and the last 100 chars of the
previous script -- not enough to know which slides share a running example,
which slide should get 90 seconds vs. 15, or that a slide is a "already
covered this, move on" recap. This module does it in two passes instead:

1. generate_lecture_plan() looks at every slide once and decides the section
   breakdown, recurring examples, and per-section time budget.
2. generate_section_scripts() generates one section's slides (4-8 at a time)
   as a single continuous script, carrying forward what's already been
   explained so later sections don't reintroduce it.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from lecture_auto.llm import LLMClient
from lecture_auto.pipeline.script_gen import (
    _extract_all_text,
    _extract_slide_title,
    get_professor_system_prompt,
    strip_markdown_json_fence,
)
from lecture_auto.schemas.lecture_plan import (
    CarryForward,
    LecturePlan,
    LectureSection,
    SectionScriptResult,
)
from lecture_auto.schemas.manifest import SlideRecord

logger = logging.getLogger(__name__)

_PLAN_SYSTEM_PROMPT = (
    "당신은 대학 강의를 섹션 단위로 설계하는 커리큘럼 설계자입니다. "
    "제공된 슬라이드 전체를 한 번에 검토하여 강의의 이야기 흐름, 섹션 구성, "
    "반복해서 사용할 사례, 섹션별 시간 배분을 결정하세요.\n\n"
    "모든 슬라이드에 동일한 시간을 배분하지 마세요. 다음을 기준으로 삼되 "
    "섹션별 minutes의 합이 전체 목표 시간과 맞아야 합니다:\n"
    "- 표지/섹션 제목 슬라이드: 10~20초\n"
    "- 이미 설명한 내용을 반복/요약하는 슬라이드: 15~25초\n"
    "- 일반 개념 설명: 30~45초\n"
    "- 핵심 도표·사례: 50~90초\n"
    "- 마지막 정리: 40~60초\n\n"
    "섹션은 하나의 이야기 흐름이 이어지도록 4~8장 슬라이드씩 묶으세요. "
    "모든 슬라이드는 정확히 하나의 섹션에만 속해야 하고, 슬라이드 번호를 빠뜨리면 안 됩니다."
)


def build_lecture_plan_prompt(
    slides: list[SlideRecord],
    subject: str,
    lecture_name: str,
    total_minutes: float,
) -> str:
    lines: list[str] = []
    lines.append(f"[과목명] {subject}")
    lines.append(f"[강의주제] {lecture_name}")
    lines.append(f"[전체 목표 시간] {total_minutes}분")
    lines.append(f"[전체 슬라이드 수] {len(slides)}장 (슬라이드 번호 1~{len(slides)})")
    lines.append("")
    lines.append("[슬라이드 목록]")
    for slide in slides:
        title = _extract_slide_title(slide)
        text = _extract_all_text(slide)
        lines.append(f"- 슬라이드 {slide.slide_number} [{title}]: {text}")
    lines.append("")
    lines.append("[출력 형식] 아래 JSON 형식으로만 출력하세요. 다른 텍스트는 포함하지 마세요.")
    lines.append(
        json.dumps(
            {
                "lecture_title": "<강의 제목>",
                "total_minutes": total_minutes,
                "opening_context": "<지난 시간/과제 연결 등 도입부 맥락>",
                "core_message": "<이 강의를 통해 학생이 얻어가야 할 핵심 메시지>",
                "recurring_examples": [
                    {"name": "<사례 이름>", "purpose": "<이 사례로 설명하려는 것>", "slides": [1, 2, 3]}
                ],
                "sections": [
                    {"title": "<섹션 제목>", "slides": [1, 2, 3], "minutes": 3.0, "goal": "<이 섹션의 목표>"}
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return "\n".join(lines)


def generate_lecture_plan(
    client: LLMClient,
    slides: list[SlideRecord],
    subject: str,
    lecture_name: str,
    total_minutes: float,
) -> LecturePlan:
    prompt = build_lecture_plan_prompt(slides, subject, lecture_name, total_minutes)
    messages = [
        {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    raw = client.chat(messages)
    data = json.loads(strip_markdown_json_fence(raw))
    plan = LecturePlan(**data)
    validate_plan_covers_slides(plan, len(slides))
    return plan


def validate_plan_covers_slides(plan: LecturePlan, slide_count: int) -> None:
    """Every slide 1..slide_count must belong to exactly one section.

    A dropped or duplicated slide here means a missing or doubled-up wav/png
    pairing much later in assemble_video -- fail loudly now instead.
    """
    owner: dict[int, str] = {}
    for section in plan.sections:
        for n in section.slides:
            if n in owner:
                raise ValueError(
                    f"lecture plan assigns slide {n} to both {owner[n]!r} and {section.title!r}"
                )
            owner[n] = section.title
    missing = [n for n in range(1, slide_count + 1) if n not in owner]
    if missing:
        raise ValueError(f"lecture plan is missing slides: {missing}")


def build_section_prompt(
    plan: LecturePlan,
    section: LectureSection,
    slides: list[SlideRecord],
    carry_forward: CarryForward | None,
    is_last_section: bool,
) -> str:
    lines: list[str] = []
    lines.append("당신은 실제 대학 강의를 진행하는 교수님의 강의 대본을 작성하는 전문 AI입니다.")
    lines.append(
        "아래 섹션에 포함된 여러 슬라이드를 하나로 이어지는 강의로 작성하세요. "
        "슬라이드 하나하나를 독립된 발표로 다루지 마세요."
    )
    lines.append("")
    lines.append(f"[강의 전체 제목] {plan.lecture_title}")
    lines.append(f"[강의 핵심 메시지] {plan.core_message}")
    if plan.recurring_examples:
        lines.append("[강의 전체에서 반복 사용하는 사례]")
        for ex in plan.recurring_examples:
            lines.append(f"- {ex.name}: {ex.purpose} (슬라이드 {ex.slides})")
    lines.append("")
    lines.append(f"[이번 섹션] {section.title} (목표 {section.minutes:.1f}분, 목적: {section.goal})")
    lines.append(f"[이번 섹션 슬라이드 번호] {section.slides}")
    lines.append("")

    if carry_forward is not None and (carry_forward.explained or carry_forward.active_example):
        lines.append("[이전 섹션까지 진행 상황]")
        if carry_forward.explained:
            lines.append(f"- 이미 설명한 내용 (다시 소개하지 말 것): {', '.join(carry_forward.explained)}")
        if carry_forward.active_example:
            lines.append(f"- 계속 이어가는 사례: {carry_forward.active_example}")
        if carry_forward.next_question:
            lines.append(f"- 이번 섹션에서 답해야 할 질문: {carry_forward.next_question}")
        lines.append("")

    lines.append("[섹션 작성 원칙]")
    lines.append("- 섹션의 첫 슬라이드에서만 주제를 도입한다. 중간 슬라이드는 인사나 새 도입 없이 바로 설명을 잇는다.")
    lines.append("- 슬라이드 사이 전환이 필요하면 그 슬라이드의 script 문장 안에 자연스럽게 포함한다 (별도 필드로 만들지 않는다).")
    lines.append(
        "- 각 슬라이드의 target_seconds는 슬라이드 성격에 맞게 다르게 준다: "
        "표지/섹션 제목 10~20초, 반복/요약 슬라이드 15~25초, 일반 개념 30~45초, 핵심 도표·사례 50~90초."
    )
    lines.append(
        "- 각 슬라이드 script의 글자 수는 target_seconds * 7자(초당 약 7자)를 기준으로 ±10% 이내로 작성한다. "
        "시간을 채우려고 같은 말을 반복하거나 억지로 늘리지 않는다."
    )
    if is_last_section:
        lines.append(
            "- 이 섹션은 강의의 마지막 섹션이다. 마지막 슬라이드는 다음 슬라이드를 예고하지 말고 "
            "강의 핵심과 학생이 기억해야 할 행동을 정리한다."
        )
    lines.append("")

    lines.append("[이번 섹션 슬라이드별 추출 텍스트 (첨부 이미지와 함께 참고)]")
    for slide in slides:
        lines.append(f"- 슬라이드 {slide.slide_number}: {_extract_all_text(slide)}")
    lines.append("")

    lines.append("[출력 형식] 아래 JSON 형식으로만 출력하세요. 다른 텍스트는 포함하지 마세요.")
    lines.append(
        json.dumps(
            {
                "section_summary": "<이번 섹션에서 실제로 설명한 내용 한두 문장>",
                "carry_forward": {
                    "explained": ["<이번 섹션에서 새로 설명한 핵심 개념들>"],
                    "active_example": "<다음 섹션에도 이어갈 사례, 없으면 빈 문자열>",
                    "next_question": "<다음 섹션에서 답해야 할 질문, 없으면 빈 문자열>",
                },
                "slides": [
                    {"slide_number": n, "target_seconds": 30.0, "script": "<강의 스크립트>"}
                    for n in section.slides
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return "\n".join(lines)


def generate_section_scripts(
    client: LLMClient,
    plan: LecturePlan,
    section: LectureSection,
    slides: list[SlideRecord],
    png_paths: list[Path],
    carry_forward: CarryForward | None,
    is_last_section: bool,
) -> SectionScriptResult:
    """Generate one section's slides as a single continuous script.

    ``slides``/``png_paths`` must be the slides belonging to ``section``, in
    ``section.slides`` order -- each slide's image is attached so small text
    and tables the extracted text might miss still reach the model.
    """
    prompt_text = build_section_prompt(plan, section, slides, carry_forward, is_last_section)

    content: list[dict] = [{"type": "text", "text": prompt_text}]
    for slide, png_path in zip(slides, png_paths):
        image_b64 = base64.b64encode(Path(png_path).read_bytes()).decode("utf-8")
        content.append({"type": "text", "text": f"[슬라이드 {slide.slide_number} 이미지]"})
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"}}
        )

    messages = [
        {"role": "system", "content": get_professor_system_prompt()},
        {"role": "user", "content": content},
    ]
    raw = client.chat(messages)
    data = json.loads(strip_markdown_json_fence(raw))
    return SectionScriptResult(**data)
