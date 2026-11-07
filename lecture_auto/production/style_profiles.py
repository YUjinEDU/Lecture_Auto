"""Account-scoped storage for reusable professor speaking profiles."""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from lecture_auto.pipeline.cache import write_text_atomic
from lecture_auto.pipeline.style_profile import StyleProfile

_COMPONENT = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class ProfileNotFound(ValueError):
    """The requested profile is unavailable in this account."""


@dataclass(frozen=True, slots=True)
class StyleProfiles:
    root: Path
    owner: str | None = None

    @property
    def directory(self) -> Path:
        owner = self.owner or "default"
        if not _COMPONENT.fullmatch(owner):
            raise ProfileNotFound(owner)
        return self.root / "data/style_profiles" / owner

    def path(self, profile_id: str) -> Path:
        if not _COMPONENT.fullmatch(profile_id):
            raise ProfileNotFound(profile_id)
        return self.directory / f"{profile_id}.json"

    def load(self, profile_id: str) -> StyleProfile:
        path = self.path(profile_id)
        if not path.is_file():
            raise ProfileNotFound(profile_id)
        return StyleProfile.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, profile: StyleProfile) -> str:
        profile_id = secrets.token_hex(16)
        write_text_atomic(self.path(profile_id), profile.model_dump_json(indent=2))
        return profile_id

    def listing(self) -> list[dict[str, str]]:
        return [{"id": p.stem, "name": self.load(p.stem).name}
                for p in sorted(self.directory.glob("*.json"))]

    def delete(self, profile_id: str) -> None:
        path = self.path(profile_id)
        try:
            path.unlink()
        except FileNotFoundError:
            raise ProfileNotFound(profile_id) from None
