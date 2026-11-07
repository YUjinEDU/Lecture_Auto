"""Routes a student reaches through a share link: no login, read-only, one lecture per token."""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from lecture_auto.pipeline.pronunciation import load_pronunciation_entries
from lecture_auto.production.study import load_study
from lecture_auto.production.viewer import load_timeline, viewer_path, write_viewer
from lecture_auto.web.settings import Settings
from lecture_auto.web.shares import resolve_share

STATIC = Path(__file__).parent / "static"
REPORTS_PER_LINK = 10
REPORT_WINDOW_SECONDS = 3600


class ReportBody(BaseModel):
    kind: str = Field(pattern="^(voice|content|other)$")
    text: str = Field(default="", max_length=2000)
    at_seconds: float | None = None


def cached_viewer(settings: Settings, lecture_id: str) -> dict:
    """Cached ``viewer.json``, rebuilt whenever the lecture was re-assembled after it was written."""
    out = settings.output_dir / lecture_id
    path = viewer_path(settings.output_dir, lecture_id)
    timelines = [p for p in out.glob("*.timeline.json")] if out.is_dir() else []
    if not timelines:
        raise HTTPException(404, "아직 영상이 없는 강의입니다")
    newest = max(p.stat().st_mtime for p in timelines)
    if not path.exists() or path.stat().st_mtime < newest:
        entries = load_pronunciation_entries(settings.root / "config" / "pronunciation.yaml")
        write_viewer(lecture_id, settings.work_dir, settings.output_dir, entries)
    return json.loads(path.read_text(encoding="utf-8"))


def make_public_router(
    settings: Settings,
    get_item: Callable[[str], dict | None],
    on_report: Callable[[str, str, ReportBody], None],
) -> APIRouter:
    """``get_item(lecture_id)`` returns the lecture dict or None (deleted or disabled lectures
    must return None so their links stop working); ``on_report(lecture_id, token, body)`` stores a report."""
    router = APIRouter()
    db = settings.web_dir / "app.db"
    reports_by_token: dict[str, deque[float]] = defaultdict(deque)
    report_lock = threading.Lock()

    def lecture_for(token: str) -> dict:
        lecture_id = resolve_share(db, token)
        item = get_item(lecture_id) if lecture_id else None
        if item is None:
            raise HTTPException(404, "링크가 없거나 공유가 중지된 강의입니다")
        return item

    @router.get("/w/{token}", response_class=HTMLResponse)
    def watch_page(token: str):
        lecture_for(token)
        return HTMLResponse((STATIC / "watch.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})

    @router.get("/api/public/{token}")
    def lecture(token: str):
        item = lecture_for(token)
        return {
            "title": item.get("name", item["id"]),
            "subject": item.get("subject", ""),
            "viewer": cached_viewer(settings, item["id"]),
            "study": load_study(settings.work_dir, item["id"]).public(),
        }

    @router.get("/api/public/{token}/video")
    def video(token: str):
        item = lecture_for(token)
        timeline, _stem = load_timeline(settings.output_dir / item["id"], item["id"])
        path = settings.output_dir / item["id"] / timeline.mp4
        if not path.is_file():
            raise HTTPException(404, "영상 파일이 없습니다")
        return FileResponse(path, media_type="video/mp4")

    @router.post("/api/public/{token}/report")
    def report(token: str, body: ReportBody):
        item = lecture_for(token)
        now = time.monotonic()
        with report_lock:
            recent = reports_by_token[token]
            while recent and now - recent[0] > REPORT_WINDOW_SECONDS:
                recent.popleft()
            if len(recent) >= REPORTS_PER_LINK:
                raise HTTPException(429, "신고가 너무 많습니다. 잠시 뒤에 다시 해 주세요")
            recent.append(now)
        on_report(item["id"], token, body)
        return {"ok": True}

    return router
