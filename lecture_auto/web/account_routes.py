from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections import deque
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from lecture_auto.web.access import admin_user, current_user
from lecture_auto.web.accounts import (
    DEFAULT_LIMITS_ID,
    Accounts,
    Registration,
    ReportBody,
)
from lecture_auto.web.quotas import usage
from lecture_auto.web.settings import Settings

GATEWAY = "https://factchat-cloud.mindlogic.ai/v1/gateway"
SIGNUP_MAX = 20  # accounts per window, across all clients (each signup costs one scrypt hash)
SIGNUP_WINDOW_SECONDS = 600


class SignupBody(Registration):
    @field_validator("email")
    @classmethod
    def email_address(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("이메일 주소를 확인해 주세요")
        return value

    @field_validator("display_name")
    @classmethod
    def name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("이름을 입력해 주세요")
        return value.strip()


class KeyBody(BaseModel):
    key: str = Field(min_length=4, max_length=4096, repr=False)


class DisabledBody(BaseModel):
    disabled: bool = True


class LimitsBody(BaseModel):
    unlimited: bool = False
    max_lectures: int | None = Field(default=None, ge=0, le=1_000_000)
    max_voices: int | None = Field(default=None, ge=0, le=1_000_000)
    storage_limit_mb: int | None = Field(default=None, ge=0, le=100_000_000)


class DefaultLimitsBody(BaseModel):
    max_lectures: int = Field(ge=0, le=1_000_000)
    max_voices: int = Field(ge=0, le=1_000_000)
    storage_limit_mb: int = Field(ge=0, le=100_000_000)


class NewUserBody(SignupBody):
    role: Literal["user", "admin"] = "user"
    unlimited: bool = True
    terms_accepted: bool = True


def account_router(settings: Settings, accounts: Accounts) -> APIRouter:
    router = APIRouter()
    signups: deque[float] = deque()
    signup_lock = threading.Lock()

    @router.get("/api/signup")
    def signup_mode():
        return {"mode": settings.signup_mode}

    @router.post("/api/signup")
    def signup(body: SignupBody):
        if settings.signup_mode == "closed":
            raise HTTPException(403, "현재 회원가입을 받지 않습니다")
        if not body.terms_accepted:
            raise HTTPException(400, "이용약관에 동의해 주세요")
        now = time.monotonic()
        with signup_lock:
            while signups and now - signups[0] > SIGNUP_WINDOW_SECONDS:
                signups.popleft()
            if len(signups) >= SIGNUP_MAX:
                raise HTTPException(429, "가입 요청이 많습니다. 잠시 뒤에 다시 해 주세요")
            signups.append(now)
        try:
            return accounts.signup(body)
        except PermissionError:
            raise HTTPException(403, "초대 코드를 확인해 주세요") from None
        except sqlite3.IntegrityError:
            raise HTTPException(409, "이미 가입된 이메일입니다") from None

    @router.get("/api/me")
    def me(request: Request):
        user = current_user(request)
        return {**user.model_dump(), "gpu": settings.gpu,
                "limits": accounts.effective_limits(user.id), "usage": usage(settings, user.id)}

    @router.get("/api/settings/key")
    def key_info(request: Request):
        return {"last4": accounts.key_last4(current_user(request).id)}

    @router.put("/api/settings/key")
    def save_key(body: KeyBody, request: Request):
        key = body.key.strip()
        if any(c.isspace() for c in key):
            raise HTTPException(400, "API 키를 확인해 주세요")
        try:
            with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False) as client:
                result = client.get(f"{GATEWAY}/models/", headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError:
            raise HTTPException(400, "API 키를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요") from None
        if result.status_code != 200:
            raise HTTPException(400, "API 키 검증에 실패했습니다. 키와 사용 권한을 확인해 주세요")
        accounts.save_key(current_user(request).id, key)
        return {"last4": key[-4:]}

    @router.delete("/api/settings/key")
    def delete_key(request: Request):
        accounts.delete_key(current_user(request).id)
        return {"ok": True}

    @router.post("/api/reports")
    def report(body: ReportBody, request: Request):
        return {"id": accounts.report(current_user(request).id, body)}

    @router.get("/api/admin/reports", dependencies=[Depends(admin_user)])
    def reports():
        return accounts.reports()

    @router.get("/api/admin/users", dependencies=[Depends(admin_user)])
    def users():
        return [{**u.model_dump(), "limits": accounts.effective_limits(u.id),
                 "overrides": accounts.limit_row(u.id), "usage": usage(settings, u.id)}
                for u in accounts.list_users()]

    @router.post("/api/admin/users", dependencies=[Depends(admin_user)])
    def create_user(body: NewUserBody):
        try:
            user = accounts.create_user(body.email, body.password, body.display_name, body.role)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "이미 가입된 이메일입니다") from None
        if body.unlimited:
            accounts.set_limits(user.id, True, None, None, None)
        return user

    @router.put("/api/admin/users/{uid}/limits", dependencies=[Depends(admin_user)])
    def set_limits(uid: str, body: LimitsBody):
        if accounts.get(uid) is None:
            raise HTTPException(404, "사용자를 찾을 수 없습니다")
        accounts.set_limits(uid, body.unlimited, body.max_lectures, body.max_voices, body.storage_limit_mb)
        return accounts.effective_limits(uid)

    @router.get("/api/admin/limits", dependencies=[Depends(admin_user)])
    def default_limits():
        return accounts.default_limits()

    @router.put("/api/admin/limits", dependencies=[Depends(admin_user)])
    def set_default_limits(body: DefaultLimitsBody):
        accounts.set_limits(DEFAULT_LIMITS_ID, False, body.max_lectures, body.max_voices, body.storage_limit_mb)
        return accounts.default_limits()

    @router.post("/api/admin/invites")
    def invite(request: Request):
        return {"code": accounts.invite(admin_user(request).id)}

    @router.put("/api/admin/users/{uid}")
    def disable_user(uid: str, body: DisabledBody, request: Request):
        admin = admin_user(request)
        if uid == admin.id:
            raise HTTPException(400, "현재 로그인한 관리자 계정은 비활성화할 수 없습니다")
        if accounts.get(uid) is None:
            raise HTTPException(404, "사용자를 찾을 수 없습니다")
        accounts.set_disabled(uid, body.disabled)
        return {"ok": True}

    @router.put("/api/admin/lectures/{lid}", dependencies=[Depends(admin_user)])
    def disable_lecture(lid: str, body: DisabledBody):
        accounts.disable_resource("lecture", lid, body.disabled)
        return {"ok": True}

    return router
