"""Persist section reviews and apply safe results as generated scripts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter

from lecture_auto.llm import LLMClient
from lecture_auto.pipeline.cache import (
    content_hash,
    is_cache_valid,
    write_cache_hash,
    write_text_atomic,
)
from lecture_auto.pipeline.critic import (
    REVIEW_INSTRUCTION,
    REVIEW_VERSION,
    REWRITE_INSTRUCTION,
    REWRITE_VERSION,
    CriticResult,
    CriticSlide,
    refine_section,
)
from lecture_auto.pipeline.script_gen import _extract_all_text
from lecture_auto.pipeline.style_profile import StyleProfile
from lecture_auto.schemas.intent import IntentSheet
from lecture_auto.schemas.lecture_plan import SectionScriptResult
from lecture_auto.schemas.manifest import SlideRecord


@dataclass(frozen=True, slots=True)
class CriticContext:
    work: Path
    slides: list[SlideRecord]
    model_key: str
    intent: IntentSheet | None = None
    profile: StyleProfile | None = None


def refine_cached(client: LLMClient, result: SectionScriptResult, context: CriticContext) -> tuple[SectionScriptResult, list[CriticResult]]:
    from lecture_auto.production.batch import _hand_edited

    text = {s.slide_number: _extract_all_text(s) for s in context.slides}
    thesis = {s.slide: s.thesis for s in context.intent.slides} if context.intent else {}
    sources: list[CriticSlide] = []
    for s in result.slides:
        edited = _hand_edited(context.work / "scripts" / f"script_{s.slide_number:03d}.json")
        notes = context.work / "vlm" / f"vlm_{s.slide_number:03d}.json"
        sources.append(CriticSlide(
            slide_number=s.slide_number, script=edited["script"] if edited is not None else s.script,
            target_seconds=edited.get("target_seconds", s.target_seconds) if edited is not None else s.target_seconds,
            slide_text=text[s.slide_number], thesis=thesis.get(s.slide_number, ""),
            visual_notes=notes.read_text(encoding="utf-8") if notes.exists() else "",
            previous=text.get(s.slide_number - 1, ""), following=text.get(s.slide_number + 1, ""),
            editable=edited is None,
        ))
    path = context.work / "sections" / f"critic_{result.slides[0].slide_number:03d}.json"
    key = content_hash(
        json.dumps([s.model_dump() for s in sources], ensure_ascii=False, sort_keys=True),
        context.intent.content_hash if context.intent else "",
        context.profile.content_hash if context.profile else "",
        REVIEW_VERSION, REWRITE_VERSION, REVIEW_INSTRUCTION, REWRITE_INSTRUCTION, context.model_key,
    )
    adapter = TypeAdapter(list[CriticResult])
    if is_cache_valid(path, key):
        results = adapter.validate_json(path.read_text(encoding="utf-8"))
    else:
        results = refine_section(client, sources, context.profile.compact() if context.profile else "")
        write_text_atomic(path, adapter.dump_json(results, indent=2).decode())
        write_cache_hash(path, key)
    scripts = {r.slide_number: r.script for r in results}
    return result.model_copy(update={"slides": [
        s.model_copy(update={"script": scripts[s.slide_number]}) for s in result.slides
    ]}), results


def write_report(work: Path, results: list[CriticResult]) -> None:
    report = {
        "lecture_id": work.name,
        "review_version": REVIEW_VERSION, "rewrite_version": REWRITE_VERSION,
        "slides": {str(r.slide_number): r.model_dump(exclude={"script", "slide_number"}) for r in results},
    }
    write_text_atomic(work / "critic_report.json", json.dumps(report, ensure_ascii=False, indent=2))
