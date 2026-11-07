from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from lecture_auto.production.intent import load_intent, save_intent
from lecture_auto.schemas.intent import IntentSheet
from lecture_auto.web import store
from lecture_auto.web.runner import JobRunner
from lecture_auto.web.settings import Settings


def intent_router(settings: Settings, runner: JobRunner) -> APIRouter:
    router = APIRouter()

    @router.get("/api/lectures/{lid}/intent")
    def get_intent(lid: str) -> IntentSheet:
        store.get_lecture(settings, lid)
        sheet = load_intent(settings.work_dir / lid)
        if sheet is None:
            raise HTTPException(404, "의도 시트가 없습니다. 초안을 먼저 만들어 주세요")
        return sheet

    @router.put("/api/lectures/{lid}/intent")
    def put_intent(lid: str, body: IntentSheet, request: Request) -> IntentSheet:
        item = store.get_lecture(settings, lid)
        with request.app.state.edit_lock:
            if runner.busy(lid):
                raise HTTPException(409, "이 강의는 작업 중입니다")
            work = settings.work_dir / lid
            current = load_intent(work)
            if current is None:
                raise HTTPException(404, "초안을 먼저 만들어 주세요")
            numbers = {s["number"] for s in store.slide_views(settings, item)}
            if body.lecture_id != lid or {s.slide for s in body.slides} != numbers:
                raise HTTPException(422, "현재 강의의 모든 슬라이드를 한 번씩 포함해야 합니다")
            sheet = current.model_copy(update={
                "slides": sorted(body.slides, key=lambda s: s.slide), "edited": True,
            })
            save_intent(work, sheet)
            return sheet

    return router
