"""Unit tests for lecture_auto.pipeline.lecture_plan. LLM transport is mocked."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lecture_auto.pipeline.lecture_plan import (
    build_lecture_plan_prompt,
    build_section_prompt,
    generate_lecture_plan,
    generate_section_scripts,
    validate_plan_covers_slides,
)
from lecture_auto.schemas.lecture_plan import CarryForward, LecturePlan, LectureSection
from lecture_auto.schemas.manifest import FontInfo, ShapeRecord, SlideRecord, TextParagraph, TextRun


def _make_slide(number: int, title: str, body: str) -> SlideRecord:
    def shape(text: str, role: str) -> ShapeRecord:
        return ShapeRecord(
            shape_id=1,
            name="box",
            z_order=0,
            left=0,
            top=0,
            width=10,
            height=10,
            content_source="text",
            has_text=True,
            text_role=role,
            paragraphs=[TextParagraph(full_text=text, runs=[TextRun(text=text, font=FontInfo())])],
        )

    return SlideRecord(
        slide_index=number - 1,
        slide_number=number,
        png_path=f"slide_{number:03d}.png",
        shapes=[shape(title, "title"), shape(body, "body")],
    )


def _valid_plan_dict() -> dict:
    return {
        "lecture_title": "디자인씽킹 개요",
        "total_minutes": 30.0,
        "opening_context": "지난 시간 과제 연결",
        "core_message": "사용자 관점에서 문제를 재정의한다",
        "recurring_examples": [{"name": "쓰레기 무단투기", "purpose": "공감 설명", "slides": [4, 5]}],
        "sections": [
            {"title": "도입", "slides": [1, 2, 3], "minutes": 5.0, "goal": "필요성 이해"},
            {"title": "공감", "slides": [4, 5], "minutes": 10.0, "goal": "관찰 방법 이해"},
        ],
    }


# ---------------------------------------------------------------------------
# build_lecture_plan_prompt
# ---------------------------------------------------------------------------

def test_build_lecture_plan_prompt_includes_all_slides():
    slides = [_make_slide(1, "표지", "AI활용현업문제해결"), _make_slide(2, "목차", "오늘의 순서")]
    prompt = build_lecture_plan_prompt(slides, "AI활용현업문제해결", "디자인씽킹 개요", 30.0)
    assert "슬라이드 1" in prompt
    assert "슬라이드 2" in prompt
    assert "AI활용현업문제해결" in prompt
    assert "30.0" in prompt


# ---------------------------------------------------------------------------
# validate_plan_covers_slides
# ---------------------------------------------------------------------------

def test_validate_plan_covers_slides_passes_when_complete():
    plan = LecturePlan(**_valid_plan_dict())
    validate_plan_covers_slides(plan, slide_count=5)  # should not raise


def test_validate_plan_covers_slides_raises_on_missing_slide():
    plan = LecturePlan(**_valid_plan_dict())
    with pytest.raises(ValueError, match="missing slides"):
        validate_plan_covers_slides(plan, slide_count=6)


def test_validate_plan_covers_slides_raises_on_duplicate_slide():
    data = _valid_plan_dict()
    data["sections"][1]["slides"] = [3, 4, 5]  # 3 now in both sections
    plan = LecturePlan(**data)
    with pytest.raises(ValueError, match="both"):
        validate_plan_covers_slides(plan, slide_count=5)


# ---------------------------------------------------------------------------
# generate_lecture_plan
# ---------------------------------------------------------------------------

def test_generate_lecture_plan_parses_response():
    slides = [_make_slide(i, f"제목{i}", f"본문{i}") for i in range(1, 6)]
    client = MagicMock()
    client.chat.return_value = json.dumps(_valid_plan_dict(), ensure_ascii=False)

    plan = generate_lecture_plan(client, slides, "AI활용현업문제해결", "디자인씽킹 개요", 30.0)

    assert isinstance(plan, LecturePlan)
    assert plan.lecture_title == "디자인씽킹 개요"
    assert len(plan.sections) == 2


def test_generate_lecture_plan_strips_markdown_fence():
    slides = [_make_slide(i, f"제목{i}", f"본문{i}") for i in range(1, 6)]
    client = MagicMock()
    client.chat.return_value = f"```json\n{json.dumps(_valid_plan_dict(), ensure_ascii=False)}\n```"

    plan = generate_lecture_plan(client, slides, "AI활용현업문제해결", "디자인씽킹 개요", 30.0)
    assert plan.lecture_title == "디자인씽킹 개요"


def test_generate_lecture_plan_raises_on_incomplete_coverage():
    slides = [_make_slide(i, f"제목{i}", f"본문{i}") for i in range(1, 8)]  # 7 slides, plan only covers 5
    client = MagicMock()
    client.chat.return_value = json.dumps(_valid_plan_dict(), ensure_ascii=False)

    with pytest.raises(ValueError, match="missing slides"):
        generate_lecture_plan(client, slides, "AI활용현업문제해결", "디자인씽킹 개요", 30.0)


# ---------------------------------------------------------------------------
# build_section_prompt
# ---------------------------------------------------------------------------

def _plan() -> LecturePlan:
    return LecturePlan(**_valid_plan_dict())


def test_build_section_prompt_includes_carry_forward_and_bans_reintroduction():
    plan = _plan()
    section = plan.sections[1]
    slides = [_make_slide(4, "관찰", "관찰 방법"), _make_slide(5, "인터뷰", "인터뷰 방법")]
    carry_forward = CarryForward(explained=["사용자 중심성"], active_example="쓰레기 무단투기", next_question="어떻게 관찰하는가")

    prompt = build_section_prompt(plan, section, slides, carry_forward, is_last_section=False)

    assert "사용자 중심성" in prompt
    assert "다시 소개하지 말 것" in prompt
    assert "쓰레기 무단투기" in prompt
    assert "다음 슬라이드를 예고하지 말고" not in prompt


def test_build_section_prompt_last_section_gets_wrap_up_instruction():
    plan = _plan()
    section = plan.sections[1]
    slides = [_make_slide(4, "관찰", "관찰 방법"), _make_slide(5, "인터뷰", "인터뷰 방법")]

    prompt = build_section_prompt(plan, section, slides, None, is_last_section=True)

    assert "다음 슬라이드를 예고하지 말고" in prompt


# ---------------------------------------------------------------------------
# generate_section_scripts
# ---------------------------------------------------------------------------

def test_generate_section_scripts_parses_response(tmp_path: Path):
    plan = _plan()
    section = plan.sections[0]
    slides = [_make_slide(n, f"제목{n}", f"본문{n}") for n in section.slides]

    png_paths = []
    for n in section.slides:
        p = tmp_path / f"slide_{n:03d}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        png_paths.append(p)

    response = {
        "section_summary": "도입부를 설명했다",
        "carry_forward": {"explained": ["문제 정의"], "active_example": "", "next_question": ""},
        "slides": [{"slide_number": n, "target_seconds": 20.0, "script": f"슬라이드 {n} 대본입니다."} for n in section.slides],
    }
    client = MagicMock()
    client.chat.return_value = json.dumps(response, ensure_ascii=False)

    result = generate_section_scripts(client, plan, section, slides, png_paths, None, is_last_section=False)

    assert result.section_summary == "도입부를 설명했다"
    assert [s.slide_number for s in result.slides] == section.slides

    # one image content part per slide reached the client
    sent_messages = client.chat.call_args[0][0]
    user_content = sent_messages[1]["content"]
    image_parts = [c for c in user_content if c.get("type") == "image_url"]
    assert len(image_parts) == len(section.slides)
