"""Unit tests for lecture_auto/pipeline/approval.py (S2 approval manifest +
timeline). Mocks/tmp_path only -- no GPU/network/Redis, no real WAV synthesis
(real tiny WAV files are written directly via soundfile for duration checks).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from lecture_auto.pipeline.approval import (
    approve,
    build_timeline,
    load_approvals,
    promote_candidate,
    save_approvals,
    verify_approved,
)
from lecture_auto.pipeline.cache import cache_path_for, write_text_atomic
from lecture_auto.schemas.production import ApprovalManifest


def _write_wav(path: Path, seconds: float, sr: int = 24000) -> None:
    sf.write(str(path), np.zeros(int(sr * seconds), dtype=np.float32), sr)


# ---------------------------------------------------------------------------
# 1. approve() records sha256 and returns a new object (manifest unchanged)
# ---------------------------------------------------------------------------

def test_approve_records_sha_and_does_not_mutate_original(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav = audio_dir / "slide_003.wav"
    wav.write_bytes(b"AUDIO-BYTES")

    original = ApprovalManifest(lecture_id="lec1")
    updated = approve(original, audio_dir, 3, source="existing", gate_ok=True, note="ok")

    assert original.slides == {}  # original untouched
    assert 3 in updated.slides
    slide = updated.slides[3]
    assert slide.wav == "slide_003.wav"
    assert slide.sha256 == __import__("hashlib").sha256(b"AUDIO-BYTES").hexdigest()
    assert slide.source == "existing"
    assert slide.gate_ok is True
    assert slide.note == "ok"
    assert slide.approved_at.tzinfo is not None


# ---------------------------------------------------------------------------
# 2. save/load round trip via atomic write
# ---------------------------------------------------------------------------

def test_save_load_roundtrip_uses_atomic_write(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav = audio_dir / "slide_001.wav"
    wav.write_bytes(b"BYTES")

    manifest = approve(ApprovalManifest(lecture_id="lec1"), audio_dir, 1, source="existing", gate_ok=None)

    with patch("lecture_auto.pipeline.approval.write_text_atomic", wraps=write_text_atomic) as mock_atomic:
        save_approvals(tmp_path, manifest)
    mock_atomic.assert_called_once()  # proves save_approvals goes through the atomic-write helper

    approved_path = tmp_path / "approved.json"
    assert approved_path.exists()
    assert not approved_path.with_name("approved.json.tmp").exists()  # atomic: no leftover .tmp

    loaded = load_approvals(tmp_path, "lec1")
    assert loaded == manifest


def test_load_approvals_returns_empty_manifest_when_missing(tmp_path):
    manifest = load_approvals(tmp_path, "lec1")
    assert manifest.lecture_id == "lec1"
    assert manifest.slides == {}


# ---------------------------------------------------------------------------
# 3. verify_approved: byte change or missing file flags the slide
# ---------------------------------------------------------------------------

def test_verify_approved_flags_changed_and_missing(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav1 = audio_dir / "slide_001.wav"
    wav1.write_bytes(b"ORIGINAL")
    wav2 = audio_dir / "slide_002.wav"
    wav2.write_bytes(b"ORIGINAL-2")

    manifest = ApprovalManifest(lecture_id="lec1")
    manifest = approve(manifest, audio_dir, 1, source="existing", gate_ok=True)
    manifest = approve(manifest, audio_dir, 2, source="existing", gate_ok=True)

    # Slide 1: bytes changed after approval.
    wav1.write_bytes(b"TAMPERED")
    # Slide 2: file deleted after approval.
    wav2.unlink()

    assert verify_approved(manifest, audio_dir) == [1, 2]


def test_verify_approved_empty_when_untouched(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav = audio_dir / "slide_001.wav"
    wav.write_bytes(b"ORIGINAL")
    manifest = approve(ApprovalManifest(lecture_id="lec1"), audio_dir, 1, source="existing", gate_ok=True)
    assert verify_approved(manifest, audio_dir) == []


# ---------------------------------------------------------------------------
# 4/5. promote_candidate: success + failed-gate promotion
# ---------------------------------------------------------------------------

def _make_candidate(audio_dir: Path, n: int, ok: bool, cache_key: str = "new-key") -> None:
    cand_wav = audio_dir / f"slide_{n:03d}.cand.wav"
    cand_wav.write_bytes(b"CANDIDATE-AUDIO")
    cand_json = audio_dir / f"slide_{n:03d}.cand.wav.json"
    cand_json.write_text(json.dumps({"ok": ok, "cache_key": cache_key}), encoding="utf-8")


def test_promote_candidate_success_replaces_main_and_keeps_prev(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav = audio_dir / "slide_005.wav"
    wav.write_bytes(b"OLD-MAIN-AUDIO")
    hash_path = cache_path_for(wav)
    hash_path.write_text("old-hash", encoding="utf-8")
    _make_candidate(audio_dir, 5, ok=True, cache_key="promoted-key")

    manifest = ApprovalManifest(lecture_id="lec1")
    updated = promote_candidate(manifest, audio_dir, 5)

    # Main WAV replaced with the candidate's bytes.
    assert wav.read_bytes() == b"CANDIDATE-AUDIO"
    # Old main kept as .prev.wav (+ its old hash alongside it).
    prev_wav = audio_dir / "slide_005.prev.wav"
    assert prev_wav.read_bytes() == b"OLD-MAIN-AUDIO"
    assert cache_path_for(prev_wav).read_text(encoding="utf-8") == "old-hash"
    # New hash = candidate's recorded cache_key.
    assert hash_path.read_text(encoding="utf-8").strip() == "promoted-key"
    # Candidate files removed.
    assert not (audio_dir / "slide_005.cand.wav").exists()
    assert not (audio_dir / "slide_005.cand.wav.json").exists()
    # Approval recorded.
    assert updated.slides[5].source == "candidate"
    assert updated.slides[5].gate_ok is True
    assert updated.slides[5].sha256 == __import__("hashlib").sha256(b"CANDIDATE-AUDIO").hexdigest()


def test_promote_candidate_does_not_leave_stale_prev_hash(tmp_path):
    """If the main WAV has no current .hash (e.g. it was itself a promoted
    failure) but an earlier promotion's slide_NNN.prev.wav.hash still exists,
    that stale hash must not get paired with the new prev.wav -- it would
    otherwise look like a valid cache hash for audio it was never computed
    from."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav = audio_dir / "slide_008.wav"
    wav.write_bytes(b"MAIN-NO-HASH")  # no cache_path_for(wav) sidecar
    stale_prev_hash = cache_path_for(audio_dir / "slide_008.prev.wav")
    stale_prev_hash.write_text("stale-hash-from-an-earlier-promotion", encoding="utf-8")
    _make_candidate(audio_dir, 8, ok=True, cache_key="new-key")

    promote_candidate(ApprovalManifest(lecture_id="lec1"), audio_dir, 8)

    assert not stale_prev_hash.exists()


def test_promote_candidate_failed_without_allow_failed_raises_and_leaves_files(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav = audio_dir / "slide_006.wav"
    wav.write_bytes(b"OLD-MAIN")
    _make_candidate(audio_dir, 6, ok=False)

    manifest = ApprovalManifest(lecture_id="lec1")
    with pytest.raises(ValueError):
        promote_candidate(manifest, audio_dir, 6, allow_failed=False)

    # Nothing changed on disk.
    assert wav.read_bytes() == b"OLD-MAIN"
    assert (audio_dir / "slide_006.cand.wav").exists()
    assert (audio_dir / "slide_006.cand.wav.json").exists()
    assert not (audio_dir / "slide_006.prev.wav").exists()


def test_promote_candidate_failed_with_allow_failed_promotes_without_hash(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav = audio_dir / "slide_007.wav"
    wav.write_bytes(b"OLD-MAIN")
    hash_path = cache_path_for(wav)
    hash_path.write_text("old-hash", encoding="utf-8")
    _make_candidate(audio_dir, 7, ok=False, cache_key="failed-key")

    manifest = ApprovalManifest(lecture_id="lec1")
    updated = promote_candidate(manifest, audio_dir, 7, allow_failed=True, note="professor accepted despite gate")

    assert wav.read_bytes() == b"CANDIDATE-AUDIO"
    # No new hash recorded for a promoted failure.
    assert not hash_path.exists()
    assert updated.slides[7].gate_ok is False
    assert updated.slides[7].note == "professor accepted despite gate"


# ---------------------------------------------------------------------------
# 9. build_timeline: known-duration WAVs -> correct start/duration/total
# ---------------------------------------------------------------------------

def test_build_timeline_start_duration_total(tmp_path):
    wav1 = tmp_path / "slide_001.wav"
    wav2 = tmp_path / "slide_002.wav"
    wav3 = tmp_path / "slide_003.wav"
    _write_wav(wav1, 2.0)
    _write_wav(wav2, 3.5)
    _write_wav(wav3, 1.25)

    timeline = build_timeline(
        "lec1", "lec1.mp4", draft=False,
        slide_wavs=[(1, wav1), (2, wav2), (3, wav3)],
        approved={2},
    )

    assert timeline.lecture_id == "lec1"
    assert timeline.mp4 == "lec1.mp4"
    assert timeline.draft is False
    assert [e.slide_number for e in timeline.entries] == [1, 2, 3]
    assert timeline.entries[0].start_seconds == pytest.approx(0.0)
    assert timeline.entries[0].duration_seconds == pytest.approx(2.0)
    assert timeline.entries[1].start_seconds == pytest.approx(2.0)
    assert timeline.entries[1].duration_seconds == pytest.approx(3.5)
    assert timeline.entries[2].start_seconds == pytest.approx(5.5)
    assert timeline.entries[2].duration_seconds == pytest.approx(1.25)
    assert timeline.total_seconds == pytest.approx(6.75)
    assert timeline.entries[0].approved is False
    assert timeline.entries[1].approved is True
    assert timeline.entries[2].approved is False
