from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_LECTURE_REF_VOICE = Path("data/audio_ref/reference_v2.wav")


@dataclass(frozen=True)
class Settings:
    """Where the web layer reads and writes. Every path is relative to ``root``,
    which is also the cwd of the batch/produce subprocesses (they use relative
    ``data/`` and ``output/`` paths), so a test can point it at a sandbox copy."""

    root: Path
    password: str
    secret: bytes
    gpu: str = "0"
    python: str = sys.executable
    code_root: Path = REPO_ROOT
    session_hours: int = 12
    max_upload_mb: int = 300
    extra_env: dict[str, str] = field(default_factory=dict)
    admin_email: str = "admin@local"
    signup_mode: Literal["closed", "open", "invite"] = "closed"
    max_lectures: int = 30
    max_voices: int = 10
    storage_limit_mb: int = 5120
    max_voice_upload_mb: int = 50
    raon_enabled: bool = True  # False on servers without a GPU: Gemini (API) voices only

    @property
    def work_dir(self) -> Path:
        return self.root / "data" / "work_batch"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def web_dir(self) -> Path:
        return self.root / "data" / "web"

    @property
    def projects_dir(self) -> Path:
        return self.root / "data" / "projects"

    @property
    def jobs_dir(self) -> Path:
        return self.web_dir / "jobs"

    @property
    def uploads_dir(self) -> Path:
        return self.web_dir / "uploads"


def _load_secret(web_dir: Path) -> bytes:
    if os.environ.get("LECTURE_WEB_SECRET"):
        return os.environ["LECTURE_WEB_SECRET"].encode()
    path = web_dir / "secret.key"
    if path.exists():
        return path.read_bytes()
    web_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def settings_from_env() -> Settings:
    password = os.environ.get("LECTURE_WEB_PASSWORD", "")
    root = Path(os.environ.get("LECTURE_WEB_ROOT", str(REPO_ROOT))).resolve()
    gpu = os.environ.get("LECTURE_WEB_GPU", "0")
    mode = os.environ.get("LECTURE_WEB_SIGNUP", "closed")
    if mode not in ("closed", "open", "invite"):
        raise SystemExit("LECTURE_WEB_SIGNUP must be closed, open or invite")
    return Settings(
        root=root, password=password, secret=_load_secret(root / "data" / "web"), gpu=gpu,
        signup_mode=mode,
        admin_email=os.environ.get("LECTURE_WEB_ADMIN_EMAIL", "admin@local").strip().lower(),
        max_upload_mb=int(os.environ.get("LECTURE_WEB_MAX_UPLOAD_MB", "300")),
        max_voice_upload_mb=int(os.environ.get("LECTURE_WEB_MAX_VOICE_UPLOAD_MB", "50")),
        max_lectures=int(os.environ.get("LECTURE_WEB_MAX_LECTURES", "30")),
        max_voices=int(os.environ.get("LECTURE_WEB_MAX_VOICES", "10")),
        storage_limit_mb=int(os.environ.get("LECTURE_WEB_STORAGE_LIMIT_MB", "5120")),
        raon_enabled=os.environ.get("LECTURE_WEB_RAON", "on").strip().lower() not in ("off", "0", "false", "no"),
    )
