from __future__ import annotations

import contextlib

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lecture_auto.pipeline import approval as approvals
from lecture_auto.pipeline.approval import load_approvals
from lecture_auto.production import batch as bgl
from lecture_auto.web import store
from lecture_auto.web.runner import JobRunner
from lecture_auto.web.settings import Settings

AUDIO_KINDS = {"main": "slide_{:03d}.wav", "cand": "slide_{:03d}.cand.wav", "prev": "slide_{:03d}.prev.wav"}


class ScriptBody(BaseModel):
    script: str = Field(min_length=1, max_length=20000)


class PromoteBody(BaseModel):
    allow_failed: bool = False
    note: str = Field(default="", max_length=500)


def review_router(settings: Settings, runner: JobRunner) -> APIRouter:
    router = APIRouter()

    @contextlib.contextmanager
    def idle(request: Request, lid: str):
        with request.app.state.edit_lock:
            if runner.busy(lid):
                raise HTTPException(409, "이 강의는 작업 중입니다")
            yield

    def review(lid, change):
        try:
            change(settings.work_dir / lid)
        except (ValueError, OSError) as error:
            raise HTTPException(400, f"명령 실패: {error}") from None

    def view(item, number):
        return next(v for v in store.slide_views(settings, item) if v["number"] == number)

    @router.put("/api/lectures/{lid}/slides/{number}/script")
    def put_script(lid: str, number: int, body: ScriptBody, request: Request):
        item = store.get_lecture(settings, lid)
        with idle(request, lid):
            try:
                store.save_script(settings, item, number, body.script.strip())
            except FileNotFoundError:
                raise HTTPException(404, "대본이 아직 없습니다") from None
            return view(item, number)

    @router.post("/api/lectures/{lid}/slides/{number}/approve")
    def approve(lid: str, number: int, request: Request):
        item = store.get_lecture(settings, lid)
        with idle(request, lid):
            if not (settings.work_dir / lid / "audio" / f"slide_{number:03d}.wav").exists():
                raise HTTPException(404, "음성이 없습니다")
            rooted = {**item, "ref_voice": store.ref_voice_path(settings, item)}
            review(lid, lambda _w: bgl._cli_approve(
                rooted, settings.work_dir, str(number), store.pronunciation_entries(settings)))
            return view(item, number)

    @router.post("/api/lectures/{lid}/slides/{number}/promote")
    def promote(lid: str, number: int, body: PromoteBody, request: Request):
        item = store.get_lecture(settings, lid)
        with idle(request, lid):
            if not (settings.work_dir / lid / "audio" / f"slide_{number:03d}.cand.wav.json").exists():
                raise HTTPException(404, "후보 음성이 없습니다")
            review(lid, lambda _w: bgl._cli_promote(
                item, settings.work_dir, str(number), body.allow_failed, body.note or "웹에서 후보 채택"))
            return view(item, number)

    @router.post("/api/lectures/{lid}/slides/{number}/unapprove")
    def unapprove(lid: str, number: int, request: Request):
        item = store.get_lecture(settings, lid)
        with idle(request, lid):
            if number not in load_approvals(settings.work_dir / lid, lid).slides:
                raise HTTPException(404, "승인된 슬라이드가 아닙니다")
            review(lid, lambda w: approvals.save_approvals(
                w, approvals.unapprove(approvals.load_approvals(w, lid), number)))
            return view(item, number)

    @router.post("/api/lectures/{lid}/slides/{number}/restore-prev")
    def restore_prev(lid: str, number: int, request: Request):
        item = store.get_lecture(settings, lid)
        with idle(request, lid):
            if not (settings.work_dir / lid / "audio" / f"slide_{number:03d}.prev.wav").exists():
                raise HTTPException(404, "되돌릴 이전 음성이 없습니다")
            review(lid, lambda w: approvals.save_approvals(
                w, approvals.restore_previous(approvals.load_approvals(w, lid), w / "audio", number)))
            return view(item, number)

    @router.get("/api/lectures/{lid}/slides/{number}/image")
    def image(lid: str, number: int):
        path = settings.work_dir / lid / "rendered" / f"slide_{number:03d}.png"
        if not path.exists():
            raise HTTPException(404, "이미지가 없습니다")
        return FileResponse(path, media_type="image/png")

    @router.get("/api/lectures/{lid}/slides/{number}/audio/{kind}")
    def audio(lid: str, number: int, kind: str):
        if kind not in AUDIO_KINDS:
            raise HTTPException(400, "잘못된 음성 종류")
        path = settings.work_dir / lid / "audio" / AUDIO_KINDS[kind].format(number)
        if not path.exists():
            raise HTTPException(404, "음성이 없습니다")
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @router.get("/api/lectures/{lid}/files/{name}")
    def output(lid: str, name: str):
        if name not in {f["name"] for f in store.output_files(settings, lid)}:
            raise HTTPException(404, "파일이 없습니다")
        return FileResponse(settings.output_dir / lid / name, filename=name)

    return router
