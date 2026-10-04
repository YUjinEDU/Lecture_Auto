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


# ---------------------------------------------------------------------------
# With memory
# ---------------------------------------------------------------------------
from lecture_auto.pipeline.series_memory import load_or_create_memory, summarize_lecture  # noqa: E402
from lecture_auto.schemas.lecture_plan import LectureMemory  # noqa: E402

_MEM = LectureMemory(
    lecture_id="prev", covered_concepts=["프로토타입", "MVP"], running_examples=["배달앱"],
    closing_hook="다음 시간에는 스크럼을 다룹니다", source_sha256="x",
)
_MEM_JSON = json.dumps(
    {"covered_concepts": ["프로토타입"], "running_examples": ["배달앱"], "closing_hook": "스크럼"},
    ensure_ascii=False,
)


def test_memory_block_in_plan_and_first_section_only():
    plan = _plan()
    slides = [_make_slide(n, f"t{n}", "b") for n in (1, 2)]
    assert "[지난 강의 요약" in build_lecture_plan_prompt(slides, "s", "n", 30.0, previous_memory=_MEM)
    first = build_section_prompt(plan, plan.sections[0], slides, None, False, previous_memory=_MEM)
    second = build_section_prompt(plan, plan.sections[1], _sec_slides(), None, False)
    assert "다음 시간에는 스크럼을 다룹니다" in first and "다시 설명하지 말 것" in first
    assert "[지난 강의 요약" not in second


def _client(*replies):
    c = MagicMock()
    c.chat.side_effect = list(replies)
    return c


def test_summarize_ok_and_one_retry_and_two_failures():
    ok = summarize_lecture(_client(_MEM_JSON), "n", {1: "가"})
    assert ok.covered_concepts == ["프로토타입"]
    c = _client("not json", f"```json\n{_MEM_JSON}\n```")
    assert summarize_lecture(c, "n", {1: "가"}).closing_hook == "스크럼"
    assert c.chat.call_count == 2
    with pytest.raises(json.JSONDecodeError):
        summarize_lecture(_client("x", "y"), "n", {1: "가"})


def _write_scripts(work: Path, text: str) -> None:
    (work / "scripts").mkdir(parents=True)
    (work / "scripts" / "script_001.json").write_text(
        json.dumps({"slide_number": 1, "script": text}, ensure_ascii=False), encoding="utf-8"
    )


def test_memory_cache_reuses_until_scripts_change(tmp_path):
    _write_scripts(tmp_path, "원본")
    c = _client(_MEM_JSON, _MEM_JSON)
    load_or_create_memory(c, "prev", "n", tmp_path, "cfg")
    load_or_create_memory(c, "prev", "n", tmp_path, "cfg")
    assert c.chat.call_count == 1
    (tmp_path / "scripts" / "script_001.json").write_text(
        json.dumps({"slide_number": 1, "script": "수정됨"}), encoding="utf-8"
    )
    load_or_create_memory(c, "prev", "n", tmp_path, "cfg")
    assert c.chat.call_count == 2


def test_memory_missing_scripts_is_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="no generated scripts"):
        load_or_create_memory(MagicMock(), "prev", "n", tmp_path, "cfg")


def test_process_lecture_without_previous_never_touches_series_memory(tmp_path):
    from unittest.mock import patch

    import scripts.batch_generate_lectures as b

    item = {"id": "x", "name": "n", "subject": "s", "pdf": tmp_path / "x.pdf"}
    for i, (extra, expect_called) in enumerate((({}, False), ({"previous": "p"}, True))):
        wdir = tmp_path / f"w{i}"  # own work dir: the first run's prep flock stays held by its traceback
        with patch.object(b, "_load_previous_memory", return_value=_MEM) as m, \
             patch.object(b, "_resolve_pdf_input", return_value=tmp_path / "x.pdf"), \
             patch.object(b, "parse_pdf", return_value=[_make_slide(1, "t", "b")]), \
             patch.object(b, "render_slides", return_value=([tmp_path / "1.png"], None)), \
             patch.object(b, "_generate_lecture_plan_cached", side_effect=RuntimeError("stop")) as plan_fn:
            with pytest.raises(RuntimeError, match="stop"):
                b.process_lecture({**item, **extra}, MagicMock(), None, wdir, tmp_path / "o")
        assert m.called is expect_called
        # No `previous`: the plan wrapper is called exactly as before S16 (no new kwarg).
        assert ("previous_memory" in plan_fn.call_args.kwargs) is expect_called
