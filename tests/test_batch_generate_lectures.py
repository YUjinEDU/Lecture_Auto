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

from lecture_auto.pipeline.cache import write_cache_hash
from scripts.batch_generate_lectures import (
    _draft_or_final_path,
    _invalid_slides,
    _run_slide_tts,
    _tts_cache_key,
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
