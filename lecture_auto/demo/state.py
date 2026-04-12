from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime


_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _base_stages() -> list[dict]:
    return [
        {"key": "upload", "label": "PDF 업로드", "status": "done", "progress": 100},
        {"key": "parse", "label": "문서 구조 분석", "status": "pending", "progress": 0},
        {"key": "render", "label": "슬라이드 렌더링", "status": "pending", "progress": 0},
        {"key": "vlm", "label": "GPT 시각 분석", "status": "pending", "progress": 0},
        {"key": "script", "label": "GPT 스크립트 생성", "status": "pending", "progress": 0},
        {"key": "tts", "label": "음성 합성", "status": "pending", "progress": 0},
        {"key": "video", "label": "강의 영상 조립", "status": "pending", "progress": 0},
        {"key": "package", "label": "다운로드 패키지", "status": "pending", "progress": 0},
    ]


def _default_settings(target_minutes: int) -> dict:
    return {
        "target_minutes": target_minutes,
        "audience": "학부 전공",
        "explanation_style": "개념 중심",
        "lecture_density": "표준형",
        "learner_profile": "",
        "delivery_notes": "",
        "use_vlm": True,
    }


def _default_recovery() -> dict:
    return {
        "can_resume_from": "upload",
        "available_actions": [
            {"key": "rerun_all", "label": "전체 재실행"},
            {"key": "rerun_tts", "label": "TTS만 재실행"},
            {"key": "rerun_video", "label": "영상만 재조립"},
        ],
    }


@dataclass
class DemoJob:
    job_id: str
    filename: str
    lecture_name: str
    target_minutes: int
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    status: str = "queued"
    current_stage: str = "upload"
    error: str | None = None
    voice_reference_name: str | None = None
    stages: list[dict] = field(default_factory=_base_stages)
    events: list[dict] = field(default_factory=list)
    slides: dict[int, dict] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    settings: dict = field(default_factory=lambda: _default_settings(8))
    glossary: dict[str, str] = field(default_factory=dict)
    version_history: list[dict] = field(default_factory=list)
    pipeline_meta: dict = field(default_factory=dict)
    library: dict = field(default_factory=dict)
    recovery: dict = field(default_factory=_default_recovery)

    def to_dict(self) -> dict:
        payload = copy.deepcopy(self.__dict__)
        payload["slides"] = [self.slides[key] for key in sorted(self.slides)]
        return payload

    def to_summary(self) -> dict:
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "lecture_name": self.lecture_name,
            "target_minutes": self.target_minutes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "current_stage": self.current_stage,
            "error": self.error,
            "voice_reference_name": self.voice_reference_name,
            "settings": copy.deepcopy(self.settings),
            "pipeline_meta": copy.deepcopy(self.pipeline_meta),
            "library": copy.deepcopy(self.library),
            "recovery": copy.deepcopy(self.recovery),
        }


_JOBS: dict[str, DemoJob] = {}


def create_job(
    job_id: str,
    filename: str,
    lecture_name: str,
    target_minutes: int,
    *,
    settings: dict | None = None,
    glossary: dict | None = None,
    version_history: list[dict] | None = None,
    pipeline_meta: dict | None = None,
    library: dict | None = None,
    recovery: dict | None = None,
) -> dict:
    with _LOCK:
        merged_settings = _default_settings(target_minutes)
        if settings:
            merged_settings.update(settings)
        merged_settings["target_minutes"] = target_minutes
        job = DemoJob(
            job_id=job_id,
            filename=filename,
            lecture_name=lecture_name,
            target_minutes=target_minutes,
            settings=merged_settings,
            glossary=copy.deepcopy(glossary or {}),
            version_history=copy.deepcopy(version_history or []),
            pipeline_meta=copy.deepcopy(pipeline_meta or {}),
            library=copy.deepcopy(library or {}),
            recovery=copy.deepcopy(recovery or _default_recovery()),
        )
        job.events.append(
            {
                "time": _now(),
                "stage": "upload",
                "message": f"Uploaded {filename}",
            }
        )
        _JOBS[job_id] = job
        return job.to_dict()


def get_job(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return job.to_dict() if job else None


def list_jobs() -> list[dict]:
    with _LOCK:
        jobs = [job.to_dict() for job in _JOBS.values()]
    jobs.sort(key=lambda job: job["updated_at"], reverse=True)
    return jobs


def list_job_summaries() -> list[dict]:
    with _LOCK:
        jobs = [job.to_summary() for job in _JOBS.values()]
    jobs.sort(key=lambda job: job["updated_at"], reverse=True)
    return jobs


def _find_stage(job: DemoJob, stage_key: str) -> dict:
    for stage in job.stages:
        if stage["key"] == stage_key:
            return stage
    raise KeyError(stage_key)


def update_stage(
    job_id: str,
    stage_key: str,
    *,
    status: str,
    progress: int | None = None,
    detail: str | None = None,
) -> None:
    with _LOCK:
        job = _JOBS[job_id]
        stage = _find_stage(job, stage_key)
        stage["status"] = status
        if progress is not None:
            stage["progress"] = progress
        if detail is not None:
            stage["detail"] = detail
        job.current_stage = stage_key
        job.recovery["can_resume_from"] = stage_key
        job.updated_at = _now()
        if status == "running":
            # Only transition to running if not already being stopped
            if job.status not in ("stopping", "stopped"):
                job.status = "running"
        elif stage_key == "package" and status == "done":
            job.status = "completed"


def append_event(job_id: str, stage_key: str, message: str) -> None:
    with _LOCK:
        job = _JOBS[job_id]
        job.events.append({"time": _now(), "stage": stage_key, "message": message})
        job.updated_at = _now()


def upsert_slide(job_id: str, slide_number: int, data: dict) -> None:
    with _LOCK:
        job = _JOBS[job_id]
        existing = job.slides.get(slide_number, {"tts_status": "pending"})
        job.slides[slide_number] = {**existing, **copy.deepcopy(data), "slide_number": slide_number}
        job.updated_at = _now()


def set_artifact(job_id: str, key: str, value: str) -> None:
    with _LOCK:
        job = _JOBS[job_id]
        job.artifacts[key] = value
        job.updated_at = _now()


def append_version(job_id: str, entry: dict) -> None:
    with _LOCK:
        job = _JOBS[job_id]
        job.version_history.append(copy.deepcopy(entry))
        job.updated_at = _now()


def update_metadata(job_id: str, **values: object) -> None:
    with _LOCK:
        job = _JOBS[job_id]
        for key, value in values.items():
            if hasattr(job, key):
                setattr(job, key, copy.deepcopy(value))
        job.updated_at = _now()


def mark_failed(job_id: str, stage_key: str, error: str) -> None:
    with _LOCK:
        job = _JOBS[job_id]
        job.status = "failed"
        job.current_stage = stage_key
        job.error = error
        job.recovery["can_resume_from"] = stage_key
        job.updated_at = _now()
        stage = _find_stage(job, stage_key)
        stage["status"] = "failed"
        stage["detail"] = error
        job.events.append({"time": _now(), "stage": stage_key, "message": error})


def mark_stopped(job_id: str, stage_key: str, message: str) -> None:
    """Mark a job as user-stopped (distinct from error-failed)."""
    with _LOCK:
        job = _JOBS[job_id]
        job.status = "stopped"
        job.current_stage = stage_key
        job.error = None
        job.recovery["can_resume_from"] = stage_key
        job.updated_at = _now()
        stage = _find_stage(job, stage_key)
        stage["status"] = "stopped"
        stage["detail"] = message
        job.events.append({"time": _now(), "stage": stage_key, "message": message})
