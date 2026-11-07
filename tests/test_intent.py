"""Intent pacing, input provenance, and script cache contracts."""
import json
from unittest.mock import MagicMock

import pytest

from lecture_auto.pipeline.intent import (
    IntentBudgetError,
    IntentDraftInput,
    draft_intent,
    repair_draft,
)
from lecture_auto.pipeline.lecture_plan import (
    build_lecture_plan_prompt,
    build_section_prompt,
)
from lecture_auto.production.batch import (
    _generate_lecture_plan_cached,
    _generate_section_scripts_cached,
    _write_section_scripts,
)
from lecture_auto.production.intent import (
    EditedIntentError,
    generate_intent_job,
    load_intent,
    save_intent,
)
from lecture_auto.schemas.intent import IntentSheet, SlideIntent
from lecture_auto.schemas.lecture_plan import LecturePlan
from tests.test_lecture_plan import _make_slide


@pytest.fixture
def source():
    return IntentDraftInput(
        lecture_id="intent_test", subject="설계", name="검증", target_minutes=5,
        slides=[_make_slide(1, "표지", "설계"), _make_slide(2, "분해", "모듈"),
                _make_slide(3, "적용", "실습")],
        visual_notes={2: "관계를 선으로 표시"},
    )


def reply():
    return json.dumps({"slides": [
        {"slide": 1, "thesis": "설계 문제를 던진다", "role": "도입", "importance": 1, "seconds": 20},
        {"slide": 2, "thesis": "변경 이유로 모듈을 나눈다", "role": "개념", "importance": 3,
         "seconds": 160, "pitfall": "기능별 분해와 혼동", "example": "주문과 결제"},
        {"slide": 3, "thesis": "결제 변경을 독립시킨다", "role": "예시", "importance": 2, "seconds": 120},
    ]}, ensure_ascii=False)


def sheet(source):
    client = MagicMock()
    client.chat.return_value = reply()
    return draft_intent(client, source)


def plan_reply():
    return json.dumps({
        "lecture_title": "설계", "total_minutes": 99, "opening_context": "문제",
        "core_message": "변경 격리", "sections": [
            {"title": "분해", "slides": [1, 2, 3], "minutes": 99, "goal": "분해 기준"},
        ],
    })


def section_reply():
    return json.dumps({
        "section_summary": "분해", "carry_forward": {},
        "slides": [{"slide_number": n, "target_seconds": 999, "script": "가" * length}
                   for n, length in [(1, 150), (2, 1200), (3, 900)]],
    })


def test_draft_repairs_coverage_ranges_and_bounded_total(source):
    raw = json.dumps({"slides": [
        {"slide": 1, "thesis": "시작", "role": "도입", "importance": 9, "seconds": 900},
        {"slide": 1, "thesis": "중복", "seconds": 99},
        {"slide": 3, "thesis": "", "role": "잘못된 역할", "importance": -1, "seconds": -40},
        {"slide": 88, "thesis": "범위 밖", "seconds": 50},
    ]})
    result = repair_draft(f"```json\n{raw}\n```", source)
    assert [s.slide for s in result] == [1, 2, 3]
    assert sum(s.seconds for s in result) == 300
    assert 10 <= result[0].seconds <= 30
    assert [(s.thesis, s.importance) for s in result] == [("시작", 3), ("분해", 2), ("적용", 1)]
    assert result[2].role == "기타"
    assert all(10 <= s.seconds <= 600 for s in result)


@pytest.mark.parametrize("minutes", [0.1, 100])
def test_impossible_duration_reports_feasible_range(source, minutes):
    with pytest.raises(IntentBudgetError, match="가능 범위"):
        repair_draft(reply(), source.model_copy(update={"target_minutes": minutes}))


def test_draft_uses_one_text_call_and_hashes_all_inputs(source):
    client = MagicMock()
    client.chat.return_value = reply()
    first = draft_intent(client, source)
    assert client.chat.call_count == 1
    prompt = client.chat.call_args.args[0][0]["content"]
    assert all(s.shapes[0].paragraphs[0].full_text in prompt for s in source.slides)
    assert source.visual_notes[2] in prompt
    second = draft_intent(client, source.model_copy(update={"visual_notes": {2: "다른 시각 분석"}}))
    assert first.input_hash != second.input_hash
    assert first.content_hash == second.content_hash


def test_content_hash_changes_on_professor_edit_but_not_metadata(source):
    original = sheet(source)
    metadata = original.model_copy(update={"edited": True, "input_hash": "new provenance"})
    assert original.content_hash == metadata.content_hash
    changed = original.model_copy(update={"slides": [
        original.slides[0].model_copy(update={"thesis": "다른 도입"}), *original.slides[1:],
    ]})
    assert changed.content_hash != original.content_hash


def test_edited_sheet_requires_force_before_any_llm_call(source, tmp_path):
    original = sheet(source).model_copy(update={"edited": True})
    save_intent(tmp_path, original)
    client = MagicMock()
    client.chat.return_value = reply()
    with pytest.raises(EditedIntentError):
        generate_intent_job(client, source, tmp_path)
    client.chat.assert_not_called()
    assert load_intent(tmp_path) == original
    forced = generate_intent_job(client, source, tmp_path, force=True)
    assert not forced.edited
    assert load_intent(tmp_path) == forced


def test_prompts_forward_selected_intents_and_seconds(source):
    intent = sheet(source)
    plan = LecturePlan.model_validate_json(plan_reply())
    plan_prompt = build_lecture_plan_prompt(source.slides, "설계", "검증", 5, intent_sheet=intent)
    section = plan.sections[0].model_copy(update={"slides": [2]})
    section_prompt = build_section_prompt(plan, section, source.slides[1:2], None, False, intent_sheet=intent)
    for prompt in (plan_prompt, section_prompt):
        assert intent.slides[1].thesis in prompt
        assert f'"seconds": {intent.slides[1].seconds}' in prompt
        assert f'"role": "{intent.slides[1].role}"' in prompt
        assert intent.slides[1].pitfall in prompt and intent.slides[1].example in prompt
    assert intent.slides[0].thesis not in section_prompt


def test_intent_changes_plan_and_section_caches_and_overrides_time(source, tmp_path):
    intent = sheet(source)
    client = MagicMock(text_model="text", vlm_model="vision")
    client.chat.return_value = plan_reply()
    plan_path = tmp_path / "plan.json"
    plan = _generate_lecture_plan_cached(client, source.slides, "설계", "검증", plan_path, intent_sheet=intent)
    assert plan.total_minutes == 5 and plan.sections[0].minutes == 5
    key = plan_path.with_suffix(".json.hash").read_text()
    _generate_lecture_plan_cached(client, source.slides, "설계", "검증", plan_path, intent_sheet=intent)
    assert client.chat.call_count == 1
    changed = intent.model_copy(update={"slides": [
        intent.slides[0].model_copy(update={"seconds": 25}),
        intent.slides[1].model_copy(update={"seconds": 155}), intent.slides[2],
    ]})
    _generate_lecture_plan_cached(client, source.slides, "설계", "검증", plan_path, intent_sheet=changed)
    assert client.chat.call_count == 2
    assert key != plan_path.with_suffix(".json.hash").read_text()
    png = tmp_path / "slide.png"
    png.write_bytes(b"png")
    sec_path = tmp_path / "section.json"
    client.chat.return_value = section_reply()
    client.reset_mock()
    args = (client, plan, plan.sections[0], source.slides, [png] * 3, None, True, sec_path)
    result = _generate_section_scripts_cached(*args, intent_sheet=intent)
    assert [s.target_seconds for s in result.slides] == [20, 160, 120]
    _generate_section_scripts_cached(*args, intent_sheet=intent)
    assert client.chat.call_count == 1
    _generate_section_scripts_cached(*args, intent_sheet=changed)
    assert client.chat.call_count == 2


def test_new_intent_preserves_hand_edited_script(source, tmp_path):
    from lecture_auto.schemas.lecture_plan import SectionScriptResult
    result = SectionScriptResult.model_validate_json(section_reply())
    tmp_path.mkdir(exist_ok=True)
    scripts = {}
    _write_section_scripts(result, tmp_path, scripts)
    path = tmp_path / "script_002.json"
    edited = json.loads(path.read_text())
    edited["script"] = "교수자가 직접 작성한 설명"
    path.write_text(json.dumps(edited))
    replacement = result.model_copy(update={"slides": [
        s.model_copy(update={"script": "새 의도 대본", "target_seconds": 55}) for s in result.slides
    ]})
    _write_section_scripts(replacement, tmp_path, scripts)
    assert scripts[2]["script"] == edited["script"]
    assert scripts[1]["script"] == "새 의도 대본"


def test_schema_rejects_duplicate_slide_and_bad_ranges(source):
    from pydantic import ValidationError
    original = sheet(source)
    with pytest.raises(ValidationError):
        IntentSheet.model_validate({**original.model_dump(), "slides": [original.slides[0]] * 2})
    with pytest.raises(ValidationError):
        SlideIntent(slide=1, thesis="설계", role="개념", importance=4, seconds=1)
