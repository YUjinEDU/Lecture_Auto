"""A lecture's settings, stored as ``<projects dir>/<id>/project.json``.

The production code still passes a lecture around as a plain dict (``as_item``), the
shape the old ``LECTURES`` list had; this module owns validation and storage.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from lecture_auto.pipeline.cache import write_text_atomic

PROJECTS_ENV = "LECTURE_AUTO_PROJECTS"
DEFAULT_PROJECTS_DIR = Path("data/projects")
DEFAULT_REF_VOICE = Path("data/audio_ref/reference_v1.wav")
PROJECT_FILE = "project.json"
_ID = re.compile(r"^[0-9A-Za-z가-힣_-]+$")


class ProjectConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    subject: str
    pdf: Path | None = None
    pptx: Path | None = None
    reference_script: Path | None = None
    clone_from: str | None = None
    previous: str | None = None
    target_minutes: float | None = None
    min_minutes: float | None = None
    ref_voice: Path | None = None
    master_audio: bool = False
    voice_match: bool = False
    restyle: bool = False
    critic: bool = False
    style_profile: str | None = None
    web: bool = False
    created_at: str | None = None
    owner: str | None = None
    tts_engine: Literal["raon", "gemini"] = "raon"
    tts_voice: str | None = None
    tts_instructions: str | None = None

    def model_post_init(self, _context) -> None:
        if not _ID.match(self.id):
            raise ValueError(f"project id may only hold letters, digits, '_' and '-': {self.id!r}")

    def as_item(self) -> dict:
        return self.model_dump(exclude_defaults=True)


def projects_dir() -> Path:
    return Path(os.environ.get(PROJECTS_ENV, str(DEFAULT_PROJECTS_DIR)))


def load_projects(root: Path | None = None) -> list[ProjectConfig]:
    root = projects_dir() if root is None else root
    if not root.is_dir():
        return []
    projects = []
    for path in root.glob(f"*/{PROJECT_FILE}"):
        try:
            projects.append(ProjectConfig.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValidationError):
            logging.getLogger(__name__).warning("Skipping invalid project: %s", path)
    return sorted(projects, key=lambda p: (
        int(m.group(1)) if (m := re.match(r"^(\d+)_", p.id)) else 0, p.id))


def save_project(project: ProjectConfig, root: Path | None = None) -> Path:
    root = projects_dir() if root is None else root
    path = root / project.id / PROJECT_FILE
    write_text_atomic(path, project.model_dump_json(indent=2, exclude_none=True))
    return path


def delete_project(project_id: str, root: Path | None = None) -> None:
    root = projects_dir() if root is None else root
    path = root / project_id / PROJECT_FILE
    path.unlink(missing_ok=True)
    if path.parent.is_dir() and not any(path.parent.iterdir()):
        path.parent.rmdir()


_UNSAFE = re.compile(r"[^0-9A-Za-z가-힣_-]+")


def new_lecture_id(name: str, existing_ids: list[str]) -> str:
    """``NN_<name>`` with the next free number, never equal to an existing id."""
    slug = _UNSAFE.sub("_", name).strip("_")[:40] or "lecture"
    numbers = [int(m.group(1)) for i in existing_ids if (m := re.match(r"^(\d+)_", i))]
    n = max(numbers, default=0) + 1
    while True:
        candidate = f"{n:02d}_{slug}"
        if candidate not in existing_ids:
            return candidate
        n += 1
