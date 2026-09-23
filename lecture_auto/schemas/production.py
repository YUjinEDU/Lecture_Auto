"""Approval + timeline contracts for the human-review step (S2).

S1 made every existing slide WAV's cache key invalid the moment
``target_seconds`` joined it (see ``scripts/batch_generate_lectures.py``'s
``_tts_cache_key``), so a plain "is the hash valid" check can no longer tell
a professor-approved take from stale/never-generated audio. ``ApprovalManifest``
records what a human explicitly signed off on -- pinned by content hash, not
by cache key -- so it survives cache-key churn. ``Timeline`` is the per-slide
start/duration map a future web player reads to jump to "slide 12". Both are
plain Pydantic models written to disk as atomic JSON (``work/<lec>/approved.json``,
``<mp4 stem>.timeline.json``); a future FastAPI layer reads/writes the same files.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ApprovedSlide(BaseModel):
    wav: str  # filename within the lecture's audio dir, e.g. "slide_012.wav"
    sha256: str  # hash of the WAV bytes at approval time
    approved_at: datetime  # timezone-aware
    source: Literal["existing", "candidate", "gate_pass"]
    gate_ok: bool | None = None  # automated check result at approval time, None if unknown
    note: str = ""


class ApprovalManifest(BaseModel):
    lecture_id: str
    slides: dict[int, ApprovedSlide] = Field(default_factory=dict)


class TimelineEntry(BaseModel):
    slide_number: int
    start_seconds: float
    duration_seconds: float
    wav: str
    wav_sha256: str
    approved: bool


class Timeline(BaseModel):
    lecture_id: str
    mp4: str  # filename
    draft: bool
    total_seconds: float
    entries: list[TimelineEntry] = Field(default_factory=list)
