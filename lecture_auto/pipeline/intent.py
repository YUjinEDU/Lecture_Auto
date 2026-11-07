"""One text-model pass over the deck to decide intent and pacing."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from lecture_auto.llm import LLMClient
from lecture_auto.pipeline.cache import content_hash
from lecture_auto.pipeline.script_gen import (
    _extract_all_text,
    _extract_slide_title,
    strip_markdown_json_fence,
)
from lecture_auto.schemas.intent import IntentSheet, SlideIntent, SlideRole
from lecture_auto.schemas.manifest import SlideRecord

ROLES: tuple[SlideRole, ...] = ("도입", "개념", "예시", "비교", "과정", "정리", "전환", "기타")


class IntentDraftInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    lecture_id: str
    name: str
    subject: str
    slides: list[SlideRecord] = Field(min_length=1)
    target_minutes: float = Field(gt=0)
    visual_notes: dict[int, str] = Field(default_factory=dict)


class _DraftSlide(BaseModel):
    slide: int
    thesis: str = ""
    role: str = "기타"
    importance: int = 2
    pitfall: str = ""
    example: str = ""
    seconds: float = Field(default=60, allow_inf_nan=False)


class _Draft(BaseModel):
    slides: list[_DraftSlide]


class IntentBudgetError(ValueError):
    def __init__(self, target: int, minimum: int, maximum: int):
        super().__init__(f"목표 {target}초를 배분할 수 없습니다. 이 자료의 가능 범위: {minimum}~{maximum}초")


def is_cover(slide: SlideRecord) -> bool:
    title = _extract_slide_title(slide).strip()
    return bool(re.search(r"표지|목차|강의\s*소개|오늘의\s*(순서|강의)|agenda|contents", title, re.IGNORECASE))


def build_intent_prompt(source: IntentDraftInput) -> str:
    deck = [
        {"slide": s.slide_number, "title": _extract_slide_title(s),
         "text": _extract_all_text(s), "visual_notes": source.visual_notes.get(s.slide_number, "")}
        for s in source.slides
    ]
    return (
        "대학 강의의 슬라이드 의도 시트를 작성하세요. 슬라이드 글자를 요약하는 대신 "
        "학생이 반드시 이해해야 할 한 문장을 thesis로 정하세요.\n"
        "먼저 문제 제기 -> 핵심 개념 -> 적용 -> 정리의 서사를 파악하고 그 흐름에 맞춰 "
        "각 장의 역할과 중요도(1~3)를 정하세요. 역할은 도입|개념|예시|비교|과정|정리|전환|기타 중 하나입니다.\n"
        "역할과 중요도에 비례해 시간을 배분하세요. 핵심 개념과 적용 사례에 시간을 더 주고, "
        "표지와 목차는 10~30초로 짧게 하세요. 각 장은 10~600초이며 seconds 합계는 "
        f"{round(source.target_minutes * 60)}초(목표 {source.target_minutes}분)의 ±5% 이내여야 합니다.\n"
        "pitfall은 학생이 막히는 지점, example은 사용할 구체 사례나 비유입니다. 없으면 빈 문자열입니다.\n"
        "모든 슬라이드를 정확히 한 번씩 포함하세요. JSON만 출력하세요:\n"
        '{"slides":[{"slide":1,"thesis":"핵심 한 문장","role":"도입","importance":1,'
        '"pitfall":"","example":"","seconds":20}]}\n'
        f"과목: {source.subject}\n강의: {source.name}\n"
        + json.dumps(deck, ensure_ascii=False)
    )


def repair_draft(raw: str, source: IntentDraftInput) -> list[SlideIntent]:
    draft = _Draft.model_validate_json(strip_markdown_json_fence(raw))
    by_number = {}
    for entry in draft.slides:
        by_number.setdefault(entry.slide, entry)
    intents = []
    caps = []
    for slide in source.slides:
        n = slide.slide_number
        entry = by_number.get(n, _DraftSlide(slide=n, thesis=_extract_slide_title(slide)))
        role = next((r for r in ROLES if r == entry.role), "기타")
        cover = is_cover(slide) or (n == 1 and role == "도입")
        cap = 30 if cover else 600
        caps.append(cap)
        intents.append(SlideIntent(
            slide=n, thesis=entry.thesis.strip() or _extract_slide_title(slide),
            role=role, importance=max(1, min(3, entry.importance)),
            pitfall=entry.pitfall, example=entry.example,
            seconds=max(10, min(cap, round(entry.seconds))),
        ))
    target = round(source.target_minutes * 60)
    if not 10 * len(intents) <= target <= sum(caps):
        raise IntentBudgetError(target, 10 * len(intents), sum(caps))
    # Bounded proportional allocation keeps short cover slides short even when
    # the model's total is far from the target.
    weights = [s.seconds for s in intents]
    low, high = 0.0, float(target)
    for _ in range(64):
        scale = (low + high) / 2
        total = sum(max(10, min(cap, w * scale)) for w, cap in zip(weights, caps))
        if total < target:
            low = scale
        else:
            high = scale
    seconds = [max(10, min(cap, int(w * high))) for w, cap in zip(weights, caps)]
    remaining = target - sum(seconds)
    for i, cap in enumerate(caps):
        addition = min(remaining, cap - seconds[i])
        seconds[i] += addition
        remaining -= addition
    return [s.model_copy(update={"seconds": t}) for s, t in zip(intents, seconds)]


def draft_intent(client: LLMClient, source: IntentDraftInput) -> IntentSheet:
    prompt = build_intent_prompt(source)
    raw = client.chat([{"role": "user", "content": prompt}])
    return IntentSheet(
        lecture_id=source.lecture_id, slides=repair_draft(raw, source),
        generated_at=datetime.now(UTC), input_hash=content_hash(prompt),
    )


def intent_lines(sheet: IntentSheet | None, numbers: list[int] | None = None) -> list[str]:
    if sheet is None:
        return []
    entries = [s.model_dump() for s in sheet.slides if numbers is None or s.slide in numbers]
    return [
        "[슬라이드 의도 시트 — 교수자 검토 기준, 시간 배분의 최우선 기준]",
        json.dumps(entries, ensure_ascii=False),
        "섹션은 이 서사를 따르고 minutes는 포함된 슬라이드 seconds 합계/60으로 정할 것.",
        "각 슬라이드의 target_seconds는 의도 시트의 seconds와 같게 할 것.",
        "개념: 질문으로 시작 → 정의 → 구체 예 → 흔한 오해 → 한 줄 정리.",
        "예시: 상황 → 적용 → 앞 개념과 연결. 비교: 비교 기준 → 차이 → 선택 이유.",
        "과정: 순서 → 각 단계의 이유 → 결과. 전환/도입/정리: 짧게, 연결 문장.",
        "슬라이드 글자를 그대로 읽지 말 것. thesis를 전달하고 pitfall과 example을 반영할 것.",
        "",
    ]
