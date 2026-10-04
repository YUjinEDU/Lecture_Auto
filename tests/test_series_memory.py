"""S16a: series memory. Golden section captures master's (pre-S16) outputs byte for byte."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lecture_auto.pipeline.lecture_plan import build_lecture_plan_prompt, build_section_prompt
from lecture_auto.schemas.lecture_plan import CarryForward, LecturePlan
from tests.test_lecture_plan import _make_slide, _valid_plan_dict

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "s16_golden"


def _plan() -> LecturePlan:
    return LecturePlan(**_valid_plan_dict())


def _sec_slides():
    return [_make_slide(4, "관찰", "관찰 방법"), _make_slide(5, "인터뷰", "인터뷰 방법")]


def _golden_outputs(tmp_path: Path) -> dict[str, str]:
    """Every no-`previous` prompt string and cache key the batch can produce."""
    from scripts.batch_generate_lectures import (
        _generate_lecture_plan_cached,
        _generate_section_scripts_cached,
    )

    plan = _plan()
    cf = CarryForward(explained=["사용자 중심성"], active_example="쓰레기 무단투기", next_question="어떻게 관찰하는가")
    slides = [_make_slide(1, "표지", "AI활용현업문제해결"), _make_slide(2, "목차", "오늘의 순서")]
    notes = {4: "관찰 참고", 5: "인터뷰 참고"}
    out = {
        "plan_plain": build_lecture_plan_prompt(slides, "과목", "강의", 42.4),
        "plan_ref": build_lecture_plan_prompt(slides, "과목", "강의", 42.4, reference_outline="구성: A / B"),
        "sec_first": build_section_prompt(plan, plan.sections[0], slides, None, False),
        "sec_cf_notes": build_section_prompt(
            plan, plan.sections[1], _sec_slides(), cf, False, reference_notes=notes
        ),
        "sec_last_correction": build_section_prompt(
            plan, plan.sections[1], _sec_slides(), cf, True, correction="분량 맞춰", reference_notes=notes
        ),
    }

    # Cache keys, as written by the real cached wrappers with the LLM mocked.
    llm = MagicMock()
    llm.text_model, llm.vlm_model = "t", "v"
    plan_path = tmp_path / "p" / "lecture_plan.json"
    llm.chat.return_value = json.dumps(_valid_plan_dict(), ensure_ascii=False)
    sl5 = [_make_slide(n, f"t{n}", f"b{n}") for n in range(1, 6)]
    _generate_lecture_plan_cached(llm, sl5, "과목", "강의", plan_path, "구성: A / B")
    out["key_plan"] = (plan_path.parent / "lecture_plan.json.hash").read_text().strip()

    png = tmp_path / "s.png"
    png.write_bytes(b"png")
    sec = plan.sections[1]
    sec_resp = {
        "section_summary": "s",
        "carry_forward": {"explained": [], "active_example": "", "next_question": ""},
        "slides": [{"slide_number": n, "target_seconds": 30.0, "script": "가" * 210} for n in sec.slides],
    }
    llm.chat.return_value = json.dumps(sec_resp, ensure_ascii=False)
    sec_path = tmp_path / "sec" / "section_001.json"
    _generate_section_scripts_cached(
        llm, plan, sec, _sec_slides(), [png, png], cf, False, sec_path, notes
    )
    out["key_section"] = (sec_path.parent / "section_001.json.hash").read_text().strip()
    return out


@pytest.mark.parametrize("name", ["plan_plain", "plan_ref", "sec_first", "sec_cf_notes",
                                  "sec_last_correction", "key_plan", "key_section"])
def test_golden_no_previous_is_byte_identical_to_master(tmp_path, name):
    got = _golden_outputs(tmp_path)[name]
    assert got == (_GOLDEN / f"{name}.txt").read_text(encoding="utf-8")
