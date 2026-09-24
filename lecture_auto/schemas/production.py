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
    # S6-a: read from the slide's .qc.json sidecar (pipeline/raon_tts.py's
    # synthesize_raon_slide) if present, None otherwise -- old timeline.json
    # files without these fields still validate.
    stt_status: Literal["pass", "fail", "unavailable"] | None = None
    cer: float | None = None
    gate_ok: bool | None = None


class Timeline(BaseModel):
    lecture_id: str
    mp4: str  # filename
    draft: bool
    total_seconds: float
    entries: list[TimelineEntry] = Field(default_factory=list)


class TranscriptionCheck(BaseModel):
    """Result of comparing synthesized audio's STT transcript against its script.

    Moved here (S6-a) from ``pipeline/raon_tts.py``, which defined it inline
    (see that module's git history) because it imports ``torch`` at module
    scope -- any future API code that only needs this result type used to pull
    in torch/soundfile/pyloudnorm with it. ``pipeline/raon_tts.py`` re-exports
    this exact class so ``from lecture_auto.pipeline.raon_tts import
    TranscriptionCheck`` keeps working for existing callers.
    """

    status: Literal["pass", "fail", "unavailable"]
    reasons: list[str]
    transcript: str | None = None
    cer: float | None = None


class SegmentQC(BaseModel):
    """One synthesized TTS segment/piece within a slide (S6-a, F1/F6)."""

    index: int
    text: str
    seed: int | None
    call: Literal["tts", "tts_continuation"] | None
    continuation_from: int | None = None  # index of the prior SegmentQC used as
    # tts_continuation's audio reference, or None if this piece used plain tts.
    fallback: bool = False  # True if this piece never passed its own quality gate.


class SlideQC(BaseModel):
    """Per-slide TTS quality record, written by ``synthesize_raon_slide`` when
    called with ``qc_path`` (S6-a). Sits next to the WAV as ``<wav>.qc.json``.
    """

    ok: bool
    gate_reasons: list[str] = Field(default_factory=list)
    stt: TranscriptionCheck | None = None
    spoken_text_sha256: str
    segments: list[SegmentQC] = Field(default_factory=list)
    # F6: segments whose continuation source was redrawn/replaced after they
    # were already generated from it -- the join no longer reflects the take
    # that shipped, so these are worth re-listening to. See raon_tts.py.
    boundary_review: list[int] = Field(default_factory=list)
    # S10-b/D-16: how many internal silent runs _shorten_long_pauses cut down
    # to _MAX_PAUSE_S, and how many seconds it removed in total. 0/0.0 when
    # nothing needed shortening.
    pauses_shortened: int = 0
    pause_seconds_removed: float = 0.0
    synth_version: str
    created_at: datetime
