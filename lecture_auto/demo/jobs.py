from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from lecture_auto.demo.state import (
    append_event,
    append_version,
    create_job,
    get_job,
    update_metadata,
)
from lecture_auto.storage.jobs import JobPaths

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_ROOT = REPO_ROOT / "data" / "demo_jobs"
DEFAULT_SCRIPT_MODEL = "gpt-5.4-mini"
DEFAULT_GPT_VLM_MODEL = "gpt-5.4-mini"
DEFAULT_TTS_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
SCRIPT_BATCH_SIZE = 8
DEMO_FAST_TTS_SLIDE_LIMIT = 18
SCRIPT_PROMPT_VERSION = "demo-v3"
PIPELINE_SCHEMA_VERSION = "demo-saas-v1"


def _job_snapshot_path(job_id: str) -> Path:
    return get_demo_job_paths(job_id).job_dir / "job_state.json"


def _default_job_settings(
    *,
    target_minutes: int,
    audience: str = "학부 전공",
    explanation_style: str = "개념 중심",
    lecture_density: str = "표준형",
    learner_profile: str = "",
    delivery_notes: str = "",
    use_vlm: bool = True,
) -> dict:
    return {
        "target_minutes": max(1, target_minutes),
        "audience": audience or "학부 전공",
        "explanation_style": explanation_style or "개념 중심",
        "lecture_density": lecture_density or "표준형",
        "learner_profile": learner_profile.strip(),
        "delivery_notes": delivery_notes.strip(),
        "use_vlm": bool(use_vlm),
    }


def _base_pipeline_meta() -> dict:
    return {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "prompt_version": SCRIPT_PROMPT_VERSION,
        "llm_model": os.environ.get("DEMO_SCRIPT_MODEL", DEFAULT_SCRIPT_MODEL),
        "vlm_model": os.environ.get("DEMO_VLM_MODEL", "Qwen/Qwen3-VL-4B-Instruct"),
        "tts_model": os.environ.get("DEMO_QWEN_TTS_MODEL", DEFAULT_TTS_MODEL),
        "tts_mode": "clone",
        "seed_mode": "temperature_0.2",
    }


def _base_library(filename: str, lecture_name: str) -> dict:
    return {
        "folder": Path(filename).stem,
        "collection": "최근 강의",
        "display_name": lecture_name,
        "artifact_tree": [],
    }


def _save_job_snapshot(job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        return
    snapshot_path = _job_snapshot_path(job_id)
    snapshot_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_job_snapshot(job_id: str) -> dict | None:
    snapshot_path = _job_snapshot_path(job_id)
    if not snapshot_path.exists():
        return None
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def _refresh_library_artifacts(job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        return
    artifact_tree = []
    if job["filename"]:
        artifact_tree.append({"kind": "pdf", "label": job["filename"]})
    artifact_tree.extend(
        [
            {"kind": "rendered", "label": "rendered/ slide previews"},
            {"kind": "script", "label": "scripts/ slide scripts"},
            {"kind": "audio", "label": "audio/ per-slide wav"},
            {"kind": "video", "label": "artifacts/ lecture mp4"},
        ]
    )
    library = job.get("library") or _base_library(job["filename"], job["lecture_name"])
    library["artifact_tree"] = artifact_tree
    update_metadata(job_id, library=library)
    _save_job_snapshot(job_id)


def _add_version_entry(job_id: str, *, kind: str, summary: str, slide_number: int | None = None, payload: dict | None = None) -> None:
    append_version(
        job_id,
        {
            "version_id": uuid.uuid4().hex[:8],
            "time": datetime.now(UTC).isoformat(),
            "kind": kind,
            "slide_number": slide_number,
            "summary": summary,
            "payload": payload or {},
        },
    )
    _save_job_snapshot(job_id)


def create_demo_job(filename: str, lecture_name: str, target_minutes: int, *, settings: dict | None = None) -> dict:
    job_id = uuid.uuid4().hex[:10]
    merged_settings = _default_job_settings(target_minutes=target_minutes, **(settings or {}))
    job = create_job(
        job_id,
        filename,
        lecture_name,
        target_minutes,
        settings=merged_settings,
        glossary={},
        version_history=[],
        pipeline_meta=_base_pipeline_meta(),
        library=_base_library(filename, lecture_name),
    )
    _save_job_snapshot(job_id)
    return job


def get_demo_job_paths(job_id: str) -> JobPaths:
    return JobPaths(job_id, root=DEMO_ROOT).ensure_dirs()


def save_uploaded_pdf(job_id: str, filename: str, content: bytes) -> Path:
    job_paths = get_demo_job_paths(job_id)
    safe_name = Path(filename).name or "lecture.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{Path(safe_name).stem}.pdf"
    target = job_paths.input_dir / safe_name
    target.write_bytes(content)
    return target


def save_voice_reference(job_id: str, filename: str, content: bytes) -> Path:
    job_paths = get_demo_job_paths(job_id)
    ext = Path(filename).suffix.lower() or ".webm"
    source_path = job_paths.input_dir / f"voice_reference{ext}"
    source_path.write_bytes(content)

    wav_path = job_paths.input_dir / "voice_reference.wav"
    if ext != ".wav":
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-ar",
                "24000",
                "-ac",
                "1",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            wav_path = source_path
    else:
        wav_path = source_path

    update_metadata(job_id, voice_reference_name=Path(filename).name)
    append_event(job_id, "tts", f"Voice reference saved: {Path(filename).name}")
    _save_job_snapshot(job_id)
    return wav_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _get_default_voice_reference_path() -> Path | None:
    shared_dir = DEMO_ROOT / "_shared"
    shared_dir.mkdir(parents=True, exist_ok=True)

    for candidate in (
        REPO_ROOT / "박유진음성.wav",
        REPO_ROOT / "박유진음성.m4a",
    ):
        if not candidate.exists():
            continue
        if candidate.suffix.lower() == ".wav":
            return candidate

        wav_path = shared_dir / "park_yujin_default.wav"
        if wav_path.exists() and wav_path.stat().st_mtime >= candidate.stat().st_mtime:
            return wav_path
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(candidate),
                "-ar",
                "24000",
                "-ac",
                "1",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and wav_path.exists():
            return wav_path
    return None


def _resolve_voice_reference(job_id: str) -> tuple[Path | None, str | None]:
    job_paths = get_demo_job_paths(job_id)
    job = get_job(job_id) or {}
    for candidate in (
        job_paths.input_dir / "voice_reference.wav",
        job_paths.input_dir / "voice_reference.webm",
    ):
        if candidate.exists():
            return candidate, Path(job.get("voice_reference_name") or candidate.name).name

    default_ref = _get_default_voice_reference_path()
    if default_ref is not None:
        return default_ref, "박유진음성.m4a (기본)"
    return None, None


def restore_job_from_disk(job_id: str) -> dict | None:
    import logging

    from lecture_auto.demo.state import upsert_slide, update_stage, set_artifact
    from lecture_auto.schemas.manifest import SlideManifest

    logger = logging.getLogger(__name__)

    existing = get_job(job_id)
    if existing is not None:
        return existing

    job_paths = get_demo_job_paths(job_id)
    if not job_paths.job_dir.exists():
        return None

    try:
        snapshot = _load_job_snapshot(job_id)

        input_files = sorted(job_paths.input_dir.glob("*.pdf"))
        filename = input_files[0].name if input_files else f"{job_id}.pdf"
        lecture_name = Path(filename).stem
        target_minutes = 8
        manifest: SlideManifest | None = None
        if job_paths.manifest_path.exists():
            manifest = SlideManifest.model_validate_json(job_paths.manifest_path.read_text(encoding="utf-8"))
            lecture_name = manifest.lecture_name
            target_minutes = manifest.target_minutes

        job = create_job(
            job_id,
            filename,
            lecture_name,
            target_minutes,
            settings=(snapshot or {}).get("settings"),
            glossary=(snapshot or {}).get("glossary"),
            version_history=(snapshot or {}).get("version_history"),
            pipeline_meta=(snapshot or {}).get("pipeline_meta"),
            library=(snapshot or {}).get("library"),
            recovery=(snapshot or {}).get("recovery"),
        )
        append_event(job_id, "package", "디스크에서 기존 작업 메타데이터 복구")

        if job_paths.manifest_path.exists():
            update_stage(job_id, "parse", status="done", progress=100, detail="파싱 결과 복구 완료")
        if list(job_paths.rendered_dir.glob("slide_*.png")):
            update_stage(job_id, "render", status="done", progress=100, detail="슬라이드 미리보기 복구 완료")

        slide_count = manifest.slide_count if manifest else 0
        if slide_count and manifest:
            from lecture_auto.demo.ai import _extract_title, _evidence_payload
            from lecture_auto.demo.synthesis import _load_saved_notes

            notes = _load_saved_notes(job_paths, manifest)
            scripts = []
            for idx, slide in enumerate(manifest.slides, start=1):
                slide_payload: dict = {
                    "title": _extract_title(slide),
                    "png_url": f"/demo/api/jobs/{job_id}/slides/{slide.slide_number}/png",
                }
                note = notes[idx - 1]
                if note:
                    slide_payload["vlm_note"] = note
                script_path = job_paths.scripts_dir / f"script_{slide.slide_number:03d}.json"
                if script_path.exists():
                    try:
                        script = json.loads(script_path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError, KeyError) as e:
                        logger.warning("Failed to restore job %s from disk: %s", job_id, e)
                        script = None
                    if script is not None:
                        scripts.append(script)
                        slide_payload["script"] = script
                        slide_payload["evidence"] = _evidence_payload(slide, note, script)
                    else:
                        slide_payload["evidence"] = _evidence_payload(slide, note, None)
                else:
                    slide_payload["evidence"] = _evidence_payload(slide, note, None)
                wav_path = job_paths.audio_dir / f"audio_{slide.slide_number:03d}.wav"
                if wav_path.exists():
                    slide_payload["audio_url"] = f"/demo/api/jobs/{job_id}/audio/{slide.slide_number}/wav"
                upsert_slide(job_id, slide.slide_number, slide_payload)

            if any(notes):
                update_stage(job_id, "vlm", status="done", progress=100, detail="VLM 분석 결과 복구 완료")
            if scripts:
                update_stage(job_id, "script", status="done", progress=100, detail="스크립트 복구 완료")
            if list(job_paths.audio_dir.glob("audio_*.wav")):
                update_stage(job_id, "tts", status="done", progress=100, detail="생성된 음성 복구 완료")
                set_artifact(job_id, "merged_audio_url", f"/demo/api/jobs/{job_id}/audio/merged")
            if list(job_paths.artifacts_dir.glob("lecture_*.mp4")):
                update_stage(job_id, "video", status="done", progress=100, detail="강의 영상 복구 완료")
                update_stage(job_id, "package", status="done", progress=100, detail="다운로드 산출물 복구 완료")
                set_artifact(job_id, "video_url", f"/demo/api/jobs/{job_id}/video")
                set_artifact(job_id, "package_url", f"/demo/api/jobs/{job_id}/package/download")

        _, voice_label = _resolve_voice_reference(job_id)
        if voice_label:
            update_metadata(job_id, voice_reference_name=voice_label)

        _refresh_library_artifacts(job_id)
        _save_job_snapshot(job_id)
        return get_job(job_id)
    except (json.JSONDecodeError, OSError, KeyError) as e:
        logger.warning("Failed to restore job %s from disk: %s", job_id, e)
        return None


def restore_all_jobs_from_disk() -> list[dict]:
    DEMO_ROOT.mkdir(parents=True, exist_ok=True)
    restored: list[dict] = []
    for path in sorted(DEMO_ROOT.iterdir()):
        if not path.is_dir() or path.name.startswith("_"):
            continue
        has_manifest = (path / "parsed" / "manifest.json").exists()
        has_snapshot = (path / "job_state.json").exists()
        has_pdf = any((path / "input").glob("*.pdf"))
        if not has_manifest and not has_pdf and not has_snapshot:
            continue
        job = restore_job_from_disk(path.name)
        if job:
            restored.append(job)
    return restored
