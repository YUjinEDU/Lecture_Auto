from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field

from lecture_auto.web.settings import Settings

logger = logging.getLogger(__name__)


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class User(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(default_factory=lambda: secrets.token_hex(16))
    email: str
    display_name: str
    role: Literal["admin", "user"]
    created_at: str = Field(default_factory=timestamp)
    terms_accepted_at: str | None = None
    disabled: bool = False


class Registration(BaseModel):
    model_config = ConfigDict(frozen=True)
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=1024, repr=False)
    display_name: str = Field(min_length=1, max_length=100)
    terms_accepted: bool
    invite_code: str = Field(default="", max_length=200)


class ReportBody(BaseModel):
    model_config = ConfigDict(frozen=True)
    target_type: Literal["voice", "lecture"]
    target_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)


class Accounts:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.web_dir.mkdir(parents=True, exist_ok=True)
        self.path = settings.web_dir / "app.db"
        self.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret).digest()))
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                    password_hash BLOB NOT NULL, salt BLOB NOT NULL,
                    display_name TEXT NOT NULL, role TEXT NOT NULL,
                    created_at TEXT NOT NULL, terms_accepted_at TEXT,
                    disabled INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS api_keys (
                    user_id TEXT PRIMARY KEY, encrypted BLOB NOT NULL, last4 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS invites (
                    code_hash TEXT PRIMARY KEY, created_by TEXT NOT NULL, used_by TEXT);
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS disabled_resources (
                    kind TEXT NOT NULL, id TEXT NOT NULL, PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS voices (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL,
                    consent_at TEXT NOT NULL, sha256 TEXT NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0, is_default INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS upload_owners (
                    lecture_id TEXT PRIMARY KEY, user_id TEXT NOT NULL);
            """)
        self.path.chmod(0o600)
        self.bootstrap()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=15)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def bootstrap(self) -> None:
        with self.connect() as db:
            if self.settings.password and not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                self._insert(db, User(email=self.settings.admin_email, display_name="관리자", role="admin"),
                             self.settings.password)

    def _insert(self, db: sqlite3.Connection, user: User, password: str) -> User:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
        db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,?,0)",
                   (user.id, user.email, digest, salt, user.display_name, user.role,
                    user.created_at, user.terms_accepted_at))
        return user

    def signup(self, registration: Registration) -> User:
        with self.connect() as db:
            # Taking the write lock before consuming an invitation makes it single-use.
            db.execute("BEGIN IMMEDIATE")
            if self.settings.signup_mode == "invite":
                hashed = hashlib.sha256(registration.invite_code.encode()).hexdigest()
                row = db.execute("SELECT used_by FROM invites WHERE code_hash=?", (hashed,)).fetchone()
                if row is None or row["used_by"] is not None:
                    raise PermissionError("초대 코드가 올바르지 않습니다")
            user = self._insert(db, User(email=registration.email.strip().lower(),
                                        display_name=registration.display_name.strip(),
                                        role="user", terms_accepted_at=timestamp()),
                                registration.password)
            if self.settings.signup_mode == "invite":
                db.execute("UPDATE invites SET used_by=? WHERE code_hash=?", (user.id, hashed))
            return user

    def get(self, uid: str) -> User | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return User.model_validate(dict(row)) if row else None

    def authenticate(self, email: str, password: str) -> User | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        # Unknown emails still pay the password-hashing cost.
        salt = row["salt"] if row else b"\0" * 16
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
        if row and hmac.compare_digest(digest, row["password_hash"]) and not row["disabled"]:
            return User.model_validate(dict(row))
        return None

    def list_users(self) -> list[User]:
        with self.connect() as db:
            return [User.model_validate(dict(r)) for r in db.execute("SELECT * FROM users")]

    def set_disabled(self, uid: str, disabled: bool) -> None:
        with self.connect() as db:
            db.execute("UPDATE users SET disabled=? WHERE id=?", (disabled, uid))

    def save_key(self, uid: str, key: str) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO api_keys VALUES (?,?,?)",
                       (uid, self.cipher.encrypt(key.encode()), key[-4:]))

    def api_key(self, uid: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT encrypted FROM api_keys WHERE user_id=?", (uid,)).fetchone()
        if row is None:
            return None
        try:
            return self.cipher.decrypt(row["encrypted"]).decode()
        except InvalidToken:
            # The server secret changed (secret.key deleted or LECTURE_WEB_SECRET rotated): the key is
            # unrecoverable, so drop it and let the user register it again instead of failing every job.
            logger.warning("stored API key of user %s cannot be decrypted with the current secret; removed", uid)
            self.delete_key(uid)
            return None

    def key_last4(self, uid: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT last4 FROM api_keys WHERE user_id=?", (uid,)).fetchone()
        return row["last4"] if row else None

    def delete_key(self, uid: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM api_keys WHERE user_id=?", (uid,))

    def invite(self, admin_id: str) -> str:
        code = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute("INSERT INTO invites VALUES (?,?,NULL)",
                       (hashlib.sha256(code.encode()).hexdigest(), admin_id))
        return code

    def resource_disabled(self, kind: str, resource_id: str) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM disabled_resources WHERE kind=? AND id=?",
                              (kind, resource_id)).fetchone() is not None

    def disable_resource(self, kind: str, resource_id: str, disabled: bool) -> None:
        with self.connect() as db:
            if disabled:
                db.execute("INSERT OR IGNORE INTO disabled_resources VALUES (?,?)", (kind, resource_id))
            else:
                db.execute("DELETE FROM disabled_resources WHERE kind=? AND id=?", (kind, resource_id))

    def report(self, uid: str, report: ReportBody) -> str:
        rid = secrets.token_hex(16)
        with self.connect() as db:
            db.execute("INSERT INTO reports VALUES (?,?,?,?,?,?)",
                       (rid, uid, report.target_type, report.target_id, report.reason, timestamp()))
        return rid

    def reports(self) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM reports ORDER BY created_at DESC")]
