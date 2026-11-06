from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path

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
    if not password:
        raise SystemExit("LECTURE_WEB_PASSWORD is not set -- refusing to start without a login password")
    root = Path(os.environ.get("LECTURE_WEB_ROOT", str(REPO_ROOT))).resolve()
    gpu = os.environ.get("LECTURE_WEB_GPU", "0")
    return Settings(root=root, password=password, secret=_load_secret(root / "data" / "web"), gpu=gpu)
