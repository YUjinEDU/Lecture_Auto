"""Slide-audio approval + timeline construction (S2).

Driver-agnostic pure functions: today called from
``scripts/batch_generate_lectures.py``, later from a FastAPI approval
endpoint. No Redis/DB/logging side effects -- only the filesystem paths the
caller passes in, written atomically per the project convention
(``pipeline/cache.py``'s ``write_text_atomic``).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import soundfile as sf

from lecture_auto.pipeline.cache import cache_path_for, write_cache_hash, write_text_atomic
from lecture_auto.schemas.production import (
    ApprovalManifest,
    ApprovedSlide,
    Timeline,
    TimelineEntry,
)


def _approved_path(work_dir: Path) -> Path:
    return Path(work_dir) / "approved.json"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_approvals(work_dir: Path, lecture_id: str) -> ApprovalManifest:
    """Load ``work_dir/approved.json``, or an empty manifest if it doesn't exist yet."""
    path = _approved_path(work_dir)
    if not path.exists():
        return ApprovalManifest(lecture_id=lecture_id)
    return ApprovalManifest(**json.loads(path.read_text(encoding="utf-8")))


def save_approvals(work_dir: Path, manifest: ApprovalManifest) -> None:
    write_text_atomic(_approved_path(work_dir), manifest.model_dump_json(indent=2))


def approve(
    manifest: ApprovalManifest,
    audio_dir: Path,
    n: int,
    source: str,
    gate_ok: bool | None,
    note: str = "",
) -> ApprovalManifest:
    """Record slide *n*'s current ``slide_NNN.wav`` as approved.

    Returns a new manifest (``model_copy``, per the project's immutable-update
    convention) -- the manifest passed in is never mutated.
    """
    wav_path = Path(audio_dir) / f"slide_{n:03d}.wav"
    slide = ApprovedSlide(
        wav=wav_path.name,
        sha256=_sha256_file(wav_path),
        approved_at=datetime.now(timezone.utc),
        source=source,
        gate_ok=gate_ok,
        note=note,
    )
    new_slides = dict(manifest.slides)
    new_slides[n] = slide
    return manifest.model_copy(update={"slides": new_slides})


def verify_approved(manifest: ApprovalManifest, audio_dir: Path) -> list[int]:
    """Slide numbers whose approved WAV is missing or no longer matches its
    recorded sha256 -- i.e. the approval no longer describes what's on disk."""
    bad: list[int] = []
    for n, slide in manifest.slides.items():
        wav_path = Path(audio_dir) / slide.wav
        if not wav_path.exists() or _sha256_file(wav_path) != slide.sha256:
            bad.append(n)
    return sorted(bad)


def promote_candidate(
    manifest: ApprovalManifest,
    audio_dir: Path,
    n: int,
    allow_failed: bool = False,
    note: str = "",
) -> ApprovalManifest:
    """Promote slide *n*'s reviewed ``slide_NNN.cand.wav`` to the main WAV.

    The previous main WAV (+ its ``.hash`` sidecar, if any) is kept as
    ``slide_NNN.prev.wav`` (overwriting any earlier prev backup) rather than
    deleted, so a bad promotion can be undone by hand. The new ``.hash`` is
    only written when the candidate passed its quality gate (``ok=True`` in
    the ``.cand.wav.json`` sidecar) -- promoting a failed candidate via
    ``allow_failed=True`` leaves the promoted file without a cache hash,
    same as S1's "failed synthesis is never cached" rule.
    """
    audio_dir = Path(audio_dir)
    wav_path = audio_dir / f"slide_{n:03d}.wav"
    cand_wav = audio_dir / f"slide_{n:03d}.cand.wav"
    cand_json_path = audio_dir / f"slide_{n:03d}.cand.wav.json"

    if not cand_wav.exists() or not cand_json_path.exists():
        raise FileNotFoundError(f"slide {n}: no candidate to promote ({cand_wav.name})")

    cand_info = json.loads(cand_json_path.read_text(encoding="utf-8"))
    ok = bool(cand_info.get("ok"))
    if not ok and not allow_failed:
        raise ValueError(
            f"slide {n}: candidate failed the quality gate (ok=False) -- "
            "pass allow_failed=True to promote it anyway"
        )

    hash_path = cache_path_for(wav_path)
    prev_wav = audio_dir / f"slide_{n:03d}.prev.wav"
    if wav_path.exists():
        os.replace(wav_path, prev_wav)
    if hash_path.exists():
        os.replace(hash_path, cache_path_for(prev_wav))

    os.replace(cand_wav, wav_path)
    if ok:
        write_cache_hash(wav_path, cand_info.get("cache_key", ""))

    cand_json_path.unlink()

    return approve(manifest, audio_dir, n, source="candidate", gate_ok=ok, note=note)


def build_timeline(
    lecture_id: str,
    mp4_name: str,
    draft: bool,
    slide_wavs: list[tuple[int, Path]],
    approved: set[int],
) -> Timeline:
    """Build a ``Timeline`` from WAVs in the exact order they were merged for
    the video (same list ``assemble_video`` consumed, so start/duration match
    the actual MP4)."""
    entries: list[TimelineEntry] = []
    start = 0.0
    for n, wav_path in slide_wavs:
        wav_path = Path(wav_path)
        duration = sf.info(str(wav_path)).duration
        entries.append(
            TimelineEntry(
                slide_number=n,
                start_seconds=start,
                duration_seconds=duration,
                wav=wav_path.name,
                wav_sha256=_sha256_file(wav_path),
                approved=n in approved,
            )
        )
        start += duration
    return Timeline(
        lecture_id=lecture_id,
        mp4=mp4_name,
        draft=draft,
        total_seconds=start,
        entries=entries,
    )
