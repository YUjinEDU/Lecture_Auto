"""Review, conservative adoption, and persistent script ownership contracts."""
import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from lecture_auto.pipeline.critic import (
    CriticSlide,
    SlideScores,
    failures_for,
    refine_section,
    review_section,
    validate_rewrite,
)
from lecture_auto.pipeline.script_gen import SPEECH_CHARS_PER_SECOND
from lecture_auto.pipeline.style_profile import StyleProfile
from lecture_auto.production.batch import _hand_edited, _write_section_scripts
from lecture_auto.production.critic import CriticContext, refine_cached, write_report
from lecture_auto.schemas.lecture_plan import SectionScriptResult, SectionSlideScript
from tests.test_lecture_plan import _make_slide

ORIGINAL = "자, 우리가 주문 3개를 처리하는 API 구조를 설명합니다. 변경 이유가 같은 기능을 묶고 다른 기능은 분리합니다."
REWRITE = "자, 우리가 주문 3개를 처리하는 API 구조를 볼게요. 가령 결제만 바뀌면 주문은 그대로 두는 거죠. 이제 연결을 봐요."


def source(**changes):
    return CriticSlide(slide_number=1, script=ORIGINAL, slide_text="주문 API 3개",
                       target_seconds=9, **changes)


def scores(**changes):
    return SlideScores.model_validate({
        "slide_number": 1, "reads_slide_verbatim": 0.2, "has_concrete_example": True,
        "delivers_thesis": True, "transitions": 1, "factual_risk": 0, **changes,
    })


def review_reply(**changes):
    return json.dumps({"slides": [scores(**changes).model_dump()]})


def rewrite_reply(text=REWRITE):
    return json.dumps({"slides": [{"slide_number": 1, "script": text}]})


@pytest.mark.parametrize("change,expected", [
    ({}, 0), ({"reads_slide_verbatim": 0.45}, 0), ({"reads_slide_verbatim": 0.46}, 1),
    ({"has_concrete_example": False}, 0), ({"delivers_thesis": False}, 1),
    ({"transitions": 0.74}, 1), ({"factual_risk": 0.1}, 0), ({"factual_risk": 0.11}, 1),
])
def test_thresholds_allow_short_slide_without_example(change, expected):
    assert len(failures_for(source(), scores(**change))) == expected


def test_concept_slide_requires_example_and_length():
    slide = source().model_copy(update={"target_seconds": 30})
    assert len(failures_for(slide, scores(has_concrete_example=False))) == 2


@pytest.mark.parametrize("text,reason", [
    (REWRITE.replace("3", "4"), "숫자"),
    (REWRITE.replace("API", "CPU"), "라틴"),
    ("짧아요", "길이"),
])
def test_gate_rejects_new_facts_terms_or_changed_length(text, reason):
    assert any(reason in r for r in validate_rewrite(source(), text))


def test_gate_rejects_target_length_even_when_original_length_preserved():
    slide = source().model_copy(update={"target_seconds": 30})
    assert validate_rewrite(slide, REWRITE) == ["목표 대비 길이 ±15% 초과"]


def test_gate_allows_grounded_addition_but_preserves_original_tokens():
    slide = source().model_copy(update={"slide_text": "주문 API 3개 CPU"})
    candidate = REWRITE.replace("구조", "CPU")
    assert validate_rewrite(slide, candidate) == []


@pytest.mark.parametrize("candidate", [
    ORIGINAL,
    ORIGINAL.replace("변경 이유가", "설명합니다."),
])
def test_critic_allows_unchanged_or_increased_formal_endings(candidate: str):
    assert validate_rewrite(source(), candidate) == []


@pytest.mark.parametrize("length,expected", [
    (84, ["목표 대비 길이 ±15% 초과"]),
    (85, []), (100, []), (115, []),
    (116, ["목표 대비 길이 ±15% 초과"]),
])
def test_critic_length_uses_target_seconds_instead_of_original(length: int, expected: list[str]):
    slide = source().model_copy(update={
        "script": "가" * 200, "slide_text": "",
        "target_seconds": 100 / SPEECH_CHARS_PER_SECOND,
    })
    assert validate_rewrite(slide, "나" * length) == expected


@pytest.mark.parametrize("grounding,candidate,expected", [
    (("API CPU GPU RAM ROM", ""), "API CPU GPU RAM", []),
    (("API CPU GPU RAM ROM", ""), "API CPU GPU", ["슬라이드 라틴 용어 보존율 80% 미만"]),
    (("API", ""), "API", []),
    (("", ""), "", []),
    (("API", "VLMOnly"), "API VLMOnly", []),
    (("API Grounded", ""), "API Grounded", []),
    (("API", ""), "API Invented", ["자료에 없는 라틴 용어 추가"]),
    (("API", "VLMOnly"), "VLMOnly", ["슬라이드 라틴 용어 보존율 80% 미만"]),
])
def test_critic_latin_terms_require_grounding_and_slide_coverage(
    grounding: tuple[str, str], candidate: str, expected: list[str],
):
    slide = source().model_copy(update={
        "script": "API CPU GPU RAM ROM Legacy".ljust(100, "가"),
        "slide_text": grounding[0], "visual_notes": grounding[1],
        "target_seconds": 100 / SPEECH_CHARS_PER_SECOND,
    })
    assert validate_rewrite(slide, candidate.ljust(100, "나")) == expected


@pytest.mark.parametrize("candidate,expected", [
    ("API 3", []),
    ("API", ["숫자 추가 또는 원본 누락"]),
    ("API 3 4", []),
    ("API 3 5", ["숫자 추가 또는 원본 누락"]),
])
def test_critic_numbers_still_preserve_original_and_only_allow_slide_additions(
    candidate: str, expected: list[str],
):
    slide = source().model_copy(update={
        "slide_text": "API 3 4", "visual_notes": "5",
        "target_seconds": 100 / SPEECH_CHARS_PER_SECOND,
    })
    assert validate_rewrite(slide, candidate.ljust(100, "나")) == expected


def test_single_targeted_rewrite_is_adopted_and_reported():
    client = MagicMock()
    client.chat.side_effect = [review_reply(delivers_thesis=False), rewrite_reply()]
    result = refine_section(client, [source()])[0]
    assert result.rewritten and result.script == REWRITE
    assert result.scores.delivers_thesis is False and len(result.failures) == 1
    assert client.chat.call_count == 2


def test_only_failed_editable_slides_are_rewritten():
    client = MagicMock()
    second = source().model_copy(update={"slide_number": 2})
    reply = {"slides": [scores(delivers_thesis=False).model_dump(),
                        scores().model_copy(update={"slide_number": 2}).model_dump()]}
    client.chat.side_effect = [json.dumps(reply), rewrite_reply()]
    result = refine_section(client, [source(), second])
    assert [r.rewritten for r in result] == [True, False]
    requested = json.loads(client.chat.call_args.args[0][1]["content"])
    assert [s["slide_number"] for s in requested] == [1]


@pytest.mark.parametrize("reply", ["bad JSON", '{"slides":[]}', rewrite_reply(REWRITE.replace("3", "4"))])
def test_bad_rewrite_keeps_original_without_another_attempt(reply):
    client = MagicMock()
    client.chat.side_effect = [review_reply(delivers_thesis=False), reply]
    result = refine_section(client, [source()])[0]
    assert not result.rewritten and result.script == ORIGINAL
    assert result.reason != "검토 통과" and client.chat.call_count == 2


@pytest.mark.parametrize("raw", ["not json", '{"slides":[]}', '{"slides":[{"slide_number":1}]}'])
def test_invalid_review_keeps_original_and_records_error(raw):
    client = MagicMock()
    client.chat.return_value = raw
    result = refine_section(client, [source()])[0]
    assert result.script == ORIGINAL and result.scores is None and result.failures == ["검토 응답 오류"]
    assert client.chat.call_count == 1


def test_duplicate_review_is_rejected():
    client = MagicMock()
    client.chat.return_value = json.dumps({"slides": [scores().model_dump()] * 2})
    with pytest.raises(ValidationError):
        review_section(client, [source()])


def section():
    return SectionScriptResult(section_summary="주문", carry_forward={}, slides=[
        SectionSlideScript(slide_number=1, script=ORIGINAL, target_seconds=9)])


def test_cache_uses_model_profile_intent_and_input_content(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from lecture_auto.schemas.intent import IntentSheet, SlideIntent

    client = MagicMock()
    client.chat.return_value = review_reply()
    context = CriticContext(tmp_path, [_make_slide(1, "주문", "API 3개")], "model-a")
    result = section()
    refine_cached(client, result, context)
    refine_cached(client, result, context)
    assert client.chat.call_count == 1
    profile = StyleProfile(signature_phrases=["자, 보세요"])
    intent = IntentSheet(lecture_id="x", generated_at=datetime.now(UTC), input_hash="x",
                         slides=[SlideIntent(slide=1, thesis="주문", role="개념", importance=2, seconds=10)])
    from dataclasses import replace

    for changed in [replace(context, model_key="model-b"), replace(context, profile=profile),
                    replace(context, profile=profile.model_copy(update={"avoid": ["반복"]})),
                    replace(context, intent=intent),
                    replace(context, intent=intent.model_copy(update={"slides": [
                        intent.slides[0].model_copy(update={"thesis": "결제"})]}))]:
        refine_cached(client, result, changed)
    assert client.chat.call_count == 6
    changed_result = result.model_copy(update={"slides": [
        result.slides[0].model_copy(update={"script": ORIGINAL + "요"})]})
    refine_cached(client, changed_result, context)
    assert client.chat.call_count == 7
    from lecture_auto.production import critic

    monkeypatch.setattr(critic, "REWRITE_VERSION", critic.REWRITE_VERSION + "-next")
    refine_cached(client, changed_result, context)
    assert client.chat.call_count == 8


def test_hand_edit_survives_critic_and_generated_results_keep_ownership(tmp_path):
    result = section()
    scripts = {}
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _write_section_scripts(result, scripts_dir, scripts)
    path = scripts_dir / "script_001.json"
    edited = json.loads(path.read_text())
    edited["script"] = "직접 수정한 대본"
    path.write_text(json.dumps(edited))
    client = MagicMock()
    client.chat.return_value = review_reply(delivers_thesis=False)
    out, results = refine_cached(client, result, CriticContext(tmp_path, [_make_slide(1, "주문", "")], "m"))
    _write_section_scripts(out, scripts_dir, scripts)
    write_report(tmp_path, results)
    assert scripts[1]["script"] == edited["script"]
    assert client.chat.call_count == 1
    assert json.loads((tmp_path / "critic_report.json").read_text())["slides"]["1"]["reason"] == "직접 수정한 대본 보존"
    new_dir = tmp_path / "generated"
    new_dir.mkdir()
    _write_section_scripts(result, new_dir, {})
    assert _hand_edited(new_dir / "script_001.json") is None
