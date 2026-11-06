from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException

from lecture_auto.core.jobs import JobSpec
from lecture_auto.web.accounts import Accounts
from lecture_auto.web.settings import Settings

KINDS = {
    "scripts": "대본 생성", "produce": "음성·영상 제작", "regen": "슬라이드 다시 만들기",
    "heal": "보류 슬라이드 자동 복구", "assemble": "영상 다시 조립", "check": "발음 점검",
    "study": "용어·퀴즈 초안",
}
GPU_KINDS = {"produce", "regen", "heal"}


class JobError(ValueError):
    pass


def job_env(settings: Settings, item: dict) -> dict[str, str]:
    from lecture_auto.web.voices import validate_ref

    env = {**os.environ, **settings.extra_env}
    env.update({
        "PYTHONPATH": str(settings.code_root), "PYTHONUNBUFFERED": "1",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUDA_VISIBLE_DEVICES": settings.gpu,
        "LECTURE_AUTO_PROJECTS": str(settings.projects_dir),
    })
    accounts = Accounts(settings)
    if accounts.resource_disabled("lecture", item["id"]):
        raise JobError("비활성화된 강의는 제작할 수 없습니다")
    uid = item.get("owner")
    if uid:
        user = accounts.get(uid)
        if user is None or user.disabled:
            raise JobError("사용할 수 없는 계정입니다")
        key = accounts.api_key(uid)
        if key:
            env.update(BAZE_API_KEY=key, FACTCHAT_API_KEY=key,
                       FACTCHAT_BASE_URL="https://factchat-cloud.mindlogic.ai/v1/gateway")
        elif user.role != "admin":
            raise JobError("설정에서 본인의 BAZE API 키를 등록한 뒤 제작해 주세요")
    if item.get("tts_engine", "raon") == "raon" and item.get("ref_voice"):
        try:
            validate_ref(settings, accounts, uid, Path(item["ref_voice"]))
        except HTTPException as error:
            raise JobError(str(error.detail)) from None
    return env


def job_spec(settings: Settings, kind: str, lecture_id: str, slides: list[int] | None = None) -> JobSpec:
    if kind not in KINDS:
        raise JobError(f"알 수 없는 작업 종류: {kind}")
    if kind == "regen" and (not slides or any(not isinstance(n, int) or n < 1 for n in slides)):
        raise JobError("다시 만들 슬라이드 번호를 지정하세요")
    workers = 1 if kind == "produce" and settings.gpu != "0" else None
    return JobSpec(kind=kind, project_id=lecture_id, slides=slides or None, workers_per_gpu=workers)


def _proc_identity(pid: int | None) -> str | None:
    if not pid:
        return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None
    return f"{boot_id}:{stat.rsplit(')', 1)[1].split()[19]}"


def _pid_alive(pid: int | None, identity: str | None = None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return identity is None or _proc_identity(pid) == identity


def job_outcome(settings: Settings, lecture_id: str) -> dict | None:
    from lecture_auto.web.store import get_lecture, lecture_summary

    try:
        summary = lecture_summary(settings, get_lecture(settings, lecture_id))
    except Exception as error:  # noqa: BLE001 - a snapshot cannot leave the queue running forever
        return {"error": repr(error)}
    return {
        "video_state": summary["video_state"], "held_back": len(summary["held_back"]),
        "no_audio": len(summary["no_audio"]), "scripts": summary["scripts"],
        "audio": summary["audio"], "candidates": summary["candidates"],
    }
