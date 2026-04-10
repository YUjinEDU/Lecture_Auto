from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from lecture_auto.schemas.manifest import SlideManifest
from lecture_auto.pipeline.parser_pdf import parse_pdf
from lecture_auto.pipeline.renderer import pdf_to_pngs
from lecture_auto.demo.jobs import (
    _add_version_entry,
    _base_pipeline_meta,
    _load_job_snapshot,
    _refresh_library_artifacts,
    _resolve_voice_reference,
    _save_job_snapshot,
    create_demo_job,
    get_demo_job_paths,
    sha256_file,
)
from lecture_auto.demo.control import (
    _check_stop,
    _clear_stop_flag,
    _get_stop_flag,
    request_stop,
)
from lecture_auto.demo.ai import (
    _apply_glossary,
    _build_script_slide_payloads,
    _call_script_model_batch,
    _compose_script,
    _evidence_payload,
    _extract_body_lines,
    _extract_keywords,
    _extract_title,
    _normalize_line,
    _run_gpt_vlm,
    _should_use_fast_tts,
)
from lecture_auto.demo.synthesis import (
    _input_pdf_path,
    _load_saved_notes,
    _render_media_stage,
    _render_script_stage,
    _synthesize_demo_tts,
    _write_manifest,
)
from lecture_auto.demo.state import (
    append_event,
    get_job,
    mark_failed,
    mark_stopped,
    set_artifact,
    update_metadata,
    update_stage,
    upsert_slide,
)


def _run_parse_render_stage(
    job_id: str, pdf_path: Path, lecture_name: str, target_minutes: int
) -> tuple["SlideManifest", list[Path]]:
    job_paths = get_demo_job_paths(job_id)

    update_stage(job_id, "parse", status="running", progress=15, detail="PDF 구조 분석 중")
    slides = parse_pdf(pdf_path)
    manifest = _write_manifest(job_id, pdf_path, slides, lecture_name, target_minutes)
    append_event(job_id, "parse", f"Parsed {len(slides)} slides from PDF")
    update_stage(job_id, "parse", status="done", progress=100, detail=f"총 {len(slides)}개 슬라이드 파싱 완료")
    _check_stop(job_id, "parse")

    update_stage(job_id, "render", status="running", progress=25, detail="슬라이드 미리보기 생성 중")
    png_paths = pdf_to_pngs(pdf_path, job_paths.rendered_dir)
    append_event(job_id, "render", f"Rendered {len(png_paths)} slide previews")
    update_stage(job_id, "render", status="done", progress=100, detail=f"총 {len(png_paths)}개 슬라이드 이미지 생성 완료")
    _check_stop(job_id, "render")

    return manifest, png_paths


def run_demo_pipeline(job_id: str, pdf_path: Path, lecture_name: str, target_minutes: int) -> None:
    current_stage = "parse"
    _clear_stop_flag(job_id)
    update_metadata(job_id, status="running")
    try:
        job = get_job(job_id) or {}
        pipeline_meta = job.get("pipeline_meta") or _base_pipeline_meta()
        pipeline_meta["input_sha256"] = sha256_file(pdf_path)
        pipeline_meta["started_at"] = datetime.now(UTC).isoformat()
        update_metadata(job_id, pipeline_meta=pipeline_meta)
        _save_job_snapshot(job_id)

        manifest, png_paths = _run_parse_render_stage(job_id, pdf_path, lecture_name, target_minutes)

        current_stage = "vlm"
        vlm_model = __import__("os").environ.get("DEMO_VLM_MODEL", "gpt-5.4-mini")
        update_stage(job_id, "vlm", status="running", progress=5, detail=f"GPT 슬라이드 시각 분석 시작 ({vlm_model})")
        notes: list[dict] = []
        for idx, slide in enumerate(manifest.slides, start=1):
            _check_stop(job_id, current_stage)
            png_path = job_paths.rendered_dir / slide.png_path
            note = _run_gpt_vlm(slide, png_path, pdf_path)
            note_path = job_paths.vlm_dir / f"vlm_note_{slide.slide_number:03d}.json"
            note_path.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
            notes.append(note)
            upsert_slide(
                job_id,
                slide.slide_number,
                {
                    "title": _extract_title(slide),
                    "png_url": f"/demo/api/jobs/{job_id}/slides/{slide.slide_number}/png",
                    "vlm_note": note,
                    "evidence": _evidence_payload(slide, note, None),
                },
            )
            progress = int(idx / max(1, len(manifest.slides)) * 100)
            update_stage(job_id, "vlm", status="running", progress=progress, detail=f"슬라이드 {idx}/{len(manifest.slides)} 시각 분석 완료")
        append_event(job_id, "vlm", f"GPT 슬라이드 시각 분석 완료 ({len(manifest.slides)}개)")
        update_stage(job_id, "vlm", status="done", progress=100, detail="모든 슬라이드 시각 분석 완료")
        _check_stop(job_id, current_stage)

        current_stage = "script"
        update_stage(job_id, "script", status="running", progress=55, detail="GPT 강의 스크립트 생성 중")
        scripts = _render_script_stage(job_id, manifest, notes)
        _check_stop(job_id, current_stage)

        current_stage = "tts"
        _render_media_stage(job_id, manifest, scripts)

        current_stage = "package"
        update_stage(job_id, "package", status="running", progress=95, detail="다운로드 패키지 정리 중")
        set_artifact(job_id, "package_url", f"/demo/api/jobs/{job_id}/package/download")
        append_event(job_id, "package", "ZIP 패키지 다운로드 준비 완료")
        update_stage(job_id, "package", status="done", progress=100, detail="데모 산출물 준비 완료")
        _refresh_library_artifacts(job_id)
        _save_job_snapshot(job_id)
    except StopIteration as exc:
        mark_stopped(job_id, current_stage, str(exc))
        _save_job_snapshot(job_id)
    except Exception as exc:
        mark_failed(job_id, current_stage, str(exc))
        _save_job_snapshot(job_id)
    finally:
        _clear_stop_flag(job_id)


def launch_demo_pipeline(job_id: str, pdf_path: Path, lecture_name: str, target_minutes: int) -> None:
    thread = threading.Thread(
        target=run_demo_pipeline,
        args=(job_id, pdf_path, lecture_name, target_minutes),
        daemon=True,
    )
    thread.start()


def update_script_and_rebuild(job_id: str, slide_number: int, script_text: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise FileNotFoundError(f"Job not found: {job_id}")

    job_paths = get_demo_job_paths(job_id)
    script_path = job_paths.scripts_dir / f"script_{slide_number:03d}.json"
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: slide {slide_number}")

    from lecture_auto.demo.ai import _trim_script_to_budget

    data = json.loads(script_path.read_text(encoding="utf-8"))
    previous_script = data.get("script", "")
    target_seconds = float(data.get("target_seconds") or 12)
    normalized_script = _trim_script_to_budget(script_text, target_seconds)
    data["script"] = normalized_script
    data["keywords"] = _extract_keywords(normalized_script)
    data["edited"] = True
    data["edited_at"] = datetime.now(UTC).isoformat()
    data["tts_text"] = re.sub(r"\s+", " ", normalized_script).strip() or f"{slide_number}번 슬라이드를 설명합니다."
    script_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = SlideManifest.model_validate_json(job_paths.manifest_path.read_text(encoding="utf-8"))
    note_path = job_paths.vlm_dir / f"vlm_note_{slide_number:03d}.json"
    note = json.loads(note_path.read_text(encoding="utf-8")) if note_path.exists() else {}
    slide = manifest.slides[slide_number - 1]
    upsert_slide(
        job_id,
        slide_number,
        {
            "script": data,
            "evidence": _evidence_payload(slide, note, data),
        },
    )
    append_event(job_id, "script", f"Slide {slide_number} script edited")
    scripts = []
    for path in sorted(job_paths.scripts_dir.glob("script_*.json")):
        scripts.append(json.loads(path.read_text(encoding="utf-8")))

    _clear_stop_flag(job_id)
    _render_media_stage(job_id, manifest, scripts)
    set_artifact(job_id, "package_url", f"/demo/api/jobs/{job_id}/package/download")
    update_stage(job_id, "package", status="done", progress=100, detail="Outputs refreshed after edit")
    _add_version_entry(
        job_id,
        kind="script_edit",
        slide_number=slide_number,
        summary=f"{slide_number}번 슬라이드 스크립트 수정",
        payload={"previous_script": previous_script, "new_script": normalized_script},
    )
    _save_job_snapshot(job_id)
    return data


def update_glossary(job_id: str, glossary: dict[str, str]) -> dict:
    normalized = {
        _normalize_line(key): _normalize_line(value)
        for key, value in glossary.items()
        if _normalize_line(key) and _normalize_line(value)
    }
    update_metadata(job_id, glossary=normalized)
    append_event(job_id, "tts", f"발음 사전 갱신: {len(normalized)}개 항목")
    _add_version_entry(job_id, kind="glossary_update", summary="발음 사전 업데이트", payload={"glossary": normalized})
    _save_job_snapshot(job_id)
    return normalized


def rerun_tts_only(job_id: str, slide_number: int | None = None) -> None:
    from lecture_auto.demo.synthesis import _synthesize_with_local_korean_fallback

    try:
        job_paths = get_demo_job_paths(job_id)
        manifest = SlideManifest.model_validate_json(job_paths.manifest_path.read_text(encoding="utf-8"))
        scripts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(job_paths.scripts_dir.glob("script_*.json"))]
        target_scripts = [item for item in scripts if slide_number is None or item["slide_number"] == slide_number]
        if not target_scripts:
            raise FileNotFoundError("No scripts available for TTS rerun.")

        voice_reference, _ = _resolve_voice_reference(job_id)
        glossary = (get_job(job_id) or {}).get("glossary") or {}
        fast_tts = _should_use_fast_tts(manifest)
        update_stage(job_id, "tts", status="running", progress=5, detail="선택한 음성 산출물 재생성 중")
        for index, script in enumerate(target_scripts, start=1):
            _check_stop(job_id, "tts")
            wav_path = job_paths.audio_dir / f"audio_{script['slide_number']:03d}.wav"
            tts_text = _apply_glossary(script["tts_text"], glossary)
            if fast_tts:
                _synthesize_with_local_korean_fallback(tts_text, wav_path)
            else:
                _synthesize_demo_tts(tts_text, wav_path, voice_reference)
            upsert_slide(job_id, script["slide_number"], {"audio_url": f"/demo/api/jobs/{job_id}/audio/{script['slide_number']}/wav", "tts_preview": tts_text})
            progress = int(index / max(1, len(target_scripts)) * 100)
            update_stage(job_id, "tts", status="running", progress=progress, detail=f"선택 음성 {index}/{len(target_scripts)} 재생성 완료")

        from lecture_auto.pipeline.tts import merge_audio
        merged_path = job_paths.audio_dir / "lecture_merged.wav"
        merge_audio(job_paths.audio_dir, merged_path)
        set_artifact(job_id, "merged_audio_url", f"/demo/api/jobs/{job_id}/audio/merged")
        update_stage(job_id, "tts", status="done", progress=100, detail="선택한 음성 산출물 재생성 완료")
        append_event(job_id, "tts", "TTS 부분 재실행 완료")
        _add_version_entry(job_id, kind="tts_rerun", slide_number=slide_number, summary="TTS 산출물 재실행 완료")
        _save_job_snapshot(job_id)
    except StopIteration as exc:
        mark_stopped(job_id, "tts", str(exc))
        _save_job_snapshot(job_id)
    except Exception as exc:
        mark_failed(job_id, "tts", str(exc))
        _save_job_snapshot(job_id)


def rerun_video_only(job_id: str) -> None:
    from lecture_auto.pipeline.video import assemble_video

    try:
        job_paths = get_demo_job_paths(job_id)
        png_paths = sorted(job_paths.rendered_dir.glob("slide_*.png"))
        wav_paths = sorted(job_paths.audio_dir.glob("audio_*.wav"))
        if not png_paths or not wav_paths:
            raise FileNotFoundError("Rendered slides or audio are missing for video rerun.")
        _check_stop(job_id, "video")
        update_stage(job_id, "video", status="running", progress=20, detail="기존 오디오로 영상만 다시 조립 중")
        output_video = job_paths.artifacts_dir / f"lecture_{job_id}.mp4"
        assemble_video(
            png_paths=png_paths,
            wav_paths=wav_paths,
            video_dir=job_paths.artifacts_dir / "video_clips",
            output_path=output_video,
            job_id=job_id,
        )
        set_artifact(job_id, "video_url", f"/demo/api/jobs/{job_id}/video")
        update_stage(job_id, "video", status="done", progress=100, detail="영상 재조립 완료")
        append_event(job_id, "video", "영상만 재조립 완료")
        _add_version_entry(job_id, kind="video_rerun", summary="최종 영상 재조립 완료")
        _refresh_library_artifacts(job_id)
        _save_job_snapshot(job_id)
    except StopIteration as exc:
        mark_stopped(job_id, "video", str(exc))
        _save_job_snapshot(job_id)
    except Exception as exc:
        mark_failed(job_id, "video", str(exc))
        _save_job_snapshot(job_id)


def rerun_scripts_and_media(job_id: str, target_minutes: int | None = None, settings_updates: dict | None = None) -> None:
    job = get_job(job_id)
    if job is None:
        raise FileNotFoundError(f"Job not found: {job_id}")

    job_paths = get_demo_job_paths(job_id)
    if not job_paths.manifest_path.exists():
        update_stage(job_id, "script", status="failed", detail="파싱 결과가 없습니다. 전체 파이프라인을 처음부터 실행해주세요.")
        append_event(job_id, "script", "재실행 실패: manifest.json 없음 (PDF 파싱 단계가 완료되지 않음)")
        update_metadata(job_id, status="failed")
        _clear_stop_flag(job_id)
        return
    manifest = SlideManifest.model_validate_json(job_paths.manifest_path.read_text(encoding="utf-8"))
    if target_minutes is not None:
        manifest = manifest.model_copy(update={"target_minutes": max(1, target_minutes)})
        job_paths.manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        update_metadata(job_id, target_minutes=max(1, target_minutes))
        append_event(job_id, "script", f"목표 강의 시간을 {max(1, target_minutes)}분으로 변경")
    if settings_updates:
        merged_settings = {**(job.get("settings") or {}), **settings_updates}
        merged_settings["target_minutes"] = manifest.target_minutes
        update_metadata(job_id, settings=merged_settings)
        append_event(job_id, "script", "강의 설정 패널 기준으로 설명 설정 반영")

    _clear_stop_flag(job_id)
    update_metadata(job_id, status="running")
    current_stage = "script"
    try:
        notes = _load_saved_notes(job_paths, manifest)
        update_stage(job_id, "script", status="running", progress=5, detail="저장된 VLM 결과를 기준으로 스크립트 재생성 중")
        scripts = _render_script_stage(job_id, manifest, notes)
        current_stage = "tts"
        _render_media_stage(job_id, manifest, scripts)
        set_artifact(job_id, "package_url", f"/demo/api/jobs/{job_id}/package/download")
        update_stage(job_id, "package", status="done", progress=100, detail="재생성된 산출물 반영 완료")
        _save_job_snapshot(job_id)
    except StopIteration as exc:
        mark_stopped(job_id, current_stage, str(exc))
        _save_job_snapshot(job_id)
    except Exception as exc:
        mark_failed(job_id, current_stage, str(exc))
        _save_job_snapshot(job_id)
    finally:
        _clear_stop_flag(job_id)


def launch_rerun(job_id: str, target_minutes: int | None = None, settings_updates: dict | None = None) -> None:
    thread = threading.Thread(
        target=rerun_scripts_and_media,
        args=(job_id, target_minutes, settings_updates),
        daemon=True,
    )
    thread.start()
