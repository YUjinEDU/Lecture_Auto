"""Unit tests for lecture_auto.pipeline.lecture_plan. LLM transport is mocked."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lecture_auto.pipeline.lecture_plan import (
    build_lecture_plan_prompt,
    build_section_prompt,
    generate_lecture_plan,
    generate_section_scripts,
    parse_reference_script,
    validate_plan_covers_slides,
)
from lecture_auto.schemas.lecture_plan import CarryForward, LecturePlan, LectureSection
from lecture_auto.schemas.manifest import FontInfo, ShapeRecord, SlideRecord, TextParagraph, TextRun

# S3 base commit (see docs/hardening/stages/S3_new_lecture_inputs/SPEC.md): the
# pre-S3-b lecture_plan.py, used below to prove the reference-args-omitted
# prompt output stayed byte-identical.
_S3_BASE_COMMIT = "5a83baf"
_MAIN_REPO_ROOT = Path("/home/dbsdosdb/workspace/Lecture_Auto")


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


# ---------------------------------------------------------------------------
# Budget overshoot: the model reliably writes past the char budget it is given
# (1.21x median over 48 slides), which is what turned a 28.9-minute plan into
# ~35 minutes of audio.
# ---------------------------------------------------------------------------

def _section_result_json(chars_per_slide: list[int], slide_numbers: list[int]) -> str:
    return json.dumps(
        {
            "section_summary": "요약",
            "carry_forward": {"explained": [], "active_example": "", "next_question": ""},
            "slides": [
                {"slide_number": n, "target_seconds": 10.0, "script": "가" * c}
                for n, c in zip(slide_numbers, chars_per_slide)
            ],
        },
        ensure_ascii=False,
    )


def _plan_and_section():
    plan = LecturePlan(
        lecture_title="t", total_minutes=30.0, opening_context="o", core_message="c",
        recurring_examples=[], sections=[{"title": "s", "slides": [1, 2], "minutes": 1.0, "goal": "g"}],
    )
    return plan, plan.sections[0]


def test_generate_section_scripts_retries_when_over_budget(tmp_path):
    # Budget is the SECTION PLAN's 1.0 min: 60s * 5.7 = 342 chars.
    over = _section_result_json([250, 250], [1, 2])   # 500/342 = 1.46x
    within = _section_result_json([170, 170], [1, 2]) # 340/342 = 0.99x
    client = MagicMock()
    client.chat.side_effect = [over, within]

    plan, section = _plan_and_section()
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG")
    slides = [_make_slide(i, f"t{i}", f"b{i}") for i in (1, 2)]

    result = generate_section_scripts(client, plan, section, slides, [png, png], None, False)

    assert client.chat.call_count == 2
    assert sum(len(s.script) for s in result.slides) == 340


def test_generate_section_scripts_keeps_first_attempt_if_retry_is_worse(tmp_path):
    # 1.46x vs an over-cut 0.29x: the retry is further from 1.0, so it loses.
    over = _section_result_json([250, 250], [1, 2])   # 1.46x
    worse = _section_result_json([50, 50], [1, 2])    # 0.29x
    client = MagicMock()
    client.chat.side_effect = [over, worse]

    plan, section = _plan_and_section()
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG")
    slides = [_make_slide(i, f"t{i}", f"b{i}") for i in (1, 2)]

    result = generate_section_scripts(client, plan, section, slides, [png, png], None, False)
    assert sum(len(s.script) for s in result.slides) == 500  # the first attempt, not the over-cut retry


def test_generate_section_scripts_does_not_retry_when_within_budget(tmp_path):
    client = MagicMock()
    client.chat.side_effect = [_section_result_json([170, 170], [1, 2])]  # 0.99x

    plan, section = _plan_and_section()
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG")
    slides = [_make_slide(i, f"t{i}", f"b{i}") for i in (1, 2)]

    generate_section_scripts(client, plan, section, slides, [png, png], None, False)
    assert client.chat.call_count == 1


def test_budget_is_measured_against_the_plan_not_the_models_own_target_seconds(tmp_path):
    # The model hands itself 10s/slide where the plan allots 1.0 min for the
    # section. Measured against its own numbers 114 chars looks perfect; against
    # the plan's 342 it is 0.33x and must trigger a retry.
    starved = _section_result_json([57, 57], [1, 2])
    full = _section_result_json([170, 170], [1, 2])
    client = MagicMock()
    client.chat.side_effect = [starved, full]

    plan, section = _plan_and_section()
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG")
    slides = [_make_slide(i, f"t{i}", f"b{i}") for i in (1, 2)]

    result = generate_section_scripts(client, plan, section, slides, [png, png], None, False)
    assert client.chat.call_count == 2
    assert sum(len(s.script) for s in result.slides) == 340


# ---------------------------------------------------------------------------
# S3-b: parse_reference_script (required test 1)
# ---------------------------------------------------------------------------

_SAMPLE_REFERENCE_MD = """\
# 어느 강의 · 강의 스크립트

- 대상 자료: sample.pptx (5슬라이드)
- 구성: 도입 -> 본문 -> 마무리
- 표기: **[슬라이드 N]** 전환 지점, *(⏱ 누적 시간)*, *(연출)* 화면 조작 안내

---

## Part 0. 도입 *(⏱ 0:00-1:00)*

**[슬라이드 1] 표지**

안녕하세요. *(연출: 화면 전환)*
반갑습니다.

**[슬라이드 2] 본문** *(⏱ 1:00-2:00)*

본문 설명입니다.

### 소단원: 본문 안의 하위 제목 *(⏱ 1:30-2:00)*

**[슬라이드 3–4] 범위 예시**

3번과 4번의 공통 설명입니다.

---

## Part 1. 마무리

**[슬라이드 5] 마무리**

정리합니다.
"""


def test_parse_reference_script_basic():
    result = parse_reference_script(_SAMPLE_REFERENCE_MD)

    # 마커 없는 머리말(제목/대상 자료/구성/표기)은 무시된다.
    assert set(result.keys()) == {1, 2, 3, 4, 5}
    assert "sample.pptx" not in "".join(result.values())

    # 이탤릭 괄호 주석(*(⏱ ...)*, *(연출...)*)은 제거된다.
    assert "⏱" not in result[1]
    assert "연출" not in result[1]
    assert "안녕하세요" in result[1]
    assert "반갑습니다" in result[1]

    assert result[2].strip() == "본문 설명입니다."
    # A "### " sub-heading between two slide markers ends the previous
    # slide's block (same intent as "## "/"---") instead of leaking into it.
    assert "소단원" not in result[2]

    # 범위 마커([슬라이드 3–4])는 두 슬라이드 모두에 같은 설명을 배정한다.
    assert result[3] == result[4]
    assert "공통 설명" in result[3]

    assert result[5].strip() == "정리합니다."


def test_parse_reference_script_real_files():
    """Data-format regression guard: parse the 4 real reference scripts and
    make sure the slide numbers form a non-empty, 1-based increasing set.
    Skips when data/PDF isn't present (gitignored -- only in the main repo
    checkout, not this worktree)."""
    real_dir = _MAIN_REPO_ROOT / "data" / "PDF" / "종합설계 2026"
    if not real_dir.is_dir():
        pytest.skip(f"{real_dir} not present in this worktree (gitignored data)")

    md_files = sorted(real_dir.glob("*_강의스크립트.md"))
    assert len(md_files) == 4
    for md_path in md_files:
        notes = parse_reference_script(md_path.read_text(encoding="utf-8"))
        assert len(notes) > 0, md_path
        assert sorted(notes) == list(range(1, max(notes) + 1)), md_path


# ---------------------------------------------------------------------------
# S3-b: reference_notes / reference_outline optional args (required tests 3, 4)
# ---------------------------------------------------------------------------

def _load_base_build_section_prompt():
    """The pre-S3-b build_section_prompt, loaded straight from the S3 base
    commit -- used as the "current implementation" expected value the SPEC
    asks for (test 3), without hand-duplicating the whole function body."""
    src = subprocess.run(
        ["git", "show", f"{_S3_BASE_COMMIT}:lecture_auto/pipeline/lecture_plan.py"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, check=True,
    ).stdout
    ns: dict = {}
    exec(compile(src, "lecture_plan_s3_base.py", "exec"), ns)  # noqa: S102
    return ns["build_section_prompt"]


def test_build_section_prompt_reference_notes_none_matches_baseline():
    plan = _plan()
    section = plan.sections[1]
    slides = [_make_slide(4, "관찰", "관찰 방법"), _make_slide(5, "인터뷰", "인터뷰 방법")]
    carry_forward = CarryForward(explained=["사용자 중심성"], active_example="쓰레기 무단투기", next_question="어떻게 관찰하는가")

    got = build_section_prompt(plan, section, slides, carry_forward, is_last_section=False, reference_notes=None)

    baseline_fn = _load_base_build_section_prompt()
    expected = baseline_fn(plan, section, slides, carry_forward, is_last_section=False)

    assert got == expected


def test_build_section_prompt_reference_notes_scopes_to_section():
    plan = _plan()
    section = plan.sections[1]  # slides [4, 5]
    slides = [_make_slide(4, "관찰", "관찰 방법"), _make_slide(5, "인터뷰", "인터뷰 방법")]
    reference_notes = {
        1: "다른 섹션(도입) 슬라이드의 참고 설명 -- 포함되면 안 됨",
        4: "관찰 슬라이드 참고 설명",
        5: "인터뷰 슬라이드 참고 설명",
    }

    prompt = build_section_prompt(
        plan, section, slides, None, is_last_section=False, reference_notes=reference_notes
    )

    assert "관찰 슬라이드 참고 설명" in prompt
    assert "인터뷰 슬라이드 참고 설명" in prompt
    assert "다른 섹션(도입) 슬라이드의 참고 설명" not in prompt
    assert "그대로 복사하지 말고" in prompt


def test_build_lecture_plan_prompt_reference_outline_none_matches_baseline():
    slides = [_make_slide(1, "표지", "AI활용현업문제해결"), _make_slide(2, "목차", "오늘의 순서")]

    got = build_lecture_plan_prompt(slides, "AI활용현업문제해결", "디자인씽킹 개요", 30.0, reference_outline=None)

    src = subprocess.run(
        ["git", "show", f"{_S3_BASE_COMMIT}:lecture_auto/pipeline/lecture_plan.py"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, check=True,
    ).stdout
    ns: dict = {}
    exec(compile(src, "lecture_plan_s3_base.py", "exec"), ns)  # noqa: S102
    expected = ns["build_lecture_plan_prompt"](slides, "AI활용현업문제해결", "디자인씽킹 개요", 30.0)

    assert got == expected
