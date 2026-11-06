from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lecture_auto.core.project import (
    ProjectConfig,
    delete_project,
    new_lecture_id,
    save_project,
)
from lecture_auto.pipeline import approval as approvals
from lecture_auto.pipeline.approval import load_approvals
from lecture_auto.production import batch as bgl
from lecture_auto.web import store
from lecture_auto.web.auth import COOKIE_NAME, check_password, issue_token, token_valid
from lecture_auto.web.runner import KINDS, JobError, JobRunner
from lecture_auto.web.settings import NEW_LECTURE_REF_VOICE, Settings

STATIC = Path(__file__).parent / "static"
UPLOAD_MAGIC = {".pptx": b"PK\x03\x04", ".pdf": b"%PDF"}
AUDIO_KINDS = {"main": "slide_{:03d}.wav", "cand": "slide_{:03d}.cand.wav", "prev": "slide_{:03d}.prev.wav"}
LOGIN_FAILURES_MAX = 10  # wrong passwords per window, across all clients
LOGIN_WINDOW_SECONDS = 60
LOGIN_FAILURE_DELAY = 1.0
SMALL_BODY_BYTES = 1024 * 1024  # every API body except the upload


class LoginBody(BaseModel):
    password: str


class ScriptBody(BaseModel):
    script: str = Field(min_length=1, max_length=20000)


class JobBody(BaseModel):
    kind: str
    slides: list[int] | None = None


class PromoteBody(BaseModel):
    allow_failed: bool = False
    note: str = Field(default="", max_length=500)


def create_app(settings: Settings, runner: JobRunner | None = None) -> FastAPI:
    runner = runner or JobRunner(settings)
    projects_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_app):
        runner.start()
        yield
        runner.stop()

    app = FastAPI(title="Lecture Auto 스튜디오", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.runner = runner

    @app.middleware("http")
    async def reject_before_reading_body(request: Request, call_next):
        # FastAPI parses a multipart upload before a route dependency runs, so the cookie
        # is checked here, ahead of any body being read; oversize bodies are refused too.
        path = request.url.path
        if path.startswith("/api/") and path not in ("/api/login", "/api/logout") and not token_valid(
            settings.secret, request.cookies.get(COOKIE_NAME)
        ):
            return JSONResponse({"detail": "로그인이 필요합니다"}, status_code=401)
        limit = SMALL_BODY_BYTES
        if request.method == "POST" and path == "/api/lectures":
            limit += settings.max_upload_mb * 1024 * 1024
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > limit:
            return JSONResponse({"detail": "요청이 너무 큽니다"}, status_code=413)
        return await call_next(request)

    def require_auth(request: Request) -> None:
        if not token_valid(settings.secret, request.cookies.get(COOKIE_NAME)):
            raise HTTPException(401, "로그인이 필요합니다")

    def lecture_or_404(lecture_id: str) -> dict:
        try:
            return store.get_lecture(settings, lecture_id)
        except store.LectureNotFound:
            raise HTTPException(404, "강의를 찾을 수 없습니다") from None

    def ensure_idle(lecture_id: str) -> None:
        job = runner.busy(lecture_id)
        if job:
            raise HTTPException(409, f"이 강의는 작업 중입니다: {job['label']} ({job['status']})")

    # Endpoints run in a thread pool: without this, two approvals could interleave their
    # read-modify-write of approved.json, and a job could start between ensure_idle and
    # the file change it guards.
    edit_lock = threading.Lock()

    @contextlib.contextmanager
    def idle(lecture_id: str):
        with edit_lock:
            ensure_idle(lecture_id)
            yield

    def review(lecture_id: str, change) -> None:
        """Approval-file changes run in this process: they take a second, not a job."""
        try:
            change(settings.work_dir / lecture_id)
        except (ValueError, OSError) as e:
            raise HTTPException(400, f"명령 실패: {e}") from None

    def with_root_paths(item: dict) -> dict:
        return {**item, "ref_voice": store.ref_voice_path(settings, item)}

    auth = [Depends(require_auth)]

    login_failures: deque[float] = deque()

    @app.post("/api/login")
    async def login(body: LoginBody, request: Request, response: Response):
        # One shared password: cap wrong guesses globally. No await between the check and the
        # append, so a burst of parallel guesses cannot slip past the limit.
        now = time.monotonic()
        while login_failures and now - login_failures[0] > LOGIN_WINDOW_SECONDS:
            login_failures.popleft()
        if len(login_failures) >= LOGIN_FAILURES_MAX:
            raise HTTPException(429, "로그인 시도가 너무 많습니다. 1분 뒤에 다시 해 주세요")
        if not check_password(body.password, settings.password):
            login_failures.append(now)
            await asyncio.sleep(LOGIN_FAILURE_DELAY)  # does not hold a worker thread, unlike time.sleep
            raise HTTPException(401, "비밀번호가 맞지 않습니다")
        # Secure only when the browser reached us over HTTPS (directly or via the proxy);
        # on a plain-HTTP LAN address a Secure cookie would never be sent back.
        forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        response.set_cookie(
            COOKIE_NAME, issue_token(settings.secret, settings.session_hours),
            max_age=settings.session_hours * 3600, httponly=True, samesite="strict", path="/",
            secure=request.url.scheme == "https" or forwarded == "https",
        )
        return {"ok": True}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/me", dependencies=auth)
    def me():
        return {"ok": True, "gpu": settings.gpu}

    @app.get("/api/lectures", dependencies=auth)
    def lectures():
        out = []
        for item in store.all_lectures(settings):
            summary = store.lecture_summary(settings, item)
            summary["job"] = runner.busy(item["id"])
            out.append(summary)
        return out

    @app.post("/api/lectures", dependencies=auth)
    async def create_lecture(
        file: Annotated[UploadFile, File()],
        name: Annotated[str, Form(min_length=1, max_length=100)],
        subject: Annotated[str, Form(max_length=100)] = "",
        target_minutes: Annotated[float, Form(gt=0, le=120)] = 30.0,
        min_minutes: Annotated[float | None, Form(gt=0, le=120)] = None,
    ):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in UPLOAD_MAGIC:
            raise HTTPException(400, "PPTX 또는 PDF 파일만 올릴 수 있습니다")
        data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"파일이 너무 큽니다 (최대 {settings.max_upload_mb}MB)")
        if not data.startswith(UPLOAD_MAGIC[suffix]):
            raise HTTPException(400, "파일 내용이 PPTX/PDF 형식이 아닙니다")
        with projects_lock:
            return _register(file, data, suffix, name, subject, target_minutes, min_minutes)

    def _register(file, data, suffix, name, subject, target_minutes, min_minutes):
        existing = [lec["id"] for lec in store.all_lectures(settings)]
        # A deleted lecture's files stay on disk; reusing its id would hand the new deck
        # its approvals, hand-edited scripts and final video.
        for d in (settings.work_dir, settings.output_dir, settings.uploads_dir):
            if d.is_dir():
                existing += [p.name for p in d.iterdir()]
        lecture_id = new_lecture_id(name, existing)
        rel = Path("data/web/uploads") / lecture_id / f"{lecture_id}{suffix}"
        dest = settings.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        save_project(ProjectConfig(
            id=lecture_id,
            name=name.strip(),
            subject=subject.strip() or "강의",
            **{suffix.lstrip("."): rel},
            target_minutes=target_minutes,
            min_minutes=min_minutes or None,
            voice_match=True,
            ref_voice=NEW_LECTURE_REF_VOICE,
            master_audio=True,
            web=True,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        ), settings.projects_dir)
        return store.lecture_summary(settings, store.get_lecture(settings, lecture_id))

    @app.delete("/api/lectures/{lecture_id}", dependencies=auth)
    def delete_lecture(lecture_id: str):
        item = lecture_or_404(lecture_id)
        if not item.get("web"):
            raise HTTPException(400, "기본 등록 강의는 웹에서 삭제할 수 없습니다")
        ensure_idle(lecture_id)
        with projects_lock:
            delete_project(lecture_id, settings.projects_dir)
        return {"ok": True}

    @app.get("/api/lectures/{lecture_id}", dependencies=auth)
    def lecture(lecture_id: str):
        item = lecture_or_404(lecture_id)
        summary = store.lecture_summary(settings, item)
        summary["job"] = runner.busy(lecture_id)
        summary["slide_list"] = store.slide_views(settings, item)
        return summary

    @app.put("/api/lectures/{lecture_id}/slides/{number}/script", dependencies=auth)
    def put_script(lecture_id: str, number: int, body: ScriptBody):
        item = lecture_or_404(lecture_id)
        with idle(lecture_id):
            try:
                store.save_script(settings, item, number, body.script.strip())
            except FileNotFoundError:
                raise HTTPException(404, "대본이 아직 없습니다") from None
            return next(v for v in store.slide_views(settings, item) if v["number"] == number)

    @app.post("/api/lectures/{lecture_id}/slides/{number}/approve", dependencies=auth)
    def approve(lecture_id: str, number: int):
        item = lecture_or_404(lecture_id)
        with idle(lecture_id):
            if not (settings.work_dir / lecture_id / "audio" / f"slide_{number:03d}.wav").exists():
                raise HTTPException(404, "음성이 없습니다")
            review(lecture_id, lambda _w: bgl._cli_approve(
                with_root_paths(item), settings.work_dir, str(number), store.pronunciation_entries(settings)))
            return next(v for v in store.slide_views(settings, item) if v["number"] == number)

    @app.post("/api/lectures/{lecture_id}/slides/{number}/promote", dependencies=auth)
    def promote(lecture_id: str, number: int, body: PromoteBody):
        item = lecture_or_404(lecture_id)
        with idle(lecture_id):
            if not (settings.work_dir / lecture_id / "audio" / f"slide_{number:03d}.cand.wav.json").exists():
                raise HTTPException(404, "후보 음성이 없습니다")
            review(lecture_id, lambda _w: bgl._cli_promote(
                item, settings.work_dir, str(number), body.allow_failed, body.note or "웹에서 후보 채택"))
            return next(v for v in store.slide_views(settings, item) if v["number"] == number)

    @app.post("/api/lectures/{lecture_id}/slides/{number}/unapprove", dependencies=auth)
    def unapprove(lecture_id: str, number: int):
        item = lecture_or_404(lecture_id)
        with idle(lecture_id):
            if number not in load_approvals(settings.work_dir / lecture_id, lecture_id).slides:
                raise HTTPException(404, "승인된 슬라이드가 아닙니다")
            review(lecture_id, lambda w: approvals.save_approvals(
                w, approvals.unapprove(approvals.load_approvals(w, lecture_id), number)))
            return next(v for v in store.slide_views(settings, item) if v["number"] == number)

    @app.post("/api/lectures/{lecture_id}/slides/{number}/restore-prev", dependencies=auth)
    def restore_prev(lecture_id: str, number: int):
        item = lecture_or_404(lecture_id)
        with idle(lecture_id):
            if not (settings.work_dir / lecture_id / "audio" / f"slide_{number:03d}.prev.wav").exists():
                raise HTTPException(404, "되돌릴 이전 음성이 없습니다")
            review(lecture_id, lambda w: approvals.save_approvals(
                w, approvals.restore_previous(approvals.load_approvals(w, lecture_id), w / "audio", number)))
            return next(v for v in store.slide_views(settings, item) if v["number"] == number)

    @app.get("/api/lectures/{lecture_id}/slides/{number}/image", dependencies=auth)
    def slide_image(lecture_id: str, number: int):
        lecture_or_404(lecture_id)
        path = settings.work_dir / lecture_id / "rendered" / f"slide_{number:03d}.png"
        if not path.exists():
            raise HTTPException(404, "이미지가 없습니다")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/lectures/{lecture_id}/slides/{number}/audio/{kind}", dependencies=auth)
    def slide_audio(lecture_id: str, number: int, kind: str):
        lecture_or_404(lecture_id)
        if kind not in AUDIO_KINDS:
            raise HTTPException(400, "잘못된 음성 종류")
        path = settings.work_dir / lecture_id / "audio" / AUDIO_KINDS[kind].format(number)
        if not path.exists():
            raise HTTPException(404, "음성이 없습니다")
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.get("/api/lectures/{lecture_id}/files/{name}", dependencies=auth)
    def output_file(lecture_id: str, name: str):
        lecture_or_404(lecture_id)
        if name not in {f["name"] for f in store.output_files(settings, lecture_id)}:
            raise HTTPException(404, "파일이 없습니다")
        return FileResponse(settings.output_dir / lecture_id / name, filename=name)

    @app.get("/api/jobs", dependencies=auth)
    def jobs():
        return runner.list()[:100]

    @app.post("/api/lectures/{lecture_id}/jobs", dependencies=auth)
    def submit(lecture_id: str, body: JobBody):
        item = lecture_or_404(lecture_id)
        if body.kind not in KINDS:
            raise HTTPException(400, "알 수 없는 작업 종류")
        try:
            with edit_lock:
                return runner.submit(body.kind, item, body.slides)
        except JobError as e:
            raise HTTPException(409 if "이미" in str(e) else 400, str(e)) from None

    @app.get("/api/jobs/{job_id}", dependencies=auth)
    def job(job_id: str):
        found = runner.get(job_id)
        if found is None:
            raise HTTPException(404, "작업이 없습니다")
        return found

    @app.get("/api/jobs/{job_id}/log", dependencies=auth)
    def job_log(job_id: str, offset: int = 0):
        if runner.get(job_id) is None:
            raise HTTPException(404, "작업이 없습니다")
        text, next_offset = runner.read_log(job_id, offset)
        return {"text": text, "offset": next_offset}

    @app.post("/api/jobs/{job_id}/cancel", dependencies=auth)
    def cancel(job_id: str):
        try:
            return runner.cancel(job_id)
        except KeyError:
            raise HTTPException(404, "작업이 없습니다") from None
        except JobError as e:
            raise HTTPException(409, str(e)) from None

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
