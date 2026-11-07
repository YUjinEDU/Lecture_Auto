"""Independent final-script review, overlap metrics, and seeded blind forms."""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import TypedDict

from pydantic import ValidationError

from lecture_auto.llm import LLMClient
from lecture_auto.pipeline.cache import write_text_atomic
from lecture_auto.pipeline.critic import CriticSlide, Review, review_section
from lecture_auto.pipeline.script_gen import (
    SPEECH_CHARS_PER_SECOND,
    _extract_all_text,
    _extract_slide_title,
)
from lecture_auto.production.intent import load_intent
from lecture_auto.schemas.lecture_plan import LecturePlan, SectionSlideScript
from lecture_auto.schemas.manifest import SlideRecord


class VariantMetrics(TypedDict):
    slide_count: int
    verbatim_recitation_ratio: float
    concrete_example_share: float
    delivers_thesis_share: float
    estimated_duration_seconds: float
    target_seconds: float
    duration_vs_target: float
    slides_rewritten: int
    review_wall_seconds: float


class EvaluationMetrics(TypedDict):
    A: VariantMetrics
    B: VariantMetrics
    definitions: dict[str, str | int]
    wall_times: dict[str, float | None]


def verbatim_ratio(script: str, slide_text: str, n: int = 8) -> float:
    """Fraction of script character n-gram occurrences also present in slide text."""
    script, slide_text = [re.sub(r"\s+", "", t).lower() for t in (script, slide_text)]
    grams = {slide_text[i:i + n] for i in range(max(0, len(slide_text) - n + 1))}
    windows = [script[i:i + n] for i in range(max(0, len(script) - n + 1))]
    return sum(g in grams for g in windows) / len(windows) if windows else 0.0


def load_scripts(folder: Path) -> dict[int, SectionSlideScript]:
    scripts = [SectionSlideScript.model_validate_json(p.read_text()) for p in sorted(folder.glob("script_*.json"))]
    return {s.slide_number: s for s in scripts}


def evaluation_review(client: LLMClient, sources: list[CriticSlide]) -> Review:
    """Evaluation may re-ask malformed JSON; the production critic never retries."""
    try:
        return review_section(client, sources)
    except ValidationError:
        return review_section(client, sources)


def evaluate(client: LLMClient, root: Path, slides: list[SlideRecord]) -> EvaluationMetrics:
    work = root / "data/work_batch/91_gemini_test"
    intent = load_intent(work)
    assert intent is not None
    plan = LecturePlan.model_validate_json((work / "lecture_plan.json").read_text())
    a, b = load_scripts(root / "baseline_scripts"), load_scripts(work / "scripts")
    assert set(a) == set(b) == {s.slide_number for s in slides}
    target = sum(s.seconds for s in intent.slides)
    theses = {s.slide: s.thesis for s in intent.slides}
    text = {s.slide_number: _extract_all_text(s) for s in slides}
    report = json.loads((work / "critic_report.json").read_text())
    variants: dict[str, VariantMetrics] = {}
    for name, scripts in (("A", a), ("B", b)):
        start = time.monotonic()
        scores = []
        for section in plan.sections:
            sources = [CriticSlide(
                slide_number=n, script=scripts[n].script, target_seconds=scripts[n].target_seconds,
                slide_text=text[n], thesis=theses[n], previous=text.get(n - 1, ""), following=text.get(n + 1, ""),
            ) for n in section.slides]
            scores.extend(evaluation_review(client, sources).slides)
        write_text_atomic(root / f"final_review_{name}.json",
                          json.dumps([s.model_dump() for s in scores], ensure_ascii=False, indent=2))
        duration = sum(len(s.script) for s in scripts.values()) / SPEECH_CHARS_PER_SECOND
        variants[name] = VariantMetrics(
            slide_count=len(scripts),
            verbatim_recitation_ratio=sum(verbatim_ratio(s.script, text[n]) for n, s in scripts.items()) / len(scripts),
            concrete_example_share=sum(s.has_concrete_example for s in scores) / len(scores),
            delivers_thesis_share=sum(s.delivers_thesis for s in scores) / len(scores),
            estimated_duration_seconds=duration, target_seconds=target, duration_vs_target=duration / target,
            slides_rewritten=sum(s["rewritten"] for s in report["slides"].values()) if name == "B" else 0,
            review_wall_seconds=time.monotonic() - start,
        )
    rng = random.Random(20261107)
    selected = sorted({2, 3, 1, len(slides) // 2, len(slides) * 3 // 4, len(slides)})
    key = {"seed": 20261107, "slides": {}}
    lines = ["# 강의 대본 블라인드 비교", "", "각 버전을 읽고 1점(낮음)~5점(높음)으로 평가해 주세요.", ""]
    for n in selected:
        slide = next(s for s in slides if s.slide_number == n)
        labels = ["A", "B"]
        rng.shuffle(labels)
        key["slides"][str(n)] = {"version_1": labels[0], "version_2": labels[1]}
        lines.extend([f"## 슬라이드 {n}: {_extract_slide_title(slide)}", "",
                      f"자료 요약: {text[n][:800]}", ""])
        for number, variant in enumerate(labels, 1):
            lines.extend([f"### 버전 {number}", "", (a if variant == "A" else b)[n].script, ""])
        lines.extend(["| 평가 항목 | 버전 1 (1~5) | 버전 2 (1~5) |",
                      "|---|---|---|", "| 이해 쉬움 | | |", "| 교수님다움 | | |",
                      "| 정확성 | | |", "| 지루하지 않음 | | |", "", "의견: ", ""])
    write_text_atomic(root / "blind_ab.md", "\n".join(lines))
    write_text_atomic(root / "blind_ab_key.json", json.dumps(key, ensure_ascii=False, indent=2))
    return EvaluationMetrics(A=variants["A"], B=variants["B"], definitions={
        "overlap_ngram_characters": 8, "overlap_normalization": "lowercase, remove whitespace; macro average",
        "quality_scores": "independent post-generation LLM review on all final scripts; same B intent for A and B",
        "duration": f"script characters / {SPEECH_CHARS_PER_SECOND}; no TTS performed",
        "baseline_wall_time": "existing scripts copied; original generation wall time unavailable",
        "rewrite_count": "critic acceptance only; B generation itself is separate",
    }, wall_times={})
