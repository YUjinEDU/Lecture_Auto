"""Unit tests for scripts/restyle_scripts.py. LLM transport is mocked; no data/
or output/ writes -- everything happens under pytest's tmp_path.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from lecture_auto.pipeline.approval import save_approvals
from lecture_auto.pipeline.cache import cache_path_for, content_hash, write_cache_hash, write_text_atomic
from lecture_auto.schemas.production import ApprovalManifest, ApprovedSlide
from scripts.restyle_scripts import run

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


def _write_script(scripts_dir: Path, n: int, script: str, target_seconds: float = 20.0) -> Path:
    path = scripts_dir / f"script_{n:03d}.json"
    generated = json.dumps({"slide_number": n, "target_seconds": target_seconds, "script": script}, ensure_ascii=False, indent=2)
    write_text_atomic(path, generated)
    write_cache_hash(path, content_hash(generated))
    return path


def _chat_json(slides: dict[int, str]) -> str:
    return json.dumps({"slides": [{"slide_number": n, "script": s} for n, s in slides.items()]}, ensure_ascii=False)


def _make_lecture_dir(tmp_path: Path) -> Path:
    lecture_dir = tmp_path / "lec01_abcdef"
    scripts_dir = lecture_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    _write_script(scripts_dir, 1, ORIGINAL_1)
    _write_script(scripts_dir, 2, ORIGINAL_2)
    # One slide per section, so each slide's LLM call can be mocked independently.
    plan = {"sections": [{"title": "A", "slides": [1], "minutes": 1.0, "goal": "g"},
                          {"title": "B", "slides": [2], "minutes": 1.0, "goal": "g"}]}
    write_text_atomic(lecture_dir / "lecture_plan.json", json.dumps(plan, ensure_ascii=False))
    return lecture_dir


def test_approved_slide_is_skipped_and_untouched(tmp_path):
    lecture_dir = _make_lecture_dir(tmp_path)
    manifest = ApprovalManifest(lecture_id=lecture_dir.name)
    manifest = manifest.model_copy(update={"slides": {2: ApprovedSlide(
        wav="slide_002.wav", sha256="deadbeef", approved_at=datetime.now(timezone.utc), source="existing",
    )}})
    save_approvals(lecture_dir, manifest)

    client = MagicMock()
    client.chat.return_value = _chat_json({1: RESTYLED_1_OK})

    results = run(lecture_dir, dry_run=False, client=client)

    assert 2 not in results
    # Only the un-approved slide was ever sent to the LLM.
    sent_user_msg = client.chat.call_args[0][0][1]["content"]
    assert "슬라이드 2" not in sent_user_msg

    script_2_after = json.loads((lecture_dir / "scripts" / "script_002.json").read_text(encoding="utf-8"))
    assert script_2_after["script"] == ORIGINAL_2


def test_real_run_creates_backup_and_updates_script_without_touching_hash(tmp_path):
    lecture_dir = _make_lecture_dir(tmp_path)
    scripts_dir = lecture_dir / "scripts"
    hash_path = cache_path_for(scripts_dir / "script_001.json")
    hash_before = hash_path.read_text(encoding="utf-8")

    client = MagicMock()
    client.chat.side_effect = [_chat_json({1: RESTYLED_1_OK}), _chat_json({2: RESTYLED_2_OK})]

    run(lecture_dir, dry_run=False, client=client)

    backup_dirs = list(lecture_dir.glob("scripts_orig_*"))
    assert len(backup_dirs) == 1
    backup_script_1 = json.loads((backup_dirs[0] / "script_001.json").read_text(encoding="utf-8"))
    assert backup_script_1["script"] == ORIGINAL_1  # backup keeps the pre-restyle text

    updated = json.loads((scripts_dir / "script_001.json").read_text(encoding="utf-8"))
    assert updated["script"] == RESTYLED_1_OK
    assert updated["target_seconds"] == 20.0  # untouched field preserved

    # .hash sidecar is left exactly as it was -- batch_generate's _hand_edited()
    # relies on this mismatch to treat the slide as a kept human edit.
    assert hash_path.read_text(encoding="utf-8") == hash_before

    report = json.loads((lecture_dir / "restyle_report.json").read_text(encoding="utf-8"))
    assert report["slides"]["1"]["adopted"] is True
    # Lecture-wide metrics are computed on the joined lecture text, not an
    # average of per-slide rates -- both slides were adopted, so formal
    # frequency over the whole lecture must drop just like each slide's did.
    assert report["lecture_metrics_after"]["formal_per_1000"] < report["lecture_metrics_before"]["formal_per_1000"]


def test_second_real_run_same_day_aborts_without_calling_llm(tmp_path):
    lecture_dir = _make_lecture_dir(tmp_path)
    (lecture_dir / f"scripts_orig_{date.today():%Y%m%d}").mkdir()

    client = MagicMock()
    try:
        run(lecture_dir, dry_run=False, client=client)
        assert False, "expected FileExistsError"
    except FileExistsError:
        pass
    client.chat.assert_not_called()

    # Scripts on disk are untouched.
    script_1 = json.loads((lecture_dir / "scripts" / "script_001.json").read_text(encoding="utf-8"))
    assert script_1["script"] == ORIGINAL_1


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_dry_run_writes_no_files(tmp_path):
    lecture_dir = _make_lecture_dir(tmp_path)
    before = _snapshot(lecture_dir)

    client = MagicMock()
    client.chat.side_effect = [_chat_json({1: RESTYLED_1_OK}), _chat_json({2: RESTYLED_2_OK})]

    results = run(lecture_dir, dry_run=True, client=client)

    assert results[1].script == RESTYLED_1_OK
    # Every path and every byte under lecture_dir is exactly as it was --
    # not just the specific files a real run would have touched.
    assert _snapshot(lecture_dir) == before
