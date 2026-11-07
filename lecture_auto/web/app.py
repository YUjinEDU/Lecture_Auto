from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lecture_auto.web import store
from lecture_auto.web.access import can_access, current_user, session_user
from lecture_auto.web.account_routes import account_router
from lecture_auto.web.accounts import Accounts, ReportBody
from lecture_auto.web.auth import COOKIE_NAME, issue_token
from lecture_auto.web.export_routes import export_router
from lecture_auto.web.lecture_routes import lecture_router
from lecture_auto.web.owner_routes import make_owner_router
from lecture_auto.web.public import ReportBody as PublicReportBody
from lecture_auto.web.public import make_public_router
from lecture_auto.web.review_routes import review_router
from lecture_auto.web.runner import JobRunner
from lecture_auto.web.settings import Settings
from lecture_auto.web.voices import voices_router

STATIC = Path(__file__).parent / "static"
LOGIN_FAILURES_MAX = 10
LOGIN_GLOBAL_MAX = 50
LOGIN_WINDOW_SECONDS = 60
LOGIN_FAILURE_DELAY = 1.0
SMALL_BODY_BYTES = 1024 * 1024


class LoginBody(BaseModel):
    email: str = Field(default="", max_length=254)
    password: str = Field(max_length=1024, repr=False)


def create_app(settings: Settings, runner: JobRunner | None = None) -> FastAPI:
    accounts = Accounts(settings)
    runner = runner or JobRunner(settings)

    @asynccontextmanager
    async def lifespan(_app):
        runner.start()
        yield
        runner.stop()

    app = FastAPI(title="Lecture Auto 스튜디오", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.runner, app.state.accounts = settings, runner, accounts
    app.state.storage_lock = threading.RLock()
    app.state.edit_lock = threading.RLock()

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, error: RequestValidationError):
        # Validation responses must not echo passwords or API keys from request bodies.
        return JSONResponse({"detail": [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in error.errors()
        ]}, status_code=422)

    @app.middleware("http")
    async def reject_before_reading_body(request: Request, call_next):
        path = request.url.path
        public = {"/api/login", "/api/logout", "/api/signup"}
        if path.startswith("/api/") and path not in public and not path.startswith("/api/public/"):
            user = session_user(request, settings, accounts)
            if user is None:
                return JSONResponse({"detail": "로그인이 필요합니다"}, status_code=401)
            request.state.user = user
            # This gate precedes multipart parsing and covers every slide, file and job route.
            parts = path.strip("/").split("/")
            lid = None
            if len(parts) >= 3 and parts[1] == "lectures":
                lid = parts[2]
            if len(parts) >= 3 and parts[1] == "jobs":
                job = runner.get(parts[2])
                if job is None:
                    return JSONResponse({"detail": "작업이 없습니다"}, status_code=404)
                if user.role != "admin" and job.get("owner") != user.id:
                    return JSONResponse({"detail": "작업이 없습니다"}, status_code=404)
            if lid:
                try:
                    item = store.get_lecture(settings, lid)
                except store.LectureNotFound:
                    return JSONResponse({"detail": "강의를 찾을 수 없습니다"}, status_code=404)
                if not can_access(user, item) or (user.role != "admin" and
                                                          accounts.resource_disabled("lecture", lid)):
                    return JSONResponse({"detail": "강의를 찾을 수 없습니다"}, status_code=404)
        limit = SMALL_BODY_BYTES
        if request.method == "POST" and path in ("/api/lectures", "/api/voices"):
            limit += (settings.max_upload_mb if path == "/api/lectures"
                      else settings.max_voice_upload_mb) * 1024 * 1024
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > limit:
            return JSONResponse({"detail": "요청이 너무 큽니다"}, status_code=413)
        return await call_next(request)

    failures: deque[float] = deque()
    per_email: dict[str, deque[float]] = defaultdict(deque)
    login_lock = threading.Lock()

    @app.post("/api/login")
    async def login(body: LoginBody, request: Request, response: Response):
        email = body.email.strip().lower() or settings.admin_email
        now = time.monotonic()
        with login_lock:
            while failures and now - failures[0] > LOGIN_WINDOW_SECONDS:
                failures.popleft()
            # Discard stale email buckets so arbitrary addresses cannot grow memory forever.
            for address in list(per_email):
                while per_email[address] and now - per_email[address][0] > LOGIN_WINDOW_SECONDS:
                    per_email[address].popleft()
                if not per_email[address]:
                    del per_email[address]
            if len(failures) >= LOGIN_GLOBAL_MAX or len(per_email[email]) >= LOGIN_FAILURES_MAX:
                raise HTTPException(429, "로그인 시도가 너무 많습니다. 1분 뒤에 다시 해 주세요")
            # Reserve an attempt before hashing off-thread, preventing concurrent bursts.
            failures.append(now)
            per_email[email].append(now)
        user = await anyio.to_thread.run_sync(accounts.authenticate, email, body.password)
        if user is None:
            await anyio.sleep(LOGIN_FAILURE_DELAY)
            raise HTTPException(401, "이메일 또는 비밀번호가 맞지 않습니다")
        with login_lock:
            failures.remove(now)
            per_email[email].remove(now)
        forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        response.set_cookie(
            COOKIE_NAME, issue_token(settings.secret, settings.session_hours, user_id=user.id),
            max_age=settings.session_hours * 3600, httponly=True, samesite="strict", path="/",
            secure=request.url.scheme == "https" or forwarded == "https",
        )
        return user

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True}

    app.include_router(account_router(settings, accounts))
    app.include_router(voices_router(settings, accounts))
    app.include_router(lecture_router(settings, runner, accounts))
    app.include_router(review_router(settings, runner))
    app.include_router(export_router(settings))

    def public_item(lecture_id: str) -> dict | None:
        try:
            item = store.get_lecture(settings, lecture_id)
        except store.LectureNotFound:
            return None
        owner = accounts.get(item["owner"]) if item.get("owner") else None
        if accounts.resource_disabled("lecture", lecture_id) or (item.get("owner") and (owner is None or owner.disabled)):
            return None
        return item

    def public_report(lecture_id: str, token: str, body: PublicReportBody) -> None:
        where = f" ({int(body.at_seconds // 60)}분 {int(body.at_seconds % 60)}초)" if body.at_seconds is not None else ""
        accounts.report("public", ReportBody(
            target_type="lecture", target_id=lecture_id,
            reason=f"[학생 페이지 신고: {body.kind}{where}, 링크 {token[:6]}…] {body.text or '(내용 없음)'}",
        ))

    def owned_lecture(request: Request, lecture_id: str) -> dict:
        try:
            item = store.get_lecture(settings, lecture_id)
        except store.LectureNotFound:
            raise HTTPException(404, "강의를 찾을 수 없습니다") from None
        if not can_access(current_user(request), item):
            raise HTTPException(404, "강의를 찾을 수 없습니다")
        return item

    app.include_router(make_public_router(settings, public_item, public_report))
    app.include_router(make_owner_router(settings, owned_lecture, lambda request: current_user(request).id))

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-cache"})

    @app.get("/terms", response_class=HTMLResponse)
    def terms():
        return RedirectResponse("static/terms.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
