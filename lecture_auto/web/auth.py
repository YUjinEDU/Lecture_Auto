from __future__ import annotations

import hashlib
import hmac
import time

COOKIE_NAME = "la_session"


def check_password(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())


def issue_token(secret: bytes, hours: int, now: float | None = None, *, user_id: str = "") -> str:
    expires = int((time.time() if now is None else now) + hours * 3600)
    if user_id:
        payload = f"v2:{user_id}:{expires}"
        sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        return f"{user_id}.{expires}.{sig}"
    sig = hmac.new(secret, f"v1:{expires}".encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def token_valid(secret: bytes, token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    if token.count(".") == 2:
        return token_user(secret, token, now) is not None
    expires_s, sig = token.split(".", 1)
    if not expires_s.isdigit():
        return False
    expected = hmac.new(secret, f"v1:{expires_s}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    return int(expires_s) > (time.time() if now is None else now)


def token_user(secret: bytes, token: str | None, now: float | None = None) -> str | None:
    if not token or token.count(".") != 2:
        return None
    uid, expires, sig = token.split(".")
    if not expires.isdigit() or len(expires) > 12 or not uid:
        return None
    expected = hmac.new(secret, f"v2:{uid}:{expires}".encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected) and int(expires) > (time.time() if now is None else now):
        return uid
    return None
