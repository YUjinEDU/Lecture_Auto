"""Batch lecture video generator for the 5 target lectures.

Runs full end-to-end pipeline:
1. PDF Parsing
2. Slide Rendering (PDF -> PNGs)
3. Lecture-wide plan (sections, recurring examples, time budget) via gpt-5.6-luna
4. Section-by-section script generation (4-8 slides per call, continuous story,
   carry-forward state) via gpt-5.6-luna vision
5. Voice-cloned TTS Audio Synthesis via Raon-Speech-9B (segmented + quality-gated)
6. Video Assembly via ffmpeg -> MP4 (40 minutes each)

Every LLM/TTS call is cached by a SHA-256 of its actual inputs (prompt text,
image bytes, reference voice, model config) via lecture_auto.pipeline.cache --
not by "does a file with this name already exist", so a prompt or reference
voice change regenerates exactly the artifacts affected by it, not none of
them (stale) and not all of them (wasteful).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import re
import shutil
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lecture_auto.llm.openai_client import OpenAILLMClient
from lecture_auto.pipeline.approval import (
    approve,
    build_report,
    build_timeline,
    load_approvals,
    promote_candidate,
    save_approvals,
    verify_approved,
)
from lecture_auto.pipeline.cache import (
    cache_path_for,
    content_hash,
    is_cache_valid,
    qc_path_for,
    write_cache_hash,
    write_text_atomic,
)
from lecture_auto.pipeline.pronunciation import apply_pronunciation, load_pronunciation_entries
from lecture_auto.pipeline.lecture_plan import (
    _PLAN_SYSTEM_PROMPT,
    build_lecture_plan_prompt,
    build_section_prompt,
    generate_lecture_plan,
    generate_section_scripts,
    parse_reference_script,
    summarize_reference_outline,
)
from lecture_auto.pipeline.parser_pdf import parse_pdf
from lecture_auto.pipeline.raon_tts import (
    TTS_MODEL_ID,
    TTS_RESEED_SEEDS,
    TTS_SEEDS,
    TTS_SYNTH_VERSION,
    TTS_TEMPERATURE,
    load_raon_pipeline,
    synthesize_raon_slide,
)
from lecture_auto.pipeline.renderer import pptx_to_pdf, render_slides
from lecture_auto.pipeline.script_gen import (
    generate_script_for_slide_vision,
    get_professor_system_prompt,
)
from lecture_auto.pipeline.video import assemble_video
from lecture_auto.schemas.lecture_plan import (
    CarryForward,
    LecturePlan,
    SectionScriptResult,
)
from lecture_auto.schemas.manifest import LectureStyle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("batch_generator")

TARGET_MINUTES = 40.0  # 40분 영상 목표 (2026-09-23 사용자 결정, 종합설계 2026)
# S10-c/D-16: 04-1 실측 -- 대본 글자 수 15,873자가 계획 예산(40분*60*7.0자/초=
# 16,800자) 대비 94.5%. 대본 생성이 계획 예산에 꾸준히 못 미쳐서 생긴 부족분을,
# 계획 자체에 넘기는 목표 분을 미리 부풀려 보정한다. TARGET_MINUTES(사용자에게
# 보여주는/기록하는 목표)는 그대로 40.0 유지.
PLAN_LENGTH_CALIBRATION = 1.06
# ref_combined.wav (47.7s) was never actually a "combined" reference at
# inference time: PretrainedSpeakerEncoder.forward() front-truncates any
# speaker_audio to SpeakerEncoderConfig.max_seconds (10.0s) before computing
# the ECAPA embedding. Verified byte-for-byte: ref_combined.wav's first 10s
# == ref_phone_norm.wav (correlation 1.0, identical peak/rms) -- the combined
# file's 37s lecture-mic tail was never used, the embedding always came from
# this normalized phone clip alone. Point at it directly instead of the
# misleading 47.7s file; this is a no-op for generated audio (same effective
# embedding, already proven to work by the batch runs so far), just honest
# about what's actually driving voice conditioning.
# NOT tested well: data/audio_ref/comparison/sample_v1_phone_orig.wav (the
# *un*normalized phone take) -- ~5x lower RMS, produced consistent quality-gate
# failures across all 3 seeds in a live test. Don't switch to it without
# re-validating.
# Built by scripts/build_voice_reference.py from 1859-1868s of the 2025
# lecture recording; reference_v1.wav.json records the exact provenance.
REF_VOICE = Path("data/audio_ref/reference_v1.wav")

LECTURES = [
    {
        "id": "01_AI현업_02_디자인씽킹개요",
        "name": "02-디자인씽킹 개요",
        "subject": "AI활용현업문제해결",
        "pdf": Path("data/PDF/AI현업문제해결/02-디자인씽킹 개요.pdf"),
    },
    {
        "id": "02_AI현업_03_고객문제이해",
        "name": "03-고객 문제 이해",
        "subject": "AI활용현업문제해결",
        "pdf": Path("data/PDF/AI현업문제해결/03-고객 문제 이해.pdf"),
    },
    {
        "id": "03_AI현업_04_문제정의와아이디에이션",
        "name": "04-문제정의와 아이디에이션",
        "subject": "AI활용현업문제해결",
        "pdf": Path("data/PDF/AI현업문제해결/04-문제정의와 아이디에이션.pdf"),
    },
    {
        "id": "04_종합설계_02_고객문제이해및정의",
        "name": "02_고객 문제 이해 및 정의",
        "subject": "종합설계",
        "pdf": Path("data/PDF/종합설계 2026/1차/02_고객 문제 이해 및 정의.pdf"),
    },
    {
        "id": "05_종합설계_03_문제정의와아이디에이션",
        "name": "03_문제정의와 아이디에이션",
        "subject": "종합설계",
        "pdf": Path("data/PDF/종합설계 2026/1차/03_문제정의와 아이디에이션.pdf"),
        "clone_from": "03_AI현업_04_문제정의와아이디에이션",
    },
    # S3-c (D-10, D-11): PPTX inputs (S3-a converts pptx -> work_dir/input/*.pdf
    # via pptx_to_pdf) + reference lecture scripts (S3-b: reference only, not
    # fed straight to TTS -- see lecture_plan.parse_reference_script).
    {
        "id": "06_종합설계_04-1_아이디어를컨셉으로만들기",
        "name": "04-1_아이디어를 컨셉으로 만들기",
        "subject": "종합설계",
        "pptx": Path("data/PDF/종합설계 2026/04-1_아이디어를 컨셉으로 만들기.pptx"),
        "reference_script": Path("data/PDF/종합설계 2026/04-1_아이디어를컨셉으로만들기_강의스크립트.md"),
    },
    {
        "id": "07_종합설계_04-2_프로토타이핑과테스트",
        "name": "04-2_프로토타이핑과 테스트",
        "subject": "종합설계",
        "pptx": Path("data/PDF/종합설계 2026/04-2_프로토타이핑과 테스트.pptx"),
        "reference_script": Path("data/PDF/종합설계 2026/04-2_프로토타이핑과테스트_강의스크립트.md"),
    },
    {
        "id": "08_종합설계_05_스크럼_활용_애자일_프로세스",
        "name": "05_스크럼 활용 애자일 프로세스",
        "subject": "종합설계",
        "pptx": Path("data/PDF/종합설계 2026/05_스크럼_활용_애자일_프로세스.pptx"),
        "reference_script": Path("data/PDF/종합설계 2026/05_스크럼_활용_애자일_프로세스_강의스크립트.md"),
    },
    {
        "id": "09_종합설계_06_Product_Backlog",
        "name": "06_Product Backlog",
        "subject": "종합설계",
        "pptx": Path("data/PDF/종합설계 2026/06_Product_Backlog.pptx"),
        "reference_script": Path("data/PDF/종합설계 2026/06_Product_Backlog_강의스크립트.md"),
    },
]


def _lecture_output_mp4(lec_id: str, output_dir: Path) -> Path:
    """S8-a: every lecture's human-facing output lives in its own subfolder,
    ``output/<id>/<id>.mp4`` (docs/STORAGE.md) -- computed from the id rather
    than hardcoded per ``LECTURES`` entry, so DRAFT/timeline/report siblings
    always land next to the right lecture's video."""
    return Path(output_dir) / lec_id / f"{lec_id}.mp4"


def _tts_cache_key(
    script_text: str, ref_voice_bytes: bytes, target_seconds, entries: Sequence[dict] = ()
) -> str:
    """TTS artifact cache key -- the single source of truth for what makes a
    synthesized slide WAV valid.

    Centralized so synthesis (writing the sidecar) and the pre-assembly
    validity check (S1-e) hash the exact same inputs; two separate ad hoc
    ``content_hash(...)`` call sites drifting apart is how a WAV that looks
    "valid" to one check quietly isn't to the other.

    ``target_seconds`` is included (S1-d): it's part of what
    ``synthesize_raon_slide`` is asked to produce (``max_seconds``), so a
    target-only edit must invalidate the cached audio. NOTE: this makes every
    existing ``.hash`` sidecar in ``data/work_batch/**`` invalid the moment
    this ships, even for slides whose script/voice/model config never
    changed -- S1-c's ``.cand.wav`` candidate flow is what keeps that mass
    invalidation from silently overwriting the already-reviewed WAVs.

    ``entries`` (S6-d) is the pronunciation dictionary. The key is hashed on
    the *spoken* text (``apply_pronunciation(script_text, entries)``), not
    the raw script, per SPEC: "TTS 캐시 키는 spoken_text 기준" -- a dictionary
    edit invalidates only the slides whose spoken text it actually changes,
    and with every entry ``approved: false`` (the shipped default) spoken ==
    script, so this is byte-identical to omitting ``entries`` entirely (see
    ``test_tts_cache_key_unaffected_by_all_unapproved_entries``).
    """
    spoken_text = apply_pronunciation(script_text, list(entries))
    return content_hash(
        spoken_text, ref_voice_bytes, TTS_MODEL_ID, str(TTS_TEMPERATURE), str(TTS_SEEDS), TTS_SYNTH_VERSION,
        str(target_seconds),
    )


def _invalid_slides(
    slide_numbers: list[int],
    wav_by_number: dict[int, Path],
    scripts: dict[int, dict],
    ref_voice_bytes: bytes,
    entries: Sequence[dict] = (),
) -> list[int]:
    """Slide numbers whose assembly-bound WAV is not valid for the scripts'
    *current* cache key: missing file, missing/stale ``.hash`` sidecar, or a
    WAV that was never successfully synthesized. Used right before assembly
    (S1-e) to decide whether the output must be a ``_DRAFT`` instead of the
    final MP4.
    """
    invalid: list[int] = []
    for n in slide_numbers:
        sc = scripts[n]
        key = _tts_cache_key(sc.get("script", ""), ref_voice_bytes, sc.get("target_seconds"), entries)
        if not is_cache_valid(wav_by_number[n], key):
            invalid.append(n)
    return invalid


def _run_slide_tts(
    tts_pipe,
    n: int,
    sc: dict,
    out_wav: Path,
    cache_key: str,
    force_regen: bool,
    entries: Sequence[dict] = (),
    verify_stt: bool = True,
) -> bool:
    """Synthesize slide *n* audio if needed. Returns the quality-gate result
    for whatever happened this run (``True`` if the existing cache was reused
    without a synthesis call).

    S1-c: if *out_wav* already exists, a re-synthesis (forced via ``--slides``
    or because the cache key no longer matches) is written to a
    ``slide_NNN.cand.wav`` sibling instead -- the existing WAV and its
    ``.hash`` sidecar are **never** touched, success or failure. Only when
    *out_wav* does not exist yet is it written to directly, same as before.

    If a candidate for the *current* cache key already exists (same file +
    recorded ``cache_key``) and ``force_regen`` is False, synthesis is
    skipped and the recorded ``ok`` is returned -- otherwise every full
    re-run after S1-d ships would re-synthesize all ~77 slides as candidates
    every single time, since S1-d invalidates every existing ``.hash`` at
    once. Seeds are fixed, so re-running an unforced, already-recorded
    candidate (pass or fail) would just reproduce the same result.

    S6-a: ``verify_stt`` defaults to True here (batch's own default -- see
    ``main --no-stt``), unlike ``synthesize_raon_slide``'s own ``False``
    default, which stays unchanged for every other caller. A ``<wav>.qc.json``
    (or ``<cand.wav>.qc.json``) is always written alongside whatever WAV this
    call produces. S6-d: the actual synthesized (and cache-keyed) text is
    ``apply_pronunciation(script_text, entries)``, never the raw script --
    the caller's *cache_key* must already reflect the same ``entries``.

    S9-d/D-15: ``force_regen`` (set only by ``--slides`` naming this slide)
    also selects ``TTS_RESEED_SEEDS`` instead of the default ``TTS_SEEDS`` --
    seeds are otherwise fixed, so an explicitly requested re-run would
    reproduce byte-identical audio to the run it's meant to replace.
    """
    script_text = sc.get("script", "")
    spoken_text = apply_pronunciation(script_text, list(entries))
    seeds = TTS_RESEED_SEEDS if force_regen else None

    if not force_regen and is_cache_valid(out_wav, cache_key):
        logger.info("Slide %d audio cached, skipping...", n)
        return True

    if out_wav.exists():
        cand_wav = out_wav.with_name(out_wav.stem + ".cand.wav")
        cand_json = out_wav.with_name(out_wav.stem + ".cand.wav.json")

        # A prior run may have already synthesized a candidate for this exact
        # cache key (very likely right after S1-d ships, since that change
        # invalidates every existing .hash at once). Seeds are fixed, so
        # re-running would just reproduce the same result at real GPU cost --
        # skip unless --slides explicitly forces it.
        if not force_regen and cand_wav.exists() and cand_wav.stat().st_size > 0 and cand_json.exists():
            try:
                recorded = json.loads(cand_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                recorded = None
            if recorded is not None and recorded.get("cache_key") == cache_key:
                logger.info("Slide %d: candidate up to date, skipping", n)
                return bool(recorded.get("ok"))

        logger.info(
            "Slide %d: existing audio present but cache invalid/forced -- "
            "synthesizing candidate %s (existing %s left untouched)",
            n, cand_wav, out_wav.name,
        )
        _, ok = synthesize_raon_slide(
            tts_pipe, spoken_text, cand_wav, speaker_audio=REF_VOICE, max_seconds=sc.get("target_seconds"),
            verify_stt=verify_stt, qc_path=qc_path_for(cand_wav), seeds=seeds,
        )
        write_text_atomic(
            cand_json, json.dumps({"ok": ok, "cache_key": cache_key}, ensure_ascii=False, indent=2)
        )
        if ok:
            logger.info("Slide %d candidate ready for review: %s", n, cand_wav)
        else:
            logger.error("Slide %d candidate audio FAILED quality gate: %s", n, cand_wav)
        return ok

    logger.info("Synthesizing slide %d audio (%d chars)...", n, len(script_text))
    _, ok = synthesize_raon_slide(
        tts_pipe, spoken_text, out_wav, speaker_audio=REF_VOICE, max_seconds=sc.get("target_seconds"),
        verify_stt=verify_stt, qc_path=qc_path_for(out_wav), seeds=seeds,
    )
    if ok:
        write_cache_hash(out_wav, cache_key)
    else:
        # Deliberately NOT cached. The wav is kept so the video still
        # assembles and can be listened to, but leaving the sidecar
        # unwritten is what stops the next run from adopting audio that
        # failed our own quality gate as a valid artifact.
        logger.error("Slide %d audio FAILED quality gate -- not caching", n)
    return ok


def _synthesize_all_slides(
    tts_pipe,
    slide_count: int,
    scripts: dict[int, dict],
    audio_dir: Path,
    ref_voice_bytes: bytes,
    shard: tuple[int, int],
    target_slides: set[int] | None,
    approved_numbers: set[int],
    entries: Sequence[dict] = (),
    verify_stt: bool = True,
) -> tuple[list[Path], list[int]]:
    """Stage 5 of ``process_lecture``, pulled out for direct testing: decide
    per slide whether to synthesize, skip (sharded/kept/approved), and
    return ``(wav_paths in slide order, failed_slides)``.

    S2: a slide in *approved_numbers* is skipped entirely -- no synthesis
    call, candidate or otherwise -- unless it is explicitly named in
    *target_slides*, even if its cache key is stale (e.g. a
    ``TTS_SYNTH_VERSION`` bump). This check runs before the cache-key
    computation and before ``_run_slide_tts`` is ever called, so an approved
    slide's audio is never touched by cache-key churn.
    """
    wav_paths: list[Path] = []
    failed_slides: list[int] = []
    shard_index, shard_count = shard
    for n in range(1, slide_count + 1):
        sc = scripts[n]
        out_wav = audio_dir / f"slide_{n:03d}.wav"
        if (n - 1) % shard_count != shard_index:
            # Another process on another GPU owns this slide. Slides are fully
            # independent -- tts_continuation only ever references a segment
            # from the same slide -- so splitting them costs no quality.
            wav_paths.append(out_wav)
            continue
        if n in approved_numbers and (target_slides is None or n not in target_slides):
            logger.info("Slide %d approved, skipping synthesis (using approved audio)", n)
            wav_paths.append(out_wav)
            continue
        if target_slides is not None and n not in target_slides and out_wav.exists():
            logger.info("Slide %d/%d not in target slides, keeping existing audio", n, slide_count)
            wav_paths.append(out_wav)
            continue

        cache_key = _tts_cache_key(sc.get("script", ""), ref_voice_bytes, sc.get("target_seconds"), entries)
        force_regen = target_slides is not None and n in target_slides
        ok = _run_slide_tts(
            tts_pipe, n, sc, out_wav, cache_key, force_regen, entries=entries, verify_stt=verify_stt
        )
        if not ok:
            failed_slides.append(n)
        wav_paths.append(out_wav)

    return wav_paths, failed_slides


def _draft_or_final_path(out_mp4: Path, invalid_slides: list[int]) -> Path:
    """Final MP4 path unless any slide's audio is invalid (S1-e), in which
    case the ``_DRAFT`` sibling is used so a bad/incomplete run never
    silently overwrites the last good final video."""
    if invalid_slides:
        return out_mp4.with_name(out_mp4.stem + "_DRAFT.mp4")
    return out_mp4


def _timeline_path(mp4_path: Path) -> Path:
    return mp4_path.with_name(mp4_path.stem + ".timeline.json")


def _report_path(mp4_path: Path) -> Path:
    return mp4_path.with_name(mp4_path.stem + ".report.md")


def _cleanup_stale_draft(final_mp4: Path) -> None:
    """S8-a: once a lecture's video is good enough to write the *final* MP4,
    any leftover ``_DRAFT`` (+ its timeline/report) from a previous, worse
    run is stale and regenerable -- remove it so the output folder doesn't
    show both a final and an old draft side by side. Never called when the
    assembly itself is a DRAFT (the existing final is left untouched, S1-e)."""
    draft_mp4 = final_mp4.with_name(final_mp4.stem + "_DRAFT.mp4")
    for p in (draft_mp4, _timeline_path(draft_mp4), _report_path(draft_mp4)):
        if p.exists():
            logger.info("Removing stale draft artifact: %s", p)
            p.unlink()


def _assemble_with_approvals(
    lec_id: str,
    work_dir: Path,
    audio_dir: Path,
    video_dir: Path,
    out_mp4: Path,
    slide_count: int,
    scripts: dict[int, dict],
    png_paths: list[Path],
    wav_paths: list[Path],
    ref_voice_bytes: bytes,
    entries: Sequence[dict] = (),
) -> Path:
    """Shared assemble+timeline tail (S2) for both the normal pipeline and
    ``--assemble-only``.

    S1-e's DRAFT check is extended here: a slide is valid for the final path
    if its WAV matches the *current* TTS cache key **or** it is approved
    (S2) -- an approved slide must never regress to DRAFT just because a
    prompt/model/version bump invalidated its cache key. Before touching the
    approved audio at all, ``verify_approved`` must come back empty: any
    approved WAV whose bytes no longer match its recorded sha256 aborts the
    whole assembly (contamination), rather than silently building a video
    from audio the professor never actually approved.
    """
    manifest = load_approvals(work_dir, lec_id)
    approved_numbers = set(manifest.slides.keys())
    contaminated = verify_approved(manifest, audio_dir)
    if contaminated:
        raise RuntimeError(
            f"[{lec_id}] approved audio changed on disk for slide(s) {contaminated} -- "
            "re-approve (--approve) or restore the file before assembling"
        )

    wav_by_number = dict(zip(range(1, slide_count + 1), wav_paths))
    invalid = _invalid_slides(
        list(range(1, slide_count + 1)), wav_by_number, scripts, ref_voice_bytes, entries
    )
    invalid = [n for n in invalid if n not in approved_numbers]
    target_mp4 = _draft_or_final_path(out_mp4, invalid)
    target_mp4.parent.mkdir(parents=True, exist_ok=True)
    if invalid:
        logger.error(
            "Assembling a DRAFT (%s): %d/%d slides have no valid cached audio and are "
            "not approved: %s. Fix, re-run (--slides), or approve before treating this as final.",
            target_mp4.name, len(invalid), slide_count, invalid,
        )
    else:
        _cleanup_stale_draft(out_mp4)

    logger.info("Assembling video via ffmpeg -> %s", target_mp4)
    assemble_video(png_paths, wav_paths, video_dir, target_mp4, lec_id, strict=True)
    logger.info("Video successfully created at: %s", target_mp4)

    timeline = build_timeline(
        lec_id, target_mp4.name, bool(invalid),
        list(zip(range(1, slide_count + 1), wav_paths)), approved_numbers,
    )
    write_text_atomic(_timeline_path(target_mp4), timeline.model_dump_json(indent=2))
    # S8-b: human-readable review report, same folder/stem as the timeline.
    write_text_atomic(_report_path(target_mp4), build_report(timeline, audio_dir))

    return target_mp4


def _llm_config_repr(llm_client) -> str:
    """The generation settings that change an LLM artifact, for the cache key.

    Prompt and images alone are not the full input: swapping the model or the
    vision model silently reused the previous model's scripts, because neither
    appeared in the hash.
    """
    return f"text={llm_client.text_model};vlm={llm_client.vlm_model}"


def _generate_lecture_plan_cached(
    llm_client, slides, subject: str, name: str, plan_path: Path,
    reference_outline: str | None = None,
) -> LecturePlan:
    # S10-c/D-16: the plan gets a calibrated (inflated) minutes figure, not
    # raw TARGET_MINUTES -- see PLAN_LENGTH_CALIBRATION's own comment. Same
    # value at both call sites below so the cache key matches what was
    # actually generated.
    plan_minutes = TARGET_MINUTES * PLAN_LENGTH_CALIBRATION
    prompt_text = build_lecture_plan_prompt(slides, subject, name, plan_minutes, reference_outline)
    cache_key = content_hash(_PLAN_SYSTEM_PROMPT, prompt_text, _llm_config_repr(llm_client))

    if is_cache_valid(plan_path, cache_key):
        logger.info("Lecture plan cached, reusing %s", plan_path)
        return LecturePlan(**json.loads(plan_path.read_text(encoding="utf-8")))

    logger.info("Generating lecture plan (whole-slide-set analysis)...")
    plan = generate_lecture_plan(llm_client, slides, subject, name, plan_minutes, reference_outline)
    write_text_atomic(plan_path, json.dumps(plan.model_dump(), ensure_ascii=False, indent=2))
    write_cache_hash(plan_path, cache_key)
    logger.info("Lecture plan: %d sections covering %d slides", len(plan.sections), len(slides))
    return plan


def _generate_section_scripts_cached(
    llm_client,
    plan: LecturePlan,
    section,
    slides_in_section,
    png_paths_in_section,
    carry_forward: CarryForward | None,
    is_last_section: bool,
    section_result_path: Path,
    reference_notes: dict[int, str] | None = None,
):
    # S3-b: reference_notes flows into prompt_text, which is what the cache
    # key hashes below -- a changed/added/removed reference script therefore
    # invalidates the section cache automatically, no separate hash input
    # needed (SPEC S3-b "캐시 키... 확인하고, 아니면 포함").
    prompt_text = build_section_prompt(
        plan, section, slides_in_section, carry_forward, is_last_section, reference_notes=reference_notes
    )
    image_bytes = b"".join(p.read_bytes() for p in png_paths_in_section)
    carry_forward_repr = carry_forward.model_dump_json() if carry_forward else ""
    cache_key = content_hash(
        get_professor_system_prompt(),
        prompt_text,
        image_bytes,
        carry_forward_repr,
        _llm_config_repr(llm_client),
    )

    if is_cache_valid(section_result_path, cache_key):
        logger.info("Section %r cached, reusing", section.title)
        result = SectionScriptResult(**json.loads(section_result_path.read_text(encoding="utf-8")))
        validate_section_result(result, section)
        return result

    logger.info("Generating section %r (%d slides)...", section.title, len(section.slides))
    result = generate_section_scripts(
        llm_client, plan, section, slides_in_section, png_paths_in_section, carry_forward, is_last_section,
        reference_notes=reference_notes,
    )
    validate_section_result(result, section)
    write_text_atomic(
        section_result_path, json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
    )
    write_cache_hash(section_result_path, cache_key)
    return result


def validate_section_result(result: SectionScriptResult, section) -> None:
    """The LLM must return each of the section's slides exactly once.

    Unchecked, a dropped slide surfaced hours later as a KeyError in the TTS
    loop, and a duplicated one silently overwrote the first script. Both are
    cheap to catch here and expensive to discover at slide 40 of 48.
    """
    returned = [s.slide_number for s in result.slides]
    expected = set(section.slides)
    duplicates = {n for n in returned if returned.count(n) > 1}
    if duplicates:
        raise ValueError(f"section {section.title!r} returned slide(s) {sorted(duplicates)} more than once")
    missing = sorted(expected - set(returned))
    extra = sorted(set(returned) - expected)
    if missing or extra:
        raise ValueError(
            f"section {section.title!r} slide mismatch: missing={missing}, unexpected={extra}"
        )



def _hand_edited(script_path: Path) -> dict | None:
    """Return the on-disk script if a human changed it, else None.

    The sidecar records the hash of what this script last wrote. Matching means
    we still own the file and may overwrite it with fresh LLM output; differing
    means someone edited it since. A file with no sidecar predates this check,
    so it is treated as ours rather than silently frozen forever.
    """
    if not script_path.exists() or not cache_path_for(script_path).exists():
        return None
    current = script_path.read_text(encoding="utf-8")
    if is_cache_valid(script_path, content_hash(current)):
        return None
    return json.loads(current)


def _resolve_pdf_input(item: dict, input_dir: Path, lec_id: str) -> Path:
    """S3-a: a lecture entry may give a ``"pptx"`` path instead of ``"pdf"``.

    Convert it once into ``work_dir/input/<stem>.pdf`` via the same
    ``pptx_to_pdf`` LibreOffice helper ``renderer.render_slides`` uses, then
    everything downstream (parse/render/plan/script) is the existing
    PDF-based pipeline unchanged. Skips reconversion when the PDF already on
    disk is newer than the source PPTX.

    Caller must hold ``work_dir/.prep.lock`` (same as stages 1-4): two shards
    of the same lecture calling this concurrently would otherwise race on
    ``pptx_to_pdf``'s ``/tmp/soffice-<job_id>`` UserInstallation dir, same
    failure mode the lock already exists to prevent for PNG/script writes.

    ``job_id`` passed to ``pptx_to_pdf`` is *not* ``lec_id`` directly -- it
    only names a throwaway ``/tmp`` dir, and LibreOffice's handling of
    non-ASCII (Korean) characters in a ``file://`` UserInstallation URL is
    unverified. A short ascii hash keeps that question moot.
    """
    if "pptx" not in item:
        return item["pdf"].resolve()
    pptx_path = item["pptx"].resolve()
    converted = input_dir / f"{pptx_path.stem}.pdf"
    if not converted.exists() or converted.stat().st_mtime < pptx_path.stat().st_mtime:
        job_id = f"batch-{content_hash(lec_id)[:12]}"
        logger.info("[0/6] Converting PPTX -> PDF: %s", pptx_path)
        pptx_to_pdf(pptx_path, input_dir, job_id)
    return converted


def process_lecture(
    item: dict,
    llm_client: OpenAILLMClient,
    tts_pipe,
    base_work_dir: Path,
    output_dir: Path,
    shard: tuple[int, int] = (0, 1),
    target_slides: set[int] | None = None,
    entries: Sequence[dict] = (),
    verify_stt: bool = True,
) -> Path:
    lec_id = item["id"]
    out_mp4 = _lecture_output_mp4(lec_id, output_dir).resolve()
    clone_source_id = item.get("clone_from")

    work_dir = base_work_dir / lec_id
    rendered_dir = work_dir / "rendered"
    scripts_dir = work_dir / "scripts"
    sections_dir = work_dir / "sections"
    audio_dir = work_dir / "audio"
    video_dir = work_dir / "video"
    input_dir = work_dir / "input"

    for d in (work_dir, rendered_dir, scripts_dir, sections_dir, audio_dir, video_dir, input_dir, output_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Stages 0-4 write the converted PDF, PNGs and script JSON that every
    # shard then reads. Hold an exclusive lock across all of them: without
    # it a second shard starting at the same moment either races
    # _resolve_pdf_input's PPTX->PDF conversion (S3-a) or reads a slide PNG
    # mid-write, which the VLM rejects as "Invalid base64 image_url". The
    # loser of the race waits, then finds everything cached and falls
    # through in seconds.
    prep_lock = (work_dir / ".prep.lock").open("w")
    fcntl.flock(prep_lock, fcntl.LOCK_EX)

    pdf_path = _resolve_pdf_input(item, input_dir, lec_id)

    logger.info("=" * 60)
    logger.info("Processing [%s] %s (%s)", lec_id, item["name"], item["subject"])
    logger.info("PDF: %s", pdf_path)
    logger.info("=" * 60)

    # 1. Parse PDF
    logger.info("[1/6] Parsing PDF...")
    slides = parse_pdf(pdf_path)
    slide_count = len(slides)
    slide_by_number = {s.slide_number: s for s in slides}

    # 2. Render PNGs
    logger.info("[2/6] Rendering slides to PNG...")
    png_paths, _ = render_slides(pdf_path, rendered_dir, lec_id)
    png_by_number = {i + 1: p for i, p in enumerate(png_paths)}
    logger.info("Rendered %d PNG images", len(png_paths))

    # S3-b (D-11): optional reference lecture script -- fed into the prompt
    # builders as material to draw from, never used as the script itself.
    reference_notes: dict[int, str] | None = None
    reference_outline: str | None = None
    reference_script_path = item.get("reference_script")
    if reference_script_path is not None:
        ref_md_text = reference_script_path.read_text(encoding="utf-8")
        reference_notes = parse_reference_script(ref_md_text)
        reference_outline = summarize_reference_outline(ref_md_text)
        if reference_notes:
            max_ref_slide = max(reference_notes)
            if max_ref_slide != slide_count:
                logger.warning(
                    "[%s] reference script max slide number %d != actual slide count %d "
                    "(%s) -- slides missing from the reference are generated without it",
                    lec_id, max_ref_slide, slide_count, reference_script_path,
                )

    scripts: dict[int, dict] = {}  # slide_number -> {"target_seconds": ..., "script": ...}

    if clone_source_id:
        # 03/05 share identical body content -- only the cover slide differs.
        # Reuse the source lecture's plan+scripts wholesale, regenerate slide 1.
        src_dir = base_work_dir / clone_source_id
        logger.info("[3-4/6] Cloning plan + body scripts from %s...", src_dir)

        style = LectureStyle(
            density="detailed",
            tone="formal",
            approach="explanatory",
            supplement=f"과목명: {item['subject']}, 강의주제: {item['name']}. 강의시간 30분 맞춤.",
        )
        script_1_path = scripts_dir / "script_001.json"
        prompt_1 = f"과목명 도입부, {item['subject']} 강의로 표지를 설명"
        cache_key_1 = content_hash(get_professor_system_prompt(), prompt_1, png_by_number[1].read_bytes())
        if is_cache_valid(script_1_path, cache_key_1):
            data_1 = json.loads(script_1_path.read_text(encoding="utf-8"))
        else:
            data_1 = generate_script_for_slide_vision(
                client=llm_client,
                slide=slides[0],
                png_path=png_by_number[1],
                style=style,
                target_seconds=20.0,
                prev_slide=None,
                next_slide=slides[1] if slide_count > 1 else None,
                prev_script=None,
            )
            script_1_path.write_text(json.dumps(data_1, ensure_ascii=False, indent=2), encoding="utf-8")
            write_cache_hash(script_1_path, cache_key_1)
        scripts[1] = {"target_seconds": data_1.get("target_seconds", 20.0), "script": data_1.get("script", "")}

        for n in range(2, slide_count + 1):
            src_file = src_dir / "scripts" / f"script_{n:03d}.json"
            dst_file = scripts_dir / f"script_{n:03d}.json"
            shutil.copy2(src_file, dst_file)
            scripts[n] = json.loads(dst_file.read_text(encoding="utf-8"))
        logger.info("Copied %d scripts from source, generated custom slide 1", slide_count - 1)
    else:
        # 3. Lecture plan
        logger.info("[3/6] Building lecture plan...")
        plan_path = work_dir / "lecture_plan.json"
        plan = _generate_lecture_plan_cached(
            llm_client, slides, item["subject"], item["name"], plan_path, reference_outline
        )

        # 4. Section-by-section script generation
        logger.info("[4/6] Generating scripts section by section...")
        carry_forward: CarryForward | None = None
        for idx, section in enumerate(plan.sections):
            is_last_section = idx == len(plan.sections) - 1
            slides_in_section = [slide_by_number[n] for n in section.slides]
            png_paths_in_section = [png_by_number[n] for n in section.slides]
            section_result_path = sections_dir / f"section_{idx + 1:03d}.json"

            result = _generate_section_scripts_cached(
                llm_client,
                plan,
                section,
                slides_in_section,
                png_paths_in_section,
                carry_forward,
                is_last_section,
                section_result_path,
                reference_notes,
            )
            for s in result.slides:
                script_path = scripts_dir / f"script_{s.slide_number:03d}.json"
                generated = json.dumps(
                    {"slide_number": s.slide_number, "target_seconds": s.target_seconds, "script": s.script},
                    ensure_ascii=False, indent=2,
                )
                edited = _hand_edited(script_path)
                if edited is not None:
                    # Someone edited this slide's script by hand. Keep it: the
                    # point of per-slide regeneration is that a correction
                    # survives the next run, and only this slide's audio needs
                    # redoing (the script text is in the TTS cache key).
                    logger.info("Slide %d script was edited by hand -- keeping it", s.slide_number)
                    scripts[s.slide_number] = edited
                    continue
                scripts[s.slide_number] = {"target_seconds": s.target_seconds, "script": s.script}
                write_text_atomic(script_path, generated)
                write_cache_hash(script_path, content_hash(generated))
            carry_forward = result.carry_forward

    fcntl.flock(prep_lock, fcntl.LOCK_UN)
    prep_lock.close()

    if tts_pipe is None:
        logger.info("[5-6/6] --skip-tts: leaving TTS/video assembly out, scripts only.")
        return scripts_dir

    # 5. Synthesize Audio with Raon-Speech-9B (segmented + quality-gated, see raon_tts.py)
    logger.info("[5/6] Synthesizing TTS with Raon-Speech-9B & Professor Voice Cloning...")
    ref_voice_bytes = REF_VOICE.read_bytes() if REF_VOICE.exists() else b""
    approved_numbers = set(load_approvals(work_dir, lec_id).slides.keys())

    wav_paths, failed_slides = _synthesize_all_slides(
        tts_pipe, slide_count, scripts, audio_dir, ref_voice_bytes, shard, target_slides, approved_numbers,
        entries=entries, verify_stt=verify_stt,
    )
    shard_index, shard_count = shard

    if failed_slides:
        logger.error(
            "%d/%d slides failed the quality gate this run (candidates or new audio): %s",
            len(failed_slides), slide_count, failed_slides,
        )
    else:
        logger.info("All %d slides passed the quality gate.", slide_count)

    if shard_count > 1:
        # Never assemble from inside a shard. Checking that the peer's wavs
        # merely exist is not enough -- a previous run leaves stale wavs on
        # disk, so shard 1 happily encoded a video from shard 0's old audio
        # while shard 0 was still regenerating it. Run the tool once more
        # without --shard to assemble; everything is cached by then.
        logger.info("[6/6] Sharded run -- re-run without --shard to assemble the video.")
        return out_mp4

    # 6. Assemble Video + write timeline (S1-e DRAFT check extended with
    # approvals, S2's verify_approved contamination guard) -- see
    # _assemble_with_approvals for the DRAFT/timeline logic shared with
    # --assemble-only.
    logger.info("[6/6] Assembling video + timeline...")
    return _assemble_with_approvals(
        lec_id, work_dir, audio_dir, video_dir, out_mp4, slide_count,
        scripts, png_paths, wav_paths, ref_voice_bytes, entries,
    )


def assemble_only(
    item: dict, base_work_dir: Path, output_dir: Path, entries: Sequence[dict] = ()
) -> Path:
    """``--assemble-only``: assemble the current on-disk PNGs/WAVs into a
    video + timeline. Loads no TTS model and makes no LLM call -- slide
    scripts are read straight from the ``scripts/script_NNN.json`` cache a
    prior full run already wrote (that's all ``_invalid_slides`` needs for
    its cache-key check), so there is nothing here that requires calling the
    LLM again.
    """
    lec_id = item["id"]
    out_mp4 = _lecture_output_mp4(lec_id, output_dir).resolve()
    work_dir = base_work_dir / lec_id
    rendered_dir = work_dir / "rendered"
    scripts_dir = work_dir / "scripts"
    audio_dir = work_dir / "audio"
    video_dir = work_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    png_paths = sorted(rendered_dir.glob("slide_*.png"))
    if not png_paths:
        raise FileNotFoundError(
            f"[{lec_id}] no rendered slides in {rendered_dir} -- run a full generation first"
        )
    slide_count = len(png_paths)

    scripts: dict[int, dict] = {}
    for n in range(1, slide_count + 1):
        script_path = scripts_dir / f"script_{n:03d}.json"
        if not script_path.exists():
            raise FileNotFoundError(f"[{lec_id}] no cached script for slide {n} at {script_path}")
        scripts[n] = json.loads(script_path.read_text(encoding="utf-8"))

    wav_paths = [audio_dir / f"slide_{n:03d}.wav" for n in range(1, slide_count + 1)]
    ref_voice_bytes = REF_VOICE.read_bytes() if REF_VOICE.exists() else b""

    return _assemble_with_approvals(
        lec_id, work_dir, audio_dir, video_dir, out_mp4, slide_count,
        scripts, png_paths, wav_paths, ref_voice_bytes, entries,
    )


def _cli_approve(item: dict, base_work_dir: Path, slides_arg: str, entries: Sequence[dict] = ()) -> None:
    """``--approve``: pin the current ``slide_NNN.wav`` as approved
    (``source="existing"``) for each slide in *slides_arg*. Reads only the
    on-disk script cache to compute ``gate_ok``; no LLM/TTS model is loaded.
    """
    lec_id = item["id"]
    work_dir = base_work_dir / lec_id
    scripts_dir = work_dir / "scripts"
    audio_dir = work_dir / "audio"
    ref_voice_bytes = REF_VOICE.read_bytes() if REF_VOICE.exists() else b""

    manifest = load_approvals(work_dir, lec_id)
    for n in sorted(_parse_slides_arg(slides_arg) or set()):
        gate_ok = None
        script_path = scripts_dir / f"script_{n:03d}.json"
        if script_path.exists():
            sc = json.loads(script_path.read_text(encoding="utf-8"))
            out_wav = audio_dir / f"slide_{n:03d}.wav"
            cache_key = _tts_cache_key(sc.get("script", ""), ref_voice_bytes, sc.get("target_seconds"), entries)
            gate_ok = is_cache_valid(out_wav, cache_key)
        manifest = approve(manifest, audio_dir, n, source="existing", gate_ok=gate_ok)
        logger.info("Approved slide %d (existing, gate_ok=%s)", n, gate_ok)
    save_approvals(work_dir, manifest)


def _cli_approve_passing(item: dict, base_work_dir: Path, entries: Sequence[dict] = ()) -> None:
    """``--approve-passing``: approve every slide whose current WAV is still
    valid for the current TTS cache key (``source="gate_pass"``).

    Slides already approved (by any source, e.g. a prior ``--promote``) are
    left alone -- this command is for picking up slides nobody has reviewed
    yet, not for silently downgrading/overwriting an existing approval
    record (and its note) with a plain gate-pass one.
    """
    lec_id = item["id"]
    work_dir = base_work_dir / lec_id
    scripts_dir = work_dir / "scripts"
    audio_dir = work_dir / "audio"
    ref_voice_bytes = REF_VOICE.read_bytes() if REF_VOICE.exists() else b""

    manifest = load_approvals(work_dir, lec_id)
    approved_count = 0
    for script_path in sorted(scripts_dir.glob("script_*.json")):
        n = int(script_path.stem.rsplit("_", 1)[1])
        if n in manifest.slides:
            continue
        sc = json.loads(script_path.read_text(encoding="utf-8"))
        out_wav = audio_dir / f"slide_{n:03d}.wav"
        cache_key = _tts_cache_key(sc.get("script", ""), ref_voice_bytes, sc.get("target_seconds"), entries)
        if is_cache_valid(out_wav, cache_key):
            manifest = approve(manifest, audio_dir, n, source="gate_pass", gate_ok=True)
            approved_count += 1
    save_approvals(work_dir, manifest)
    logger.info("Approved %d slide(s) currently passing the cache/quality gate", approved_count)


def _cli_promote(item: dict, base_work_dir: Path, slides_arg: str, allow_failed: bool, note: str) -> None:
    """``--promote``: promote each slide's reviewed candidate to the main WAV."""
    lec_id = item["id"]
    work_dir = base_work_dir / lec_id
    audio_dir = work_dir / "audio"

    manifest = load_approvals(work_dir, lec_id)
    for n in sorted(_parse_slides_arg(slides_arg) or set()):
        manifest = promote_candidate(manifest, audio_dir, n, allow_failed=allow_failed, note=note)
        save_approvals(work_dir, manifest)
        logger.info("Promoted candidate for slide %d", n)


def _parse_slides_arg(arg: str | None) -> set[int] | None:
    if not arg:
        return None
    slides: set[int] = set()
    for part in arg.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            slides.update(range(int(start), int(end) + 1))
        else:
            slides.add(int(part))
    return slides


_SLIDE_WAV_RE = re.compile(r"^slide_\d{3}\.wav$")


@dataclass
class LectureStatus:
    """Disk-only progress summary for one lecture (S8-c). Reused as-is by a
    future web UI, per SPEC -- only the CLI formats it into text."""

    slides: int
    scripts: int
    audio: int
    qc_fail: int
    qc_missing: int
    candidates: int
    approved: int
    video_state: str  # "final" | "draft" | "none"
    video_path: Path | None


def compute_lecture_status(item: dict, base_work_dir: Path, output_dir: Path) -> LectureStatus:
    """Pure, disk-only status for ``--status`` (S8-c). Reads globs/JSON
    sidecars only -- never loads the TTS model or the LLM client, never
    writes anything.

    "검사 실패" counts only ``qc.json`` with ``ok=false``; a main WAV with no
    (or unreadable) ``.qc.json`` is counted separately as ``qc_missing``, per
    SPEC ("qc가 없으면 세지 않고 별도 표시").
    """
    lec_id = item["id"]
    work_dir = base_work_dir / lec_id
    rendered_dir = work_dir / "rendered"
    scripts_dir = work_dir / "scripts"
    audio_dir = work_dir / "audio"

    n_slides = len(list(rendered_dir.glob("slide_*.png"))) if rendered_dir.is_dir() else 0
    n_scripts = len(list(scripts_dir.glob("script_*.json"))) if scripts_dir.is_dir() else 0

    main_wavs: list[Path] = []
    n_candidates = 0
    if audio_dir.is_dir():
        main_wavs = sorted(p for p in audio_dir.glob("slide_*.wav") if _SLIDE_WAV_RE.match(p.name))
        n_candidates = len(list(audio_dir.glob("slide_*.cand.wav")))

    qc_fail = qc_missing = 0
    for wav in main_wavs:
        qc_file = qc_path_for(wav)
        data = None
        if qc_file.exists():
            try:
                data = json.loads(qc_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = None
        if data is None:
            qc_missing += 1
        elif data.get("ok") is False:
            qc_fail += 1

    n_approved = len(load_approvals(work_dir, lec_id).slides)

    out_mp4 = _lecture_output_mp4(lec_id, output_dir)
    draft_mp4 = out_mp4.with_name(out_mp4.stem + "_DRAFT.mp4")
    if out_mp4.exists():
        video_state, video_path = "final", out_mp4
    elif draft_mp4.exists():
        video_state, video_path = "draft", draft_mp4
    else:
        video_state, video_path = "none", None

    return LectureStatus(
        slides=n_slides, scripts=n_scripts, audio=len(main_wavs),
        qc_fail=qc_fail, qc_missing=qc_missing, candidates=n_candidates,
        approved=n_approved, video_state=video_state, video_path=video_path,
    )


def _format_status_line(idx: int, lec_id: str, st: LectureStatus) -> str:
    video = {
        "final": f"최종 ({st.video_path})",
        "draft": f"DRAFT ({st.video_path})",
        "none": "없음",
    }[st.video_state]
    return (
        f"{idx:2d} {lec_id:45s} 슬라이드 {st.slides:3d}  대본 {st.scripts:3d}  음성 {st.audio:3d}  "
        f"검사실패 {st.qc_fail}(qc없음 {st.qc_missing})  후보대기 {st.candidates}  "
        f"승인 {st.approved}  영상 {video}"
    )


def main():
    parser = argparse.ArgumentParser(description="Batch lecture video generation")
    parser.add_argument(
        "--only", type=str, default=None,
        help=f"Run only specific lecture id or index (1-{len(LECTURES)})",
    )
    parser.add_argument(
        "--slides", type=str, default=None,
        help="Comma-separated list of slide numbers to selectively regenerate (e.g. '23,41,48' or '23-25'). "
             "Other slides keep their existing audio.",
    )
    parser.add_argument("--skip-tts", action="store_true", help="Skip TTS synthesis (test script/render only)")
    parser.add_argument("--gpu", type=int, default=0, help="CUDA device index for the TTS model")
    parser.add_argument(
        "--shard", type=str, default="0/1",
        help="Take only every Nth slide, as i/N. Run one process per GPU "
             "(--gpu 0 --shard 0/2 and --gpu 1 --shard 1/2), then once more "
             "unsharded to assemble the video from the cached audio.",
    )
    # Exactly one approval command per invocation -- spec: an approval command
    # "modifies only the approval file, then exits" (no combining e.g.
    # --approve with --assemble-only in one run).
    approval_group = parser.add_mutually_exclusive_group()
    approval_group.add_argument(
        "--approve", type=str, default=None,
        help="S2: approve the current slide_NNN.wav as-is for these slides (e.g. '1-48'), "
             "source=existing. Requires --only. Loads no TTS model/LLM client.",
    )
    approval_group.add_argument(
        "--approve-passing", action="store_true",
        help="S2: approve every slide whose current audio is valid for the current cache key "
             "(source=gate_pass). Requires --only. Loads no TTS model/LLM client.",
    )
    approval_group.add_argument(
        "--promote", type=str, default=None,
        help="S2: promote reviewed slide_NNN.cand.wav to the approved main WAV for these "
             "slides (e.g. '12,15'). Requires --only. Loads no TTS model/LLM client.",
    )
    approval_group.add_argument(
        "--assemble-only", action="store_true",
        help="S2: assemble the current on-disk PNGs/WAVs into a video + timeline.json "
             "without synthesizing audio. Requires --only. Loads no TTS model/LLM client.",
    )
    approval_group.add_argument(
        "--status", action="store_true",
        help="S8-c: print a one-line-per-lecture progress table (optionally --only) to "
             "stdout and exit. Disk reads only -- no TTS model/LLM client, no writes.",
    )
    parser.add_argument(
        "--allow-failed", action="store_true",
        help="With --promote: allow promoting a candidate that failed the quality gate.",
    )
    parser.add_argument(
        "--note", type=str, default="",
        help="With --promote: note recorded on the approval entry.",
    )
    parser.add_argument(
        "--no-stt", action="store_true",
        help="S6-a: disable the post-synthesis STT fidelity check (on by default). "
             "STT adds one transcription pass per slide and can turn a previously "
             "gate-passing slide into a candidate/DRAFT if the transcript doesn't "
             "match (content-fidelity reasons feed the same gate as everything else).",
    )
    args = parser.parse_args()

    base_work = Path("data/work_batch")
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    # S6-d: professor-approved pronunciation overrides, applied only right
    # before synthesis (never rewrites script JSON). Every shipped entry is
    # approved:false, so this is a no-op until someone flips one to true.
    pronunciation_entries = load_pronunciation_entries(Path("config/pronunciation.yaml"))

    approval_mode = bool(args.approve or args.approve_passing or args.promote or args.assemble_only)
    if approval_mode and not args.only:
        parser.error(
            "--approve/--approve-passing/--promote/--assemble-only require --only <lecture id or index>"
        )

    selected = LECTURES
    if args.only:
        if args.only.isdigit():
            idx = int(args.only) - 1
            if not 0 <= idx < len(LECTURES):
                parser.error(f"--only {args.only}: index must be in 1..{len(LECTURES)}")
            selected = [LECTURES[idx]]
        else:
            selected = [lec for lec in LECTURES if args.only in lec["id"]]

    if args.status:
        # S8-c: disk-only status table -- no TTS/LLM load, no --only-must-be-
        # unique requirement (unlike the other approval_group commands, this
        # one is meant to be run over many/all lectures at once).
        for lec in selected:
            st = compute_lecture_status(lec, base_work, output_dir)
            print(_format_status_line(LECTURES.index(lec) + 1, lec["id"], st))
        return

    if approval_mode and len(selected) != 1:
        parser.error(
            f"--only {args.only!r} must match exactly one lecture for an approval command "
            f"(matched: {[s['id'] for s in selected]})"
        )

    if approval_mode:
        # Approval-only commands touch only approved.json / on-disk audio --
        # never load the TTS model or the LLM client (SPEC S2 §3).
        item = selected[0]
        if args.approve:
            _cli_approve(item, base_work, args.approve, pronunciation_entries)
        if args.approve_passing:
            _cli_approve_passing(item, base_work, pronunciation_entries)
        if args.promote:
            _cli_promote(item, base_work, args.promote, args.allow_failed, args.note)
        if args.assemble_only:
            mp4_path = assemble_only(item, base_work, output_dir, pronunciation_entries)
            logger.info("Assembled (no synth/LLM): %s", mp4_path)
        return

    logger.info("Initializing LLM client (FactChat gpt-5.6-luna)...")
    llm_client = OpenAILLMClient()

    tts_pipe = None
    if not args.skip_tts:
        logger.info("Loading Raon-Speech-9B TTS model on cuda:%d...", args.gpu)
        tts_pipe = load_raon_pipeline(TTS_MODEL_ID, device=f"cuda:{args.gpu}", dtype="bfloat16")
        logger.info("Raon-Speech-9B ready!")

    shard_index, shard_count = (int(x) for x in args.shard.split("/"))
    if not 0 <= shard_index < shard_count:
        parser.error(f"--shard {args.shard}: index must be in 0..{shard_count - 1}")
    shard = (shard_index, shard_count)
    if shard_count > 1:
        logger.info("Shard %d of %d on cuda:%d", shard_index, shard_count, args.gpu)

    target_slides = _parse_slides_arg(args.slides)
    if target_slides:
        logger.info("Target slides to selectively regenerate: %s", sorted(target_slides))

    logger.info("Lectures to generate: %d", len(selected))
    results = []

    verify_stt = not args.no_stt
    for lec in selected:
        t0 = time.time()
        mp4_path = process_lecture(
            lec, llm_client, tts_pipe, base_work, output_dir, shard, target_slides=target_slides,
            entries=pronunciation_entries, verify_stt=verify_stt,
        )
        elapsed = time.time() - t0
        results.append((lec["id"], mp4_path, elapsed))

    logger.info("=" * 60)
    logger.info("ALL COMPLETED!")
    for lid, path, el in results:
        logger.info("  [%s] -> %s (Time: %.1f min)", lid, path, el / 60.0)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
