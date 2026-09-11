"""Whole-lecture design produced before any per-slide script is written.

Generating scripts one slide at a time (the old approach) has no notion of
which slides belong to the same story beat, which example keeps recurring,
or which slides deserve 90 seconds vs. 15. LecturePlan captures that once,
up front, from all slides at once; SectionScript carries the plan forward
section by section so mid-section slides don't re-introduce themselves.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RecurringExample(BaseModel):
    name: str
    purpose: str
    slides: list[int]


class LectureSection(BaseModel):
    title: str
    slides: list[int]
    minutes: float
    goal: str


class LecturePlan(BaseModel):
    lecture_title: str
    total_minutes: float
    opening_context: str
    core_message: str
    recurring_examples: list[RecurringExample] = Field(default_factory=list)
    sections: list[LectureSection]


class CarryForward(BaseModel):
    explained: list[str] = Field(default_factory=list)
    active_example: str = ""
    next_question: str = ""


class SectionSlideScript(BaseModel):
    slide_number: int
    target_seconds: float
    script: str


class SectionScriptResult(BaseModel):
    section_summary: str
    carry_forward: CarryForward
    slides: list[SectionSlideScript]
