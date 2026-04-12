from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

from lecture_auto.pipeline.tts import (
    load_tts as load_qwen_tts,
    merge_audio,
    synthesize_slide as synthesize_qwen_slide,
)
from lecture_auto.pipeline.video import assemble_video
from lecture_auto.schemas.manifest import LectureStyle, SlideManifest, SlideRecord
from lecture_auto.demo.jobs import (
    DEFAULT_TTS_MODEL,
    _add_version_entry,
    _load_job_snapshot,
    _save_job_snapshot,
    _resolve_voice_reference,
    get_demo_job_paths,
    sha256_file,
    _base_pipeline_meta,
    _refresh_library_artifacts,
)
from lecture_auto.demo.control import _check_stop
from lecture_auto.demo.state import (
    append_event,
    get_job,
    set_artifact,
    update_metadata,
    update_stage,
    upsert_slide,
)
from lecture_auto.demo.ai import (
    _apply_glossary,
    _normalize_vlm_payload,
    _should_use_fast_tts,
)

_TTS_LOCK = threading.Lock()
_QWEN_TTS_MODEL = None
_LOCAL_TTS_MODEL = None
_LOCAL_TTS_TOKENIZER = None


def _get_local_tts():
    global _LOCAL_TTS_MODEL, _LOCAL_TTS_TOKENIZER
    if _LOCAL_TTS_MODEL is not None and _LOCAL_TTS_TOKENIZER is not None:
        return _LOCAL_TTS_MODEL, _LOCAL_TTS_TOKENIZER

    with _TTS_LOCK:
        if _LOCAL_TTS_MODEL is not None and _LOCAL_TTS_TOKENIZER is not None:
            return _LOCAL_TTS_MODEL, _LOCAL_TTS_TOKENIZER

        import torch
        from transformers import AutoTokenizer, VitsModel

        model_id = os.environ.get("DEMO_TTS_MODEL", "facebook/mms-tts-kor")
        _LOCAL_TTS_TOKENIZER = AutoTokenizer.from_pretrained(model_id)
        _LOCAL_TTS_MODEL = VitsModel.from_pretrained(model_id)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _LOCAL_TTS_MODEL = _LOCAL_TTS_MODEL.to(device)
        _LOCAL_TTS_MODEL.eval()
        return _LOCAL_TTS_MODEL, _LOCAL_TTS_TOKENIZER


def _get_qwen_tts():
    global _QWEN_TTS_MODEL
    if _QWEN_TTS_MODEL is not None:
        return _QWEN_TTS_MODEL

    with _TTS_LOCK:
        if _QWEN_TTS_MODEL is not None:
            return _QWEN_TTS_MODEL
        _QWEN_TTS_MODEL = load_qwen_tts(os.environ.get("DEMO_QWEN_TTS_MODEL", DEFAULT_TTS_MODEL))
        return _QWEN_TTS_MODEL


def _split_tts_segments(text: str, limit: int = 180) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    parts = re.split(r"(?<=[.!?])\s+|(?<=[다요죠])\s+", normalized)
    segments: list[str] = []
    current = ""
    for part in parts:
        chunk = part.strip()
        if not chunk:
            continue
        candidate = f"{current} {chunk}".strip()
        if current and len(candidate) > limit:
            segments.append(current)
            current = chunk
        else:
            current = candidate
    if current:
        segments.append(current)
    return segments or [normalized]


def _synthesize_with_flite_fallback(text: str, output_path: Path) -> None:
    safe = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"flite=text='{safe}':voice=slt",
        "-ar",
        "24000",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
    except subprocess.TimeoutExpired:
        logger.warning("subprocess timed out: ffmpeg flite synthesis")
        raise RuntimeError("ffmpeg flite synthesis timed out")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg flite synthesis failed")


def _synthesize_with_local_korean_fallback(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import numpy as np
        import soundfile as sf
        import torch

        model, tokenizer = _get_local_tts()
        device = next(model.parameters()).device
        sample_rate = int(getattr(model.config, "sampling_rate", 16000))
        segments = _split_tts_segments(text)
        waves: list[np.ndarray] = []

        for segment in segments:
            inputs = tokenizer(segment, return_tensors="pt")
            inputs = {key: value.to(device) for key, value in inputs.items()}
            with torch.no_grad():
                waveform = model(**inputs).waveform[0].detach().cpu().numpy()
            waves.append(waveform.astype("float32"))
            waves.append(np.zeros(int(sample_rate * 0.12), dtype="float32"))

        merged = np.concatenate(waves[:-1] if len(waves) > 1 else waves)
        sf.write(str(output_path), merged, sample_rate)
    except Exception:
        _synthesize_with_flite_fallback(text, output_path)


def _synthesize_demo_tts(text: str, output_path: Path, voice_reference: Path | None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        model = _get_qwen_tts()
        synthesize_qwen_slide(model, text, output_path, voice_ref_path=voice_reference)
        return
    except Exception:
        _synthesize_with_local_korean_fallback(text, output_path)


def _input_pdf_path(job_paths) -> Path | None:
    pdf_files = sorted(job_paths.input_dir.glob("*.pdf"))
    return pdf_files[0] if pdf_files else None


def _load_saved_notes(job_paths, manifest: SlideManifest) -> list[dict]:
    notes: list[dict] = []
    pdf_path = _input_pdf_path(job_paths)
    for slide in manifest.slides:
        slide_number = slide.slide_number
        note_path = job_paths.vlm_dir / f"vlm_note_{slide_number:03d}.json"
        if note_path.exists():
            loaded = json.loads(note_path.read_text(encoding="utf-8"))
            if pdf_path is not None:
                loaded = _normalize_vlm_payload(loaded, slide, pdf_path)
                note_path.write_text(json.dumps(loaded, ensure_ascii=False, indent=2), encoding="utf-8")
            notes.append(loaded)
        else:
            notes.append({})
    return notes


def _render_script_stage(job_id: str, manifest: SlideManifest, notes: list[dict]) -> list[dict]:
    from lecture_auto.demo.ai import (
        _build_script_slide_payloads,
        _call_script_model_batch,
        _compose_script,
        _evidence_payload,
        _extract_keywords,
        _extract_title,
        SCRIPT_BATCH_SIZE,
    )
    from lecture_auto.demo.state import append_event, upsert_slide, update_stage
    from datetime import UTC, datetime

    job_paths = get_demo_job_paths(job_id)
    job = get_job(job_id) or {}
    settings = job.get("settings") or {}
    target_seconds = (manifest.target_minutes * 60) / max(1, manifest.slide_count)
    scripts: list[dict] = []
    generated_scripts: dict[int, str] = {}

    slide_payloads = _build_script_slide_payloads(manifest, notes, target_seconds, settings)
    try:
        total_batches = max(1, (len(slide_payloads) + SCRIPT_BATCH_SIZE - 1) // SCRIPT_BATCH_SIZE)
        for batch_index, start in enumerate(range(0, len(slide_payloads), SCRIPT_BATCH_SIZE), start=1):
            chunk = slide_payloads[start:start + SCRIPT_BATCH_SIZE]
            generated_scripts.update(_call_script_model_batch(chunk, target_seconds, settings))
            append_event(
                job_id,
                "script",
                f"LLM 스크립트 배치 생성 완료 {batch_index}/{total_batches}",
            )
    except Exception as exc:
        append_event(job_id, "script", f"LLM batch script fallback used: {exc}")

    for idx, slide in enumerate(manifest.slides, start=1):
        next_title = _extract_title(manifest.slides[idx]) if idx < len(manifest.slides) else None
        fallback_script = _compose_script(slide, notes[idx - 1], next_title, target_seconds)
        script = fallback_script
        generated_script = generated_scripts.get(slide.slide_number)
        if generated_script:
            script["script"] = generated_script
            script["keywords"] = _extract_keywords(generated_script)
            script["tts_text"] = generated_script
        script_path = job_paths.scripts_dir / f"script_{slide.slide_number:03d}.json"
        script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        scripts.append(script)
        upsert_slide(
            job_id,
            slide.slide_number,
            {
                "script": script,
                "evidence": _evidence_payload(slide, notes[idx - 1], script),
            },
        )
        progress = int(idx / max(1, len(manifest.slides)) * 100)
        update_stage(job_id, "script", status="running", progress=progress, detail=f"슬라이드 {idx}/{len(manifest.slides)} 스크립트 생성 완료")
    pipeline_meta = job.get("pipeline_meta") or _base_pipeline_meta()
    pipeline_meta["last_script_generated_at"] = datetime.now(UTC).isoformat()
    update_metadata(job_id, pipeline_meta=pipeline_meta)
    append_event(job_id, "script", "발표 스크립트 생성 단계 완료")
    update_stage(job_id, "script", status="done", progress=100, detail="모든 슬라이드 스크립트 생성 완료")
    _add_version_entry(job_id, kind="script_generation", summary="전체 슬라이드 스크립트 재생성 완료")
    return scripts


def _run_tts_loop(
    job_id: str,
    scripts: list[dict],
    job_paths,
    voice_reference,
    fast_tts: bool,
    glossary: dict,
) -> list[Path]:
    wav_paths: list[Path] = []
    for idx, script in enumerate(scripts, start=1):
        _check_stop(job_id, "tts")
        wav_path = job_paths.audio_dir / f"audio_{script['slide_number']:03d}.wav"
        tts_text = _apply_glossary(script["tts_text"], glossary)
        if fast_tts:
            _synthesize_with_local_korean_fallback(tts_text, wav_path)
        else:
            _synthesize_demo_tts(tts_text, wav_path, voice_reference)
        wav_paths.append(wav_path)
        upsert_slide(
            job_id,
            script["slide_number"],
            {
                "audio_url": f"/demo/api/jobs/{job_id}/audio/{script['slide_number']}/wav",
                "tts_preview": tts_text,
                "tts_status": "done",
            },
        )
        progress = int(idx / max(1, len(scripts)) * 100)
        update_stage(job_id, "tts", status="running", progress=progress, detail=f"슬라이드 {idx}/{len(scripts)} 음성 생성 완료")
    return wav_paths


def _assemble_final_video(job_id: str, job_paths, wav_paths: list[Path]) -> None:
    _check_stop(job_id, "video")
    png_paths = sorted(job_paths.rendered_dir.glob("slide_*.png"))
    update_stage(job_id, "video", status="running", progress=90, detail="단일 MP4로 최종 강의 영상 조립 중")
    output_video = job_paths.artifacts_dir / f"lecture_{job_id}.mp4"
    assemble_video(
        png_paths=png_paths,
        wav_paths=wav_paths,
        video_dir=job_paths.artifacts_dir / "video_clips",
        output_path=output_video,
        job_id=job_id,
    )
    set_artifact(job_id, "video_url", f"/demo/api/jobs/{job_id}/video")
    append_event(job_id, "video", f"Lecture video assembled: {output_video.name}")
    update_stage(job_id, "video", status="done", progress=100, detail="Lecture MP4 generated")


def _render_media_stage(job_id: str, manifest: SlideManifest, scripts: list[dict]) -> None:
    job_paths = get_demo_job_paths(job_id)
    voice_reference, voice_label = _resolve_voice_reference(job_id)
    fast_tts = _should_use_fast_tts(manifest)
    pipeline_meta = (get_job(job_id) or {}).get("pipeline_meta") or _base_pipeline_meta()
    pipeline_meta["tts_mode"] = "fast_local" if fast_tts else "qwen_clone"
    if voice_label:
        update_metadata(job_id, voice_reference_name=voice_label)
        append_event(job_id, "tts", f"음성 레퍼런스 등록: {voice_label}")
    if fast_tts:
        append_event(
            job_id,
            "tts",
            f"슬라이드 수가 많아 속도 우선 음성 모드 사용: {manifest.slide_count}장 문서는 로컬 한국어 TTS로 생성",
        )

    tts_detail = "빠른 데모 음성 생성 시작" if fast_tts else "보이스 클론 음성 생성 시작"
    update_stage(job_id, "tts", status="running", progress=10, detail=tts_detail)
    glossary = (get_job(job_id) or {}).get("glossary") or {}

    wav_paths = _run_tts_loop(job_id, scripts, job_paths, voice_reference, fast_tts, glossary)

    merged_path = job_paths.audio_dir / "lecture_merged.wav"
    merge_audio(job_paths.audio_dir, merged_path)
    set_artifact(job_id, "merged_audio_url", f"/demo/api/jobs/{job_id}/audio/merged")
    append_event(job_id, "tts", "슬라이드별 음성과 병합 오디오 생성 완료")
    update_stage(job_id, "tts", status="done", progress=100, detail="음성 합성 완료")

    _assemble_final_video(job_id, job_paths, wav_paths)

    pipeline_meta["last_media_generated_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    update_metadata(job_id, pipeline_meta=pipeline_meta)
    _refresh_library_artifacts(job_id)
    _add_version_entry(job_id, kind="media_generation", summary="음성과 최종 영상 산출물 갱신 완료")


def _write_manifest(
    job_id: str,
    pdf_path: Path,
    slides: list[SlideRecord],
    lecture_name: str,
    target_minutes: int,
) -> SlideManifest:
    job = get_job(job_id) or {}
    settings = job.get("settings") or {}
    density = str(settings.get("lecture_density", "표준형")).lower()
    manifest = SlideManifest(
        job_id=job_id,
        file_sha256=sha256_file(pdf_path),
        lecture_name=lecture_name,
        subject_name="Demo Lecture",
        target_audience=str(settings.get("audience", "presentation")),
        target_minutes=max(1, target_minutes),
        style=LectureStyle(
            density="detailed" if "자세" in density else "concise",
            tone="formal",
            approach="explanatory",
        ),
        slide_count=len(slides),
        slides=slides,
    )
    job_paths = get_demo_job_paths(job_id)
    job_paths.manifest_path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return manifest
