"""Pydantic schemas for the Interactive Review Lecture Player."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewSlideData(BaseModel):
    """Data for a single reviewable slide."""

    slide_index: int
    slide_number: int
    title: str
    image_url: str
    easy_script: str = Field(..., description="90-second easy-to-understand review script")
    key_point: str = Field(..., description="1-sentence core conceptual takeaway")
    exam_hint: str = Field(..., description="Professor's exam/assignment emphasis")
    raw_audio_start_sec: float
    raw_audio_end_sec: float
    raw_audio_url: str | None = None
    ai_audio_url: str | None = None


class ReviewPack(BaseModel):
    """Full review package for a lecture."""

    course_title: str
    lecture_title: str
    slides: list[ReviewSlideData]


class QnARequest(BaseModel):
    """Question sent by a student regarding a specific slide."""

    slide_index: int
    question: str


class QnAResponse(BaseModel):
    """Answer generated in professor persona with optional audio."""

    slide_index: int
    question: str
    answer_text: str
    answer_audio_url: str | None = None
