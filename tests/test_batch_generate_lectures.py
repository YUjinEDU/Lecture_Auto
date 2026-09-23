"""Unit tests for scripts/batch_generate_lectures.py's TTS cache/output-integrity
helpers (S1-c candidate protection, S1-d target_seconds cache key, S1-e DRAFT split).

``process_lecture`` itself pulls in PDF parsing, an LLM client, and the Raon TTS
pipeline, so per SPEC these helpers were extracted as small, independently
testable functions instead of driving the whole function. All externals
(synthesize_raon_slide) are mocked -- no GPU/network.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import numpy as np
import soundfile as sf

from lecture_auto.pipeline.approval import approve, save_approvals, verify_approved
from lecture_auto.pipeline.cache import write_cache_hash
from lecture_auto.schemas.production import ApprovalManifest
from scripts.batch_generate_lectures import (
    _assemble_with_approvals,
    _draft_or_final_path,
    _invalid_slides,
    _run_slide_tts,
    _synthesize_all_slides,
    _tts_cache_key,
    main,
)


# ---------------------------------------------------------------------------
# S1-d: target_seconds is part of the cache key
# ---------------------------------------------------------------------------

def test_tts_cache_key_changes_with_target_seconds():
    """Only the target duration differs -- the cache key must still differ."""
    key_a = _tts_cache_key("동일한 스크립트 텍스트", b"ref-bytes", 20.0)
    key_b = _tts_cache_key("동일한 스크립트 텍스트", b"ref-bytes", 25.0)
    assert key_a != key_b


def test_tts_cache_key_stable_for_same_inputs():
    key_a = _tts_cache_key("script", b"ref-bytes", 20.0)
    key_b = _tts_cache_key("script", b"ref-bytes", 20.0)
    assert key_a == key_b


# ---------------------------------------------------------------------------
# S1-c: existing WAV is protected; re-synthesis goes to a .cand.wav sibling
# ---------------------------------------------------------------------------

def test_run_slide_tts_candidate_preserves_existing_wav_on_forced_regen(tmp_path):
    """Existing WAV has a currently-VALID hash (cache alone would reuse it);
    only ``--slides`` forcing regeneration should trigger the candidate path,
    and even then the existing WAV/hash must be untouched."""
    out_wav = tmp_path / "slide_001.wav"
    out_wav.write_bytes(b"ORIGINAL-AUDIO-BYTES")
    hash_path = out_wav.with_name(out_wav.name + ".hash")
    write_cache_hash(out_wav, "current-cache-key")
    original_bytes = out_wav.read_bytes()
    original_hash = hash_path.read_text(encoding="utf-8")

    sc = {"script": "hello professor", "target_seconds": 20.0}
    cand_wav = out_wav.with_name("slide_001.cand.wav")

    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        mock_synth.return_value = (cand_wav, True)
        ok = _run_slide_tts(
            tts_pipe=object(),
            n=1,
            sc=sc,
            out_wav=out_wav,
            cache_key="current-cache-key",
            force_regen=True,
        )

    assert ok is True
    # Synthesis was written to the candidate path, not the existing WAV.
    called_output_path = mock_synth.call_args.args[2]
    assert called_output_path == cand_wav

    # Existing WAV + hash are byte-for-byte untouched.
    assert out_wav.read_bytes() == original_bytes
    assert hash_path.read_text(encoding="utf-8") == original_hash

    # Candidate result recorded atomically alongside it.
    cand_json = out_wav.with_name("slide_001.cand.wav.json")
    assert json.loads(cand_json.read_text(encoding="utf-8")) == {
        "ok": True,
        "cache_key": "current-cache-key",
    }


def test_run_slide_tts_candidate_preserves_existing_wav_on_failure(tmp_path):
    """Same protection when the candidate synthesis FAILS the gate, this time
    via a stale hash (the S1-d mass-invalidation path) rather than --slides."""
    out_wav = tmp_path / "slide_001.wav"
    out_wav.write_bytes(b"ORIGINAL-AUDIO-BYTES")
    hash_path = out_wav.with_name(out_wav.name + ".hash")
    hash_path.write_text("stale-hash-from-before-target-seconds-change", encoding="utf-8")
    original_bytes = out_wav.read_bytes()
    original_hash = hash_path.read_text(encoding="utf-8")

    sc = {"script": "hello professor", "target_seconds": 20.0}
    cand_wav = out_wav.with_name("slide_001.cand.wav")

    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        mock_synth.return_value = (cand_wav, False)
        ok = _run_slide_tts(
            tts_pipe=object(),
            n=1,
            sc=sc,
            out_wav=out_wav,
            cache_key="new-cache-key",
            force_regen=False,  # not forced -- the stale hash alone triggers it
        )

    assert ok is False
    called_output_path = mock_synth.call_args.args[2]
    assert called_output_path == cand_wav

    assert out_wav.read_bytes() == original_bytes
    assert hash_path.read_text(encoding="utf-8") == original_hash

    cand_json = out_wav.with_name("slide_001.cand.wav.json")
    assert json.loads(cand_json.read_text(encoding="utf-8")) == {
        "ok": False,
        "cache_key": "new-cache-key",
    }


def _make_existing_candidate(out_wav: Path, cache_key: str, ok: bool) -> Path:
    """Set up an existing out_wav plus an already-recorded slide_NNN.cand.wav
    (+ .cand.wav.json), as a prior run would have left behind."""
    out_wav.write_bytes(b"EXISTING-MAIN-AUDIO")
    cand_wav = out_wav.with_name(out_wav.stem + ".cand.wav")
    cand_wav.write_bytes(b"EXISTING-CANDIDATE-AUDIO")
    cand_json = out_wav.with_name(out_wav.stem + ".cand.wav.json")
    cand_json.write_text(
        json.dumps({"ok": ok, "cache_key": cache_key}, ensure_ascii=False), encoding="utf-8"
    )
    return cand_wav


def test_run_slide_tts_reuses_matching_candidate_ok_true(tmp_path):
    """A candidate already recorded for the current cache key (ok=True) is
    reused -- no wasted GPU re-synthesis of an unchanged result."""
    out_wav = tmp_path / "slide_005.wav"
    _make_existing_candidate(out_wav, cache_key="same-key", ok=True)

    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        ok = _run_slide_tts(
            tts_pipe=object(),
            n=5,
            sc={"script": "x", "target_seconds": 5.0},
            out_wav=out_wav,
            cache_key="same-key",
            force_regen=False,
        )

    assert ok is True
    mock_synth.assert_not_called()


def test_run_slide_tts_reuses_matching_candidate_ok_false(tmp_path):
    """Same reuse when the recorded candidate FAILED the gate -- seeds are
    fixed, so an unforced re-run would just reproduce the same failure."""
    out_wav = tmp_path / "slide_006.wav"
    _make_existing_candidate(out_wav, cache_key="same-key", ok=False)

    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        ok = _run_slide_tts(
            tts_pipe=object(),
            n=6,
            sc={"script": "x", "target_seconds": 5.0},
            out_wav=out_wav,
            cache_key="same-key",
            force_regen=False,
        )

    assert ok is False
    mock_synth.assert_not_called()


def test_run_slide_tts_resynthesizes_when_candidate_cache_key_differs(tmp_path):
    """A recorded candidate for a DIFFERENT (stale) cache key does not count
    as up to date -- must re-synthesize."""
    out_wav = tmp_path / "slide_007.wav"
    cand_wav = _make_existing_candidate(out_wav, cache_key="old-key", ok=True)

    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        mock_synth.return_value = (cand_wav, True)
        ok = _run_slide_tts(
            tts_pipe=object(),
            n=7,
            sc={"script": "x", "target_seconds": 5.0},
            out_wav=out_wav,
            cache_key="new-key",
            force_regen=False,
        )

    assert ok is True
    mock_synth.assert_called_once()
    assert mock_synth.call_args.args[2] == cand_wav
    cand_json = out_wav.with_name("slide_007.cand.wav.json")
    assert json.loads(cand_json.read_text(encoding="utf-8"))["cache_key"] == "new-key"


def test_run_slide_tts_force_regen_resynthesizes_even_if_candidate_key_matches(tmp_path):
    """--slides forces regeneration even when the existing candidate already
    matches the current cache key."""
    out_wav = tmp_path / "slide_008.wav"
    cand_wav = _make_existing_candidate(out_wav, cache_key="same-key", ok=True)

    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        mock_synth.return_value = (cand_wav, True)
        ok = _run_slide_tts(
            tts_pipe=object(),
            n=8,
            sc={"script": "x", "target_seconds": 5.0},
            out_wav=out_wav,
            cache_key="same-key",
            force_regen=True,
        )

    assert ok is True
    mock_synth.assert_called_once()
    assert mock_synth.call_args.args[2] == cand_wav


def test_run_slide_tts_direct_write_when_out_wav_missing(tmp_path):
    """No existing WAV -- synthesis writes straight to out_wav, as before."""
    out_wav = tmp_path / "slide_002.wav"
    assert not out_wav.exists()

    sc = {"script": "second slide", "target_seconds": 10.0}

    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        mock_synth.return_value = (out_wav, True)
        ok = _run_slide_tts(
            tts_pipe=object(),
            n=2,
            sc=sc,
            out_wav=out_wav,
            cache_key="key-2",
            force_regen=False,
        )

    assert ok is True
    called_output_path = mock_synth.call_args.args[2]
    assert called_output_path == out_wav
    # Hash written for a successful direct synthesis.
    hash_path = out_wav.with_name(out_wav.name + ".hash")
    assert hash_path.read_text(encoding="utf-8").strip() == "key-2"
    # No candidate files created for the direct path.
    assert not out_wav.with_name("slide_002.cand.wav.json").exists()


def test_run_slide_tts_direct_write_failure_leaves_no_hash(tmp_path):
    out_wav = tmp_path / "slide_003.wav"

    sc = {"script": "third slide", "target_seconds": 10.0}

    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        mock_synth.return_value = (out_wav, False)
        ok = _run_slide_tts(
            tts_pipe=object(),
            n=3,
            sc=sc,
            out_wav=out_wav,
            cache_key="key-3",
            force_regen=False,
        )

    assert ok is False
    assert not out_wav.with_name(out_wav.name + ".hash").exists()


def test_run_slide_tts_skips_synthesis_when_cached(tmp_path):
    out_wav = tmp_path / "slide_004.wav"
    out_wav.write_bytes(b"cached-audio")
    write_cache_hash(out_wav, "same-key")

    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        ok = _run_slide_tts(
            tts_pipe=object(),
            n=4,
            sc={"script": "x", "target_seconds": 5.0},
            out_wav=out_wav,
            cache_key="same-key",
            force_regen=False,
        )

    assert ok is True
    mock_synth.assert_not_called()


# ---------------------------------------------------------------------------
# S1-e: DRAFT vs. final path from cache validity of the assembled WAVs
# ---------------------------------------------------------------------------

def test_invalid_slides_flags_missing_and_stale_hash(tmp_path):
    wav1 = tmp_path / "slide_001.wav"
    wav1.write_bytes(b"a")
    # No hash at all -> invalid.

    wav2 = tmp_path / "slide_002.wav"
    wav2.write_bytes(b"b")
    write_cache_hash(wav2, _tts_cache_key("script2", b"ref", 10.0))  # valid

    wav3 = tmp_path / "slide_003.wav"
    wav3.write_bytes(b"c")
    write_cache_hash(wav3, "stale-key-from-before-target-seconds-change")  # invalid

    scripts = {
        1: {"script": "script1", "target_seconds": 5.0},
        2: {"script": "script2", "target_seconds": 10.0},
        3: {"script": "script3", "target_seconds": 15.0},
    }
    wav_by_number = {1: wav1, 2: wav2, 3: wav3}

    invalid = _invalid_slides([1, 2, 3], wav_by_number, scripts, b"ref")
    assert invalid == [1, 3]


def test_draft_or_final_path_picks_draft_when_any_invalid(tmp_path):
    out = tmp_path / "lecture.mp4"
    assert _draft_or_final_path(out, [3]) == tmp_path / "lecture_DRAFT.mp4"
    assert _draft_or_final_path(out, []) == out


def test_assembly_path_end_to_end_one_invalid_then_all_valid(tmp_path):
    """Required test 6, chained through both helpers as assembly actually
    uses them: one invalid slide -> DRAFT path; once every slide's hash is
    current -> the final path."""
    out_mp4 = tmp_path / "lecture.mp4"
    scripts = {
        1: {"script": "s1", "target_seconds": 5.0},
        2: {"script": "s2", "target_seconds": 10.0},
    }
    wav1 = tmp_path / "slide_001.wav"
    wav1.write_bytes(b"a")
    wav2 = tmp_path / "slide_002.wav"
    wav2.write_bytes(b"b")
    wav_by_number = {1: wav1, 2: wav2}

    # Only slide 2 has a valid hash -> one invalid slide -> DRAFT.
    write_cache_hash(wav2, _tts_cache_key("s2", b"ref", 10.0))
    invalid = _invalid_slides([1, 2], wav_by_number, scripts, b"ref")
    assert invalid == [1]
    assert _draft_or_final_path(out_mp4, invalid) == tmp_path / "lecture_DRAFT.mp4"

    # Now slide 1 also gets a valid hash -> nothing invalid -> final path.
    write_cache_hash(wav1, _tts_cache_key("s1", b"ref", 5.0))
    invalid = _invalid_slides([1, 2], wav_by_number, scripts, b"ref")
    assert invalid == []
    assert _draft_or_final_path(out_mp4, invalid) == out_mp4


# ---------------------------------------------------------------------------
# S2 test 6/7: TTS loop respects approvals (_synthesize_all_slides)
# ---------------------------------------------------------------------------

def test_synthesize_all_slides_skips_approved_slide_despite_stale_cache(tmp_path):
    """Required test 6: an approved slide is never resynthesized, even when
    its cache key is stale (e.g. a TTS_SYNTH_VERSION bump invalidated it)."""
    out_wav = tmp_path / "slide_001.wav"
    out_wav.write_bytes(b"APPROVED-AUDIO")
    write_cache_hash(out_wav, "stale-hash-unrelated-to-current-cache-key")

    scripts = {1: {"script": "s1", "target_seconds": 5.0}}
    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        wav_paths, failed = _synthesize_all_slides(
            tts_pipe=object(),
            slide_count=1,
            scripts=scripts,
            audio_dir=tmp_path,
            ref_voice_bytes=b"ref",
            shard=(0, 1),
            target_slides=None,
            approved_numbers={1},
        )

    mock_synth.assert_not_called()
    assert wav_paths == [out_wav]
    assert failed == []
    assert out_wav.read_bytes() == b"APPROVED-AUDIO"


def test_synthesize_all_slides_approved_and_in_target_slides_uses_candidate_flow(tmp_path):
    """Required test 7: an approved slide explicitly named in --slides is
    NOT skipped -- it goes through the normal S1-c candidate flow, and the
    main WAV (and therefore the existing approval record, whose sha256
    points at it) is left untouched."""
    audio_dir = tmp_path
    out_wav = audio_dir / "slide_001.wav"
    out_wav.write_bytes(b"APPROVED-MAIN-AUDIO")
    cand_wav = audio_dir / "slide_001.cand.wav"

    manifest = approve(ApprovalManifest(lecture_id="lec1"), audio_dir, 1, source="existing", gate_ok=True)
    scripts = {1: {"script": "s1", "target_seconds": 5.0}}

    with patch("scripts.batch_generate_lectures.synthesize_raon_slide") as mock_synth:
        mock_synth.return_value = (cand_wav, True)
        wav_paths, failed = _synthesize_all_slides(
            tts_pipe=object(),
            slide_count=1,
            scripts=scripts,
            audio_dir=audio_dir,
            ref_voice_bytes=b"ref",
            shard=(0, 1),
            target_slides={1},
            approved_numbers={1},
        )

    mock_synth.assert_called_once()
    assert mock_synth.call_args.args[2] == cand_wav  # candidate path, not main
    assert out_wav.read_bytes() == b"APPROVED-MAIN-AUDIO"  # main WAV untouched
    assert (audio_dir / "slide_001.cand.wav.json").exists()
    assert failed == []
    # The approval record still describes what's on disk -- untouched.
    assert verify_approved(manifest, audio_dir) == []


# ---------------------------------------------------------------------------
# S2 test 8: DRAFT judgment considers approvals; contamination aborts assembly
# ---------------------------------------------------------------------------

def _write_real_wav(path: Path, seconds: float, sr: int = 24000) -> None:
    sf.write(str(path), np.zeros(int(sr * seconds), dtype=np.float32), sr)


def test_assemble_with_approvals_final_path_when_approved_despite_stale_cache(tmp_path):
    lec_id = "lec1"
    work_dir = tmp_path / "work"
    audio_dir = work_dir / "audio"
    video_dir = work_dir / "video"
    audio_dir.mkdir(parents=True)

    wav1 = audio_dir / "slide_001.wav"
    _write_real_wav(wav1, 1.0)
    # No .hash at all -> cache-invalid under _invalid_slides -- but approved.
    png1 = tmp_path / "slide_001.png"
    png1.write_bytes(b"PNG-BYTES")

    manifest = approve(ApprovalManifest(lecture_id=lec_id), audio_dir, 1, source="existing", gate_ok=False)
    save_approvals(work_dir, manifest)

    scripts = {1: {"script": "s1", "target_seconds": 5.0}}
    out_mp4 = tmp_path / "lecture.mp4"
    with patch("scripts.batch_generate_lectures.assemble_video") as mock_assemble:
        target = _assemble_with_approvals(
            lec_id, work_dir, audio_dir, video_dir, out_mp4, 1, scripts, [png1], [wav1], b"ref",
        )

    assert target == out_mp4  # final path, not _DRAFT -- approval covers the stale cache key
    mock_assemble.assert_called_once()
    timeline_path = out_mp4.with_name("lecture.timeline.json")
    assert timeline_path.exists()
    assert json.loads(timeline_path.read_text(encoding="utf-8"))["draft"] is False


def test_assemble_with_approvals_aborts_when_approved_audio_contaminated(tmp_path):
    """Required test 8 (second half): an approved WAV whose bytes no longer
    match its recorded sha256 aborts the whole assembly."""
    lec_id = "lec1"
    work_dir = tmp_path / "work"
    audio_dir = work_dir / "audio"
    video_dir = work_dir / "video"
    audio_dir.mkdir(parents=True)

    wav1 = audio_dir / "slide_001.wav"
    _write_real_wav(wav1, 1.0)
    png1 = tmp_path / "slide_001.png"
    png1.write_bytes(b"PNG-BYTES")

    manifest = approve(ApprovalManifest(lecture_id=lec_id), audio_dir, 1, source="existing", gate_ok=True)
    save_approvals(work_dir, manifest)

    # Tamper the approved WAV after approval.
    wav1.write_bytes(b"TAMPERED-BYTES")

    scripts = {1: {"script": "s1", "target_seconds": 5.0}}
    out_mp4 = tmp_path / "lecture.mp4"
    with patch("scripts.batch_generate_lectures.assemble_video") as mock_assemble:
        with pytest.raises(RuntimeError, match=r"\[lec1\].*slide.*1"):
            _assemble_with_approvals(
                lec_id, work_dir, audio_dir, video_dir, out_mp4, 1, scripts, [png1], [wav1], b"ref",
            )
    mock_assemble.assert_not_called()


# ---------------------------------------------------------------------------
# S2 test 10: CLI approval commands require --only and skip LLM/TTS model load
# ---------------------------------------------------------------------------

_FAKE_LECTURE = {
    "id": "testlec",
    "name": "test",
    "subject": "test",
    "pdf": Path("does-not-matter.pdf"),
    "output_mp4": Path("output/testlec.mp4"),
}


@pytest.mark.parametrize(
    "argv_tail",
    [
        ["--approve", "1-3"],
        ["--approve-passing"],
        ["--promote", "1"],
        ["--assemble-only"],
    ],
)
def test_cli_approval_commands_without_only_error(monkeypatch, tmp_path, argv_tail):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["batch_generate_lectures.py", *argv_tail])
    with pytest.raises(SystemExit):
        main()


def test_cli_approve_does_not_load_llm_or_tts_model(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scripts.batch_generate_lectures.LECTURES", [_FAKE_LECTURE])

    audio_dir = tmp_path / "data" / "work_batch" / "testlec" / "audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "slide_001.wav").write_bytes(b"SOME-AUDIO")

    monkeypatch.setattr("sys.argv", ["batch_generate_lectures.py", "--only", "testlec", "--approve", "1"])
    with patch("scripts.batch_generate_lectures.OpenAILLMClient") as mock_llm, \
         patch("scripts.batch_generate_lectures.load_raon_pipeline") as mock_tts:
        main()

    mock_llm.assert_not_called()
    mock_tts.assert_not_called()
    manifest = json.loads(
        (tmp_path / "data" / "work_batch" / "testlec" / "approved.json").read_text(encoding="utf-8")
    )
    assert manifest["slides"]["1"]["source"] == "existing"


def test_cli_promote_does_not_load_llm_or_tts_model(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scripts.batch_generate_lectures.LECTURES", [_FAKE_LECTURE])

    audio_dir = tmp_path / "data" / "work_batch" / "testlec" / "audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "slide_001.cand.wav").write_bytes(b"CANDIDATE-AUDIO")
    (audio_dir / "slide_001.cand.wav.json").write_text(
        json.dumps({"ok": True, "cache_key": "k"}), encoding="utf-8"
    )

    monkeypatch.setattr("sys.argv", ["batch_generate_lectures.py", "--only", "testlec", "--promote", "1"])
    with patch("scripts.batch_generate_lectures.OpenAILLMClient") as mock_llm, \
         patch("scripts.batch_generate_lectures.load_raon_pipeline") as mock_tts:
        main()

    mock_llm.assert_not_called()
    mock_tts.assert_not_called()
    assert (audio_dir / "slide_001.wav").read_bytes() == b"CANDIDATE-AUDIO"


def test_cli_assemble_only_does_not_load_llm_or_tts_model(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scripts.batch_generate_lectures.LECTURES", [_FAKE_LECTURE])

    work_dir = tmp_path / "data" / "work_batch" / "testlec"
    rendered_dir = work_dir / "rendered"
    scripts_dir = work_dir / "scripts"
    audio_dir = work_dir / "audio"
    rendered_dir.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)

    (rendered_dir / "slide_001.png").write_bytes(b"PNG")
    (scripts_dir / "script_001.json").write_text(
        json.dumps({"target_seconds": 3.0, "script": "s1"}), encoding="utf-8"
    )
    wav1 = audio_dir / "slide_001.wav"
    _write_real_wav(wav1, 1.0)
    write_cache_hash(wav1, _tts_cache_key("s1", b"", 3.0))  # REF_VOICE doesn't exist -> b""

    monkeypatch.setattr("sys.argv", ["batch_generate_lectures.py", "--only", "testlec", "--assemble-only"])
    with patch("scripts.batch_generate_lectures.OpenAILLMClient") as mock_llm, \
         patch("scripts.batch_generate_lectures.load_raon_pipeline") as mock_tts, \
         patch("scripts.batch_generate_lectures.assemble_video") as mock_assemble:
        main()

    mock_llm.assert_not_called()
    mock_tts.assert_not_called()
    mock_assemble.assert_called_once()
    assert (tmp_path / "output" / "testlec.timeline.json").exists()


def test_cli_only_ambiguous_match_errors_for_approval_command(monkeypatch, tmp_path):
    """--only must resolve to exactly one lecture for an approval command --
    a substring matching several real lecture ids (e.g. shared '종합설계')
    must not silently pick the first match and promote the wrong lecture's
    audio."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["batch_generate_lectures.py", "--only", "종합설계", "--approve", "1"])
    with pytest.raises(SystemExit):
        main()
    # No approved.json should have been written for either matched lecture.
    assert not (tmp_path / "data" / "work_batch").exists()
