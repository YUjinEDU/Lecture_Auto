"""Professor-reviewable slide goals and pacing."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SlideRole = Literal["도입", "개념", "예시", "비교", "과정", "정리", "전환", "기타"]


class SlideIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slide: int = Field(ge=1)
    thesis: str = Field(min_length=1, max_length=2000)
    role: SlideRole
    importance: int = Field(ge=1, le=3)
    pitfall: str = Field(default="", max_length=4000)
    example: str = Field(default="", max_length=4000)
    seconds: int = Field(ge=10, le=600)


class IntentSheet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lecture_id: str
    slides: list[SlideIntent] = Field(min_length=1)
    generated_at: datetime
    edited: bool = False
    input_hash: str

    @model_validator(mode="after")
    def unique_slides(self) -> IntentSheet:
        numbers = [s.slide for s in self.slides]
        if len(numbers) != len(set(numbers)):
            raise ValueError("슬라이드 번호가 중복됩니다")
        return self

    @property
    def content_hash(self) -> str:
        """Metadata changes must not invalidate scripts; professor edits must."""
        payload = json.dumps(
            [s.model_dump() for s in sorted(self.slides, key=lambda s: s.slide)],
            ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
