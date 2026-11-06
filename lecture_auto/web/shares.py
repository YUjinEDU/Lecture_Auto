from __future__ import annotations

import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shares (
    token TEXT PRIMARY KEY,
    lecture_id TEXT NOT NULL,
    created_by TEXT,
    created_at REAL NOT NULL,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS shares_lecture ON shares (lecture_id);
"""


def _connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def create_share(db: Path, lecture_id: str, created_by: str | None) -> dict:
    token = secrets.token_urlsafe(16)
    with closing(_connect(db)) as conn, conn:
        conn.execute(
            "INSERT INTO shares (token, lecture_id, created_by, created_at) VALUES (?, ?, ?, ?)",
            (token, lecture_id, created_by, time.time()),
        )
    return {"token": token, "lecture_id": lecture_id, "created_by": created_by, "revoked_at": None}


def list_shares(db: Path, lecture_id: str) -> list[dict]:
    with closing(_connect(db)) as conn:
        rows = conn.execute(
            "SELECT * FROM shares WHERE lecture_id = ? ORDER BY created_at DESC", (lecture_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def revoke_share(db: Path, lecture_id: str, token: str) -> bool:
    with closing(_connect(db)) as conn, conn:
        cur = conn.execute(
            "UPDATE shares SET revoked_at = ? WHERE token = ? AND lecture_id = ? AND revoked_at IS NULL",
            (time.time(), token, lecture_id),
        )
    return cur.rowcount == 1


def revoke_all(db: Path, lecture_id: str) -> int:
    with closing(_connect(db)) as conn, conn:
        cur = conn.execute(
            "UPDATE shares SET revoked_at = ? WHERE lecture_id = ? AND revoked_at IS NULL", (time.time(), lecture_id)
        )
    return cur.rowcount


def resolve_share(db: Path, token: str) -> str | None:
    if not token or len(token) > 64:
        return None
    with closing(_connect(db)) as conn:
        row = conn.execute("SELECT lecture_id FROM shares WHERE token = ? AND revoked_at IS NULL", (token,)).fetchone()
    return row["lecture_id"] if row else None
