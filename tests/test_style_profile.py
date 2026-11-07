"""Profile extraction, compact prompts, and opt-in cache contracts."""
import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from lecture_auto.core.project import ProjectConfig
from lecture_auto.pipeline.lecture_plan import build_section_prompt
from lecture_auto.pipeline.style_profile import (
    CHUNK_CHARS,
    StyleProfile,
    TranscriptError,
    build_style_profile,
)
from lecture_auto.production.batch import _generate_section_scripts_cached
from lecture_auto.production.style_profiles import ProfileNotFound, StyleProfiles
from tests.test_intent import plan_reply, section_reply
from tests.test_lecture_plan import _make_slide


def test_build_profile_parses_fenced_json_and_compacts_all_categories():
    profile = StyleProfile(
        signature_phrases=["여러분" * 1000], fillers=["그러니까"],
        topic_openings=["자, 우리가"], topic_closings=["다음으로 보죠"],
        student_questions=["왜 그럴까요?"], example_domains=["쇼핑몰"],
        emphasis_patterns=["다시 말하면"], sentence_endings={"~요": 0.6, "~죠": 0.4},
        avoid=["딱딱한 발표체"],
    )
    client = MagicMock()
    client.chat.return_value = "```json\n" + profile.model_dump_json() + "\n```"
    result = build_style_profile(client, "자, 우리가 주문을 보면 이해가 되죠.")
    assert result == profile
    compact = result.compact()
    assert len(compact) <= 1200 and "딱딱한 발표체" in compact and "60%" in compact
    assert client.chat.call_count == 1


def test_long_transcript_processes_every_chunk():
    client = MagicMock()
    client.chat.return_value = StyleProfile(topic_openings=["처음"]).model_dump_json()
    build_style_profile(client, "가" * (CHUNK_CHARS + 1))
    assert client.chat.call_count == 2


def test_empty_transcript_avoids_llm():
    client = MagicMock()
    with pytest.raises(TranscriptError):
        build_style_profile(client, " \n")
    client.chat.assert_not_called()


def test_storage_scopes_profile_to_owner_and_blocks_paths(tmp_path):
    first, second = StyleProfiles(tmp_path, "alice"), StyleProfiles(tmp_path, "bob")
    profile = StyleProfile(name="수업 말투")
    pid = first.save(profile)
    assert first.load(pid) == profile and second.listing() == []
    for store, key in [(second, pid), (first, "../alice/" + pid)]:
        with pytest.raises(ProfileNotFound):
            store.load(key)
    first.delete(pid)


def test_config_defaults_remain_absent_and_fields_round_trip():
    base = ProjectConfig(id="test", name="강의", subject="설계")
    assert base.as_item() == {"id": "test", "name": "강의", "subject": "설계"}
    selected = ProjectConfig(**{**base.as_item(), "critic": True, "style_profile": "profile"})
    assert ProjectConfig.model_validate_json(selected.model_dump_json()) == selected


def test_invalid_profile_reply_rejected():
    client = MagicMock()
    client.chat.return_value = '{"sentence_endings":{"요":"invalid"}}'
    with pytest.raises(ValidationError):
        build_style_profile(client, "강의 녹취")


def test_profile_none_preserves_prompt_and_full_profile_invalidates_cache(tmp_path):
    from lecture_auto.schemas.lecture_plan import LecturePlan

    plan = LecturePlan.model_validate_json(plan_reply())
    plan = plan.model_copy(update={"sections": [plan.sections[0].model_copy(update={"minutes": 5})]})
    slides = [_make_slide(n, "제목", "설명") for n in (1, 2, 3)]
    args = (plan, plan.sections[0], slides, None, True)
    assert build_section_prompt(*args) == build_section_prompt(*args, style_profile=None)
    png = tmp_path / "slide.png"
    png.write_bytes(b"png")
    path = tmp_path / "section.json"
    client = MagicMock(text_model="t", vlm_model="v")
    client.chat.return_value = section_reply()
    call = (client, plan, plan.sections[0], slides, [png] * 3, None, True, path)
    profile = StyleProfile(signature_phrases=["말투" * 100])
    _generate_section_scripts_cached(*call, style_profile=profile)
    key = path.with_suffix(".json.hash").read_text()
    _generate_section_scripts_cached(*call, style_profile=profile)
    changed = profile.model_copy(update={"signature_phrases": [profile.signature_phrases[0] + "다름"]})
    assert changed.compact() == profile.compact()
    _generate_section_scripts_cached(*call, style_profile=changed)
    assert key != path.with_suffix(".json.hash").read_text()
    assert client.chat.call_count == 2
    raw = json.loads(path.read_text())
    assert len(raw["slides"]) == 3
