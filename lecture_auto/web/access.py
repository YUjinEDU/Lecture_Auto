from __future__ import annotations

from fastapi import HTTPException, Request

from lecture_auto.web.accounts import Accounts, User
from lecture_auto.web.auth import COOKIE_NAME, token_user
from lecture_auto.web.settings import Settings


def current_user(request: Request) -> User:
    return request.state.user


def admin_user(request: Request) -> User:
    user = current_user(request)
    if user.role != "admin":
        raise HTTPException(403, "관리자 권한이 필요합니다")
    return user


def session_user(request: Request, settings: Settings, accounts: Accounts) -> User | None:
    uid = token_user(settings.secret, request.cookies.get(COOKIE_NAME))
    user = accounts.get(uid) if uid else None
    return user if user and not user.disabled else None


def can_access(user: User, item: dict) -> bool:
    return user.role == "admin" or item.get("owner") == user.id
