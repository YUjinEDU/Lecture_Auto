from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ValidationError

from lecture_auto.core.project import (
    ProjectConfig,
    delete_project,
    new_lecture_id,
    save_project,
)
from lecture_auto.web import store
from lecture_auto.web.access import can_access, current_user
from lecture_auto.web.accounts import Accounts
from lecture_auto.web.lecture_settings import (
    GEMINI_VOICES,
    LectureSettings,
    resolved_settings,
)
from lecture_auto.web.quotas import check_storage
from lecture_auto.web.runner import KINDS, JobError, JobRunner
from lecture_auto.web.settings import Settings

UPLOAD_MAGIC = {".pptx": b"PK\x03\x04", ".pdf": b"%PDF"}


class JobBody(BaseModel):
    kind: str
    slides: list[int] | None = None


def lecture_router(settings: Settings, runner: JobRunner, accounts: Accounts) -> APIRouter:
    router = APIRouter()

    def available(request, item):
        user = current_user(request)
        return can_access(user, item) and (user.role == "admin" or
                                           not accounts.resource_disabled("lecture", item["id"]))

    def summary(item):
        return {**store.lecture_summary(settings, item),
                "owner": item.get("owner"), "tts_engine": item.get("tts_engine", "raon"),
                "tts_voice": item.get("tts_voice"), "tts_instructions": item.get("tts_instructions"),
                "ref_voice": str(item.get("ref_voice") or "")}

    @router.get("/api/lectures")
    def lectures(request: Request):
        return [{**summary(item), "job": runner.busy(item["id"])}
                for item in store.all_lectures(settings) if available(request, item)]

    @router.get("/api/tts-options")
    def options():
        return {"gemini_voices": sorted(GEMINI_VOICES), "raon_enabled": settings.raon_enabled}

    @router.post("/api/lectures")
    async def create(request: Request, file: Annotated[UploadFile, File()],
                     name: Annotated[str, Form(min_length=1, max_length=100)],
                     subject: Annotated[str, Form(max_length=100)] = "",
                     target_minutes: Annotated[float, Form(gt=0, le=120)] = 30,
                     min_minutes: Annotated[float | None, Form(gt=0, le=120)] = None,
                     tts_engine: Annotated[str | None, Form()] = None,
                     tts_voice: Annotated[str | None, Form()] = None,
                     tts_instructions: Annotated[str | None, Form()] = None,
                     ref_voice: Annotated[str | None, Form()] = None):
        user = current_user(request)
        tts_engine = tts_engine or ("raon" if settings.raon_enabled else "gemini")
        if tts_engine == "gemini" and not tts_voice:
            tts_voice = "Charon"
        try:
            selection = LectureSettings(tts_engine=tts_engine, tts_voice=tts_voice,
                                        tts_instructions=tts_instructions, ref_voice=ref_voice)
        except ValidationError:
            raise HTTPException(400, "음성 엔진과 음성 설정을 확인해 주세요") from None
        selection = resolved_settings(settings, accounts, user.id, selection)
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in UPLOAD_MAGIC:
            raise HTTPException(400, "PPTX 또는 PDF 파일만 올릴 수 있습니다")
        data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, "파일 크기 한도를 초과했습니다")
        if not data.startswith(UPLOAD_MAGIC[suffix]):
            raise HTTPException(400, "파일 내용이 PPTX/PDF 형식이 아닙니다")
        with request.app.state.storage_lock:
            items = store.all_lectures(settings)
            limit = accounts.effective_limits(user.id)["max_lectures"]
            if limit is not None and sum(item.get("owner") == user.id for item in items) >= limit:
                raise HTTPException(409, "등록할 수 있는 강의 개수를 초과했습니다")
            check_storage(settings, user.id, len(data))
            existing = [i["id"] for i in items]
            for folder in (settings.work_dir, settings.output_dir, settings.uploads_dir):
                if folder.is_dir():
                    existing.extend(p.name for p in folder.iterdir())
            lid = new_lecture_id(name, existing)
            rel = Path("data/web/uploads") / lid / f"{lid}{suffix}"
            dest = settings.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            project = ProjectConfig(
                id=lid, name=name.strip(), subject=subject.strip() or "강의",
                **{suffix.lstrip("."): rel}, target_minutes=target_minutes, min_minutes=min_minutes,
                **selection.model_dump(), voice_match=True, master_audio=True, web=True,
                owner=user.id, created_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
            save_project(project, settings.projects_dir)
            with accounts.connect() as db:
                db.execute("INSERT INTO upload_owners VALUES (?,?)", (lid, user.id))
        return summary(project.as_item())

    @router.get("/api/lectures/{lid}")
    def lecture(lid: str):
        item = store.get_lecture(settings, lid)
        return {**summary(item), "job": runner.busy(lid), "slide_list": store.slide_views(settings, item)}

    @router.put("/api/lectures/{lid}/settings")
    def edit(lid: str, body: LectureSettings, request: Request):
        with request.app.state.edit_lock:
            if runner.busy(lid):
                raise HTTPException(409, "이 강의는 작업 중입니다")
            item = store.get_lecture(settings, lid)
            selection = resolved_settings(settings, accounts, item.get("owner"), body)
            project = ProjectConfig.model_validate({**item, **selection.model_dump()})
            save_project(project, settings.projects_dir)
        return summary(project.as_item())

    @router.delete("/api/lectures/{lid}")
    def delete(lid: str, request: Request):
        item = store.get_lecture(settings, lid)
        if not item.get("web"):
            raise HTTPException(400, "기본 등록 강의는 웹에서 삭제할 수 없습니다")
        with request.app.state.edit_lock, request.app.state.storage_lock:
            if runner.busy(lid):
                raise HTTPException(409, "이 강의는 작업 중입니다")
            delete_project(lid, settings.projects_dir)
        return {"ok": True}

    @router.get("/api/jobs")
    def jobs(request: Request):
        if current_user(request).role == "admin":
            return runner.list()[:100]
        permitted = {i["id"] for i in store.all_lectures(settings) if available(request, i)}
        return [j for j in runner.list() if j.get("owner") == current_user(request).id
                or j["lecture_id"] in permitted][:100]

    @router.post("/api/lectures/{lid}/jobs")
    def submit(lid: str, body: JobBody, request: Request):
        if body.kind not in KINDS:
            raise HTTPException(400, "알 수 없는 작업 종류")
        try:
            with request.app.state.edit_lock:
                return runner.submit(body.kind, store.get_lecture(settings, lid), body.slides)
        except JobError as error:
            raise HTTPException(409 if "이미" in str(error) else 400, str(error)) from None

    @router.get("/api/jobs/{jid}")
    def job(jid: str):
        return runner.get(jid)

    @router.get("/api/jobs/{jid}/log")
    def log(jid: str, offset: int = 0):
        text, nxt = runner.read_log(jid, offset)
        return {"text": text, "offset": nxt}

    @router.post("/api/jobs/{jid}/cancel")
    def cancel(jid: str):
        try:
            return runner.cancel(jid)
        except JobError as error:
            raise HTTPException(409, str(error)) from None

    return router
