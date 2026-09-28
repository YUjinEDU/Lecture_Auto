"""Unit tests for lecture_auto.pipeline.restyle. LLM transport is mocked."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from lecture_auto.pipeline.restyle import (
    RestyleResult,
    _validate,
    compute_metrics,
    restyle_scripts,
)

ORIGINAL_1 = (
    "이 슬라이드는 GPU 메모리 구조를 설명합니다. 이 영역은 총 3개로 구성되어 있습니다. "
    "각 영역의 역할을 순서대로 확인합니다. 마지막으로 전체 흐름을 정리합니다."
)
RESTYLED_1_OK = (
    "자, 이 슬라이드는 GPU 메모리 구조를 보여주는 거죠. 총 3개 영역으로 구성돼 있고요, "
    "각 역할을 순서대로 확인해 볼게요. 그래서 흐름을 정리해 봅시다."
)
ORIGINAL_2 = "이 화면은 이전 내용을 정리합니다. 핵심은 3가지로 요약됩니다. 자세한 내용은 다음 자료에서 확인합니다."
RESTYLED_2_OK = "자, 이 화면은 이전 내용을 정리하는 거죠. 핵심은 3가지로 요약돼요. 다음 자료에서 확인해 봅시다."


def _chat_json(slides: dict[int, str]) -> str:
    return json.dumps({"slides": [{"slide_number": n, "script": s} for n, s in slides.items()]}, ensure_ascii=False)


def test_normal_response_is_adopted_and_metrics_recorded():
    client = MagicMock()
    client.chat.return_value = _chat_json({1: RESTYLED_1_OK})

    results = restyle_scripts(client, {1: ORIGINAL_1})

    assert client.chat.call_count == 1
    result = results[1]
    assert isinstance(result, RestyleResult)
    assert result.kept_original is False
    assert result.reasons == []
    assert result.script == RESTYLED_1_OK
    assert result.metrics_before["formal_per_1000"] > result.metrics_after["formal_per_1000"]


def test_latin_token_change_retries_only_that_slide_then_adopts():
    bad = RESTYLED_1_OK.replace("GPU", "CPU")  # drops the original Latin token, adds a new one
    client = MagicMock()
    client.chat.side_effect = [
        _chat_json({1: bad, 2: RESTYLED_2_OK}),  # slide 2 passes first try
        _chat_json({1: RESTYLED_1_OK}),  # retry batch should ask about slide 1 only
    ]

    results = restyle_scripts(client, {1: ORIGINAL_1, 2: ORIGINAL_2})

    assert client.chat.call_count == 2
    retry_user_msg = client.chat.call_args_list[1][0][0][1]["content"]
    assert '"slide_number": 1' in retry_user_msg
    assert '"slide_number": 2' not in retry_user_msg

    assert results[1].kept_original is False
    assert results[1].script == RESTYLED_1_OK
    assert results[1].reasons == []
    # Slide 2 was never re-sent -- its first-pass result must survive untouched.
    assert results[2].kept_original is False
    assert results[2].script == RESTYLED_2_OK


def test_length_out_of_range_both_attempts_keeps_original():
    too_short = "짧게 요약해 봅시다."
    client = MagicMock()
    client.chat.side_effect = [_chat_json({1: too_short}), _chat_json({1: too_short})]

    results = restyle_scripts(client, {1: ORIGINAL_1})

    assert client.chat.call_count == 2
    result = results[1]
    assert result.kept_original is True
    assert result.script == ORIGINAL_1
    assert any("글자 수 비율" in r for r in result.reasons)


def test_digit_change_fails_validation():
    changed = RESTYLED_1_OK.replace("3", "4")
    reasons = _validate(ORIGINAL_1, changed)
    assert any("숫자 토큰" in r for r in reasons)


def test_malformed_json_is_reasked_once_then_succeeds():
    client = MagicMock()
    client.chat.side_effect = ["not json at all", _chat_json({1: RESTYLED_1_OK})]

    results = restyle_scripts(client, {1: ORIGINAL_1})

    assert client.chat.call_count == 2
    assert results[1].kept_original is False
    assert results[1].script == RESTYLED_1_OK


def test_malformed_json_twice_raises():
    client = MagicMock()
    client.chat.side_effect = ["not json", "still not json"]

    try:
        restyle_scripts(client, {1: ORIGINAL_1})
        assert False, "expected a JSON decode error"
    except json.JSONDecodeError:
        pass


def test_empty_scripts_returns_empty_without_calling_llm():
    client = MagicMock()
    assert restyle_scripts(client, {}) == {}
    client.chat.assert_not_called()


def test_compute_metrics_formal_frequency_drops_with_fewer_endings():
    before = compute_metrics(ORIGINAL_1)
    after = compute_metrics(RESTYLED_1_OK)
    assert before["formal_per_1000"] > after["formal_per_1000"]
