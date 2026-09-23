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

from lecture_auto.pipeline.cache import cache_path_for, qc_path_for, write_cache_hash, write_text_atomic
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
    qc_path = qc_path_for(wav_path)
    cand_qc_path = qc_path_for(cand_wav)
    prev_wav = audio_dir / f"slide_{n:03d}.prev.wav"
    if wav_path.exists():
        os.replace(wav_path, prev_wav)
    if hash_path.exists():
        os.replace(hash_path, cache_path_for(prev_wav))
    else:
        # No current hash -- don't let a stale hash from an earlier prev.wav
        # linger and get paired with this (unhashed) prev.wav.
        cache_path_for(prev_wav).unlink(missing_ok=True)
    # S6-a: same keep-as-prev treatment for the QC sidecar as the hash above,
    # so a bad promotion can be undone with its quality record intact too.
    if qc_path.exists():
        os.replace(qc_path, qc_path_for(prev_wav))
    else:
        qc_path_for(prev_wav).unlink(missing_ok=True)

    os.replace(cand_wav, wav_path)
    if ok:
        write_cache_hash(wav_path, cand_info.get("cache_key", ""))
    if cand_qc_path.exists():
        os.replace(cand_qc_path, qc_path)

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
    the actual MP4).

    S6-a: each entry's ``stt_status``/``cer``/``gate_ok`` are read from the
    WAV's ``.qc.json`` sidecar (``synthesize_raon_slide``'s ``qc_path``) if
    one exists there, so a professor/web UI can sort by CER without opening
    every sidecar by hand; a slide with no QC record (or an unreadable one)
    just gets ``None`` for all three -- this never blocks timeline building.
    """
    entries: list[TimelineEntry] = []
    start = 0.0
    for n, wav_path in slide_wavs:
        wav_path = Path(wav_path)
        duration = sf.info(str(wav_path)).duration
        stt_status = cer = gate_ok = None
        qc_file = qc_path_for(wav_path)
        if qc_file.exists():
            try:
                qc_data = json.loads(qc_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                qc_data = None
            if qc_data is not None:
                gate_ok = qc_data.get("ok")
                stt = qc_data.get("stt") or {}
                stt_status = stt.get("status")
                cer = stt.get("cer")
        entries.append(
            TimelineEntry(
                slide_number=n,
                start_seconds=start,
                duration_seconds=duration,
                wav=wav_path.name,
                wav_sha256=_sha256_file(wav_path),
                approved=n in approved,
                stt_status=stt_status,
                cer=cer,
                gate_ok=gate_ok,
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


def _mmss(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def build_report(timeline: Timeline, audio_dir: Path) -> str:
    """Human-readable Markdown review report (S8-b), written atomically by
    the caller next to the timeline (``<mp4 stem>.report.md``).

    Pure function: no filesystem writes here, only reads -- each slide's
    ``.qc.json`` sidecar (for ``gate_reasons``/``boundary_review``, which
    ``TimelineEntry`` doesn't carry) and whether a ``slide_NNN.cand.wav``
    candidate is waiting for review. Uses only fields the existing quality
    gate already computed -- no new thresholds/CER cutoffs (D-08).
    """
    audio_dir = Path(audio_dir)
    rows = []
    for e in timeline.entries:
        qc_data = None
        qc_file = qc_path_for(audio_dir / e.wav)
        if qc_file.exists():
            try:
                qc_data = json.loads(qc_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                qc_data = None
        rows.append(
            {
                "n": e.slide_number,
                "start": e.start_seconds,
                "dur": e.duration_seconds,
                "approved": e.approved,
                "gate_ok": e.gate_ok,
                "stt": e.stt_status,
                "cer": e.cer,
                "gate_reasons": (qc_data or {}).get("gate_reasons") or [],
                "boundary_review": (qc_data or {}).get("boundary_review") or [],
                "has_candidate": (audio_dir / f"slide_{e.slide_number:03d}.cand.wav").exists(),
            }
        )

    n_approved = sum(1 for r in rows if r["approved"])
    n_pass = sum(1 for r in rows if r["gate_ok"] is True)
    n_fail = sum(1 for r in rows if r["gate_ok"] is False)
    n_candidate = sum(1 for r in rows if r["has_candidate"])

    def needs_review(r: dict) -> bool:
        return (
            r["gate_ok"] is False
            or r["stt"] in ("fail", "unavailable")
            or bool(r["boundary_review"])
            or r["has_candidate"]
        )

    flagged = [r for r in rows if needs_review(r)]
    # CER 내림차순 (S8-b spec); CER을 모르는 슬라이드는 맨 뒤로.
    flagged.sort(key=lambda r: r["cer"] if r["cer"] is not None else -1.0, reverse=True)

    lines = [
        f"# {timeline.lecture_id} 검수 보고서",
        "",
        f"- 상태: {'DRAFT' if timeline.draft else '최종'} ({timeline.mp4})",
        f"- 총 길이: {_mmss(timeline.total_seconds)}",
        f"- 슬라이드 수: {len(rows)}",
        f"- 승인 {n_approved} / 검사 통과 {n_pass} / 실패 {n_fail} / 후보 대기 {n_candidate}",
        "",
        "## 먼저 들어볼 슬라이드",
        "",
    ]
    if not flagged:
        lines.append("없음")
    else:
        lines.append("| 슬라이드 | 시작 | 길이 | 문제 | 조치 |")
        lines.append("|---|---|---|---|---|")
        for r in flagged:
            problems = []
            if r["gate_reasons"]:
                problems.append(", ".join(r["gate_reasons"]))
            if r["stt"] in ("fail", "unavailable"):
                cer_str = f" (CER {r['cer']:.2f})" if r["cer"] is not None else ""
                problems.append(f"STT {r['stt']}{cer_str}")
            if r["boundary_review"]:
                problems.append(f"경계 재확인 필요 (세그먼트 {r['boundary_review']})")
            if r["has_candidate"]:
                problems.append("후보 대기")
            hint = f"`--promote {r['n']}`" if r["has_candidate"] else f"`--slides {r['n']}`"
            lines.append(
                f"| {r['n']} | {_mmss(r['start'])} | {_mmss(r['dur'])} | "
                f"{'; '.join(problems) if problems else '-'} | {hint} |"
            )

    lines += ["", "## 전체 슬라이드", "", "| 번호 | 시작 | 길이 | 승인 | gate | STT | CER |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        approved_str = "O" if r["approved"] else "-"
        gate_str = "-" if r["gate_ok"] is None else ("통과" if r["gate_ok"] else "실패")
        stt_str = r["stt"] or "-"
        cer_str = "-" if r["cer"] is None else f"{r['cer']:.3f}"
        lines.append(
            f"| {r['n']} | {_mmss(r['start'])} | {_mmss(r['dur'])} | "
            f"{approved_str} | {gate_str} | {stt_str} | {cer_str} |"
        )

    return "\n".join(lines) + "\n"
