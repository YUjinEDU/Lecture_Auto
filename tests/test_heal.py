"""--heal: one bounded recovery round for a DRAFT lecture. No GPU/LLM/ffmpeg."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lecture_auto.pipeline.cache import write_cache_hash
from scripts import batch_generate_lectures as bgl
from scripts import produce

_ITEM = {"id": "healtest", "name": "t", "subject": "t", "pdf": Path("x.pdf")}


@pytest.fixture
def work(tmp_path, monkeypatch):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref")
    monkeypatch.setattr(bgl, "REF_VOICE", ref)
    base = tmp_path / "work_batch"
    (base / "healtest" / "scripts").mkdir(parents=True)
    (base / "healtest" / "audio").mkdir()
    return base


def _slide(base, n, *, valid):
    script = {"slide_number": n, "target_seconds": 10.0, "script": f"{n}번 슬라이드 대본입니다."}
    (base / "healtest" / "scripts" / f"script_{n:03d}.json").write_text(
        json.dumps(script, ensure_ascii=False), encoding="utf-8")
    wav = base / "healtest" / "audio" / f"slide_{n:03d}.wav"
    wav.write_bytes(b"RIFF")
    if valid:
        write_cache_hash(wav, bgl._tts_cache_key(script["script"], b"ref", 10.0))


def test_held_back_slides_are_the_invalid_unapproved_ones(work):
    _slide(work, 1, valid=True)
    _slide(work, 2, valid=False)
    _slide(work, 3, valid=False)
    approvals = bgl.load_approvals(work / "healtest", "healtest")

    assert bgl._held_back_slides(_ITEM, work, []) == [2, 3]

    with patch.object(bgl, "load_approvals", return_value=approvals.model_copy(update={"slides": {3: object()}})):
        assert bgl._held_back_slides(_ITEM, work, []) == [2]


def test_heal_retries_only_held_back_slides_then_reports_what_still_fails(work, caplog):
    for n, valid in ((1, True), (2, False), (3, False)):
        _slide(work, n, valid=valid)
    audio = work / "healtest" / "audio"
    for n in (2, 3):
        (audio / f"slide_{n:03d}.cand.wav").write_bytes(b"RIFF")
    (audio / "slide_003.cand.wav.qc.json").write_text(json.dumps({
        "gate_reasons": ["seg1:fallback(cer)"],
        "segments": [{"index": 1, "fallback": True, "cer": 0.31, "text": "문제 문장입니다"}],
    }), encoding="utf-8")

    def promote(item, base, slides_arg, allow_failed, note):
        if slides_arg == "3":
            raise ValueError("candidate failed the quality gate")
        (audio / "slide_002.wav.hash").write_text(
            bgl._tts_cache_key("2번 슬라이드 대본입니다.", b"ref", 10.0), encoding="utf-8")

    with patch.object(bgl, "process_lecture") as synth, \
         patch.object(bgl, "_cli_promote", side_effect=promote) as prom, \
         patch.object(bgl, "assemble_only") as assemble:
        still = bgl._heal_lecture(_ITEM, object(), object(), work, Path("out"), [], True)

    assert synth.call_args.kwargs["target_slides"] == {2, 3}
    assert synth.call_args.kwargs["claim"].startswith("heal_")
    assert [c.args[2] for c in prom.call_args_list] == ["2", "3"]
    assemble.assert_called_once()
    assert still == [3]
    assert "문제 문장입니다" in caplog.text and "seg1:fallback(cer)" in caplog.text


def test_heal_does_nothing_when_no_slide_is_held_back(work):
    _slide(work, 1, valid=True)

    with patch.object(bgl, "process_lecture") as synth, patch.object(bgl, "assemble_only") as assemble:
        assert bgl._heal_lecture(_ITEM, object(), object(), work, Path("out"), [], True) == []

    synth.assert_not_called()
    assemble.assert_not_called()


def test_produce_heal_flag_adds_one_heal_command_per_lecture(capsys):
    produce.main(["--only", "10,11", "--gpus", "0", "--heal", "--dry-run"])

    heals = [line for line in capsys.readouterr().out.splitlines() if "--heal" in line]
    assert len(heals) == 2
    assert all("--gpu 0" in line for line in heals)


def test_produce_without_heal_flag_prints_no_heal_command(capsys):
    produce.main(["--only", "10,11", "--gpus", "0", "--dry-run"])

    assert "--heal" not in capsys.readouterr().out
