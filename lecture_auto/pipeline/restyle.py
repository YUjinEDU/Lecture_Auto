"""S12: content-preserving spoken-register rewrite of already-generated scripts.

script_gen.py / lecture_plan.py write a slide's *content* and *style* in one
LLM call. Asking for spoken-register phrasing (합니다/습니다 down, 그래서/이제
connectors up) in that same call regreses toward written-register Korean --
the model treats "get the facts right" and "sound like the professor" as
competing goals and picks the former. This module is a separate pass, run
only after a script's content is already approved: it takes a slide's
*finished* script text and rewrites phrasing only, verifying afterward that
nothing about the content moved (length, English words, digits).

See docs/hardening/stages/S12_restyle/SPEC.md for the measured baseline and
``pilot_v2.py`` in the same folder for the prompt this module's prompt file
(``lecture_auto/prompts/restyle_instruction.md``) is adapted from.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

from lecture_auto.llm import LLMClient
from lecture_auto.pipeline.lecture_plan import strip_markdown_json_fence

logger = logging.getLogger(__name__)

_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
_DIGIT_RE = re.compile(r"\d+")

# ponytail: sentence-final "~요" detection is a suffix-before-terminal-punctuation
# regex, not a real parser -- good enough for the reporting metric (not gated
# on), upgrade to a proper sentence splitter if the report numbers need to be
# exact. Only "요" (not "죠", which SPEC's baseline table tracks separately as
# its own ~5.4/1000 figure) so this lines up with SPEC's "~요 종결" column.
_YO_ENDING_RE = re.compile(r"요(?=[.!?]|$)")
_JO_ENDING_RE = re.compile(r"죠(?=[.!?]|$)")
_QUESTION_ENDING_RE = re.compile(r"까요(?=[.!?]|$)")
_COMMA_RE = re.compile(r",")

_LENGTH_RATIO_RANGE = (0.95, 1.10)

# Pilot v2's system message, unchanged -- everything else (excerpt, style
# stats, rules, per-slide counts, the scripts to rewrite) is the user message
# built from restyle_instruction.md, in the same order pilot_v2.py used.
_SYSTEM_PROMPT = (
    "당신은 김영국 교수님 본인입니다. 이미 내용이 확정된 강의 대본을 교수님이 실제 강의실에서 "
    "말하는 말투로만 바꿔 씁니다. 내용·순서·사실·예시는 그대로 두고 말투만 바꿉니다."
)


class RestyleResult(BaseModel):
    original: str
    script: str
    kept_original: bool
    reasons: list[str] = Field(default_factory=list)
    metrics_before: dict[str, float]
    metrics_after: dict[str, float]


def compute_metrics(text: str) -> dict[str, float]:
    """합니다/습니다, 그래서+이제, ~요 종결, ~죠 종결, ~까요 종결, 쉼표(AP 호흡) frequency per 1000 characters."""
    n = len(text) or 1
    formal = len(re.findall(r"합니다|습니다", text))
    connector = len(re.findall(r"그래서|이제", text))
    yo_ending = len(_YO_ENDING_RE.findall(text))
    jo_ending = len(_JO_ENDING_RE.findall(text))
    question_ending = len(_QUESTION_ENDING_RE.findall(text))
    comma_count = len(_COMMA_RE.findall(text))
    return {
        "formal_per_1000": round(formal / n * 1000, 2),
        "connector_per_1000": round(connector / n * 1000, 2),
        "yo_ending_per_1000": round(yo_ending / n * 1000, 2),
        "jo_ending_per_1000": round(jo_ending / n * 1000, 2),
        "question_per_1000": round(question_ending / n * 1000, 2),
        "comma_per_1000": round(comma_count / n * 1000, 2),
    }


def _load_instruction() -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / "restyle_instruction.md"
    return path.read_text(encoding="utf-8")


def _counts_line(n: int, script: str) -> str:
    length = len(script)
    connector_min = max(2, round(length * 0.009))
    transition = 1 if length > 400 else 0
    formal_max = max(1, round(length * 0.003))
    return (
        f"- 슬라이드 {n}: '그래서'·'이제'·'그 다음에'·'그러면'으로 문장 잇기 합쳐 최소 "
        f"{connector_min}회, '자,' 화제 전환 {transition}회 이상, '합니다/습니다' 종결 최대 {formal_max}회"
    )


def _build_user_prompt(scripts: dict[int, str], template: str) -> str:
    """Fill ``restyle_instruction.md``'s two placeholders.

    ``str.replace`` (not ``.format``/``string.Template``) because the
    template's own output-format line has literal ``{"slides": ...}`` braces.
    """
    counts = "\n".join(_counts_line(n, s) for n, s in scripts.items())
    slides_json = json.dumps(
        [{"slide_number": n, "script": s} for n, s in scripts.items()],
        ensure_ascii=False, indent=1,
    )
    return template.replace("{{COUNTS}}", counts).replace("{{SLIDES}}", slides_json)


def _request_slides(client: LLMClient, messages: list[dict], temperature: float) -> dict[int, str]:
    """Call the LLM and parse ``{"slides":[...]}``, re-asking once on bad JSON.

    Same one-retry-then-raise shape as lecture_plan.py's section generation.
    """
    for attempt in range(2):
        raw = client.chat(messages, temperature=temperature)
        try:
            data = json.loads(strip_markdown_json_fence(raw))
            return {int(s["slide_number"]): s["script"] for s in data["slides"]}
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            if attempt:
                raise
            logger.warning("Restyle: malformed JSON from LLM -- re-asking once")
    raise AssertionError("unreachable")  # loop above always returns or raises


def _validate(original: str, restyled: str) -> list[str]:
    """Semantic-preservation gates. Empty list means the rewrite is adopted."""
    reasons: list[str] = []
    ratio = len(restyled) / len(original) if original else 1.0
    lo, hi = _LENGTH_RATIO_RANGE
    if not (lo <= ratio <= hi):
        reasons.append(f"글자 수 비율 {ratio:.2f} (허용 {lo}-{hi})")

    latin_orig, latin_new = set(_LATIN_RE.findall(original)), set(_LATIN_RE.findall(restyled))
    if latin_orig != latin_new:
        reasons.append(
            f"라틴 토큰 불일치: 추가={sorted(latin_new - latin_orig)} 누락={sorted(latin_orig - latin_new)}"
        )

    if compute_metrics(restyled)["formal_per_1000"] >= compute_metrics(original)["formal_per_1000"]:
        reasons.append("합니다/습니다 빈도가 원본보다 줄지 않음")

    digits_orig, digits_new = set(_DIGIT_RE.findall(original)), set(_DIGIT_RE.findall(restyled))
    if digits_orig != digits_new:
        reasons.append(
            f"숫자 토큰 불일치: 추가={sorted(digits_new - digits_orig)} 누락={sorted(digits_orig - digits_new)}"
        )
    return reasons


def _messages(scripts: dict[int, str], template: str) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(scripts, template)},
    ]


def _pick(new_scripts: dict[int, str], n: int, original: str) -> tuple[str, list[str]]:
    """The LLM's rewrite for slide n, or the original + a reason if it left slide n out."""
    if n in new_scripts:
        return new_scripts[n], []
    return original, ["LLM 응답에 이 슬라이드 번호가 없음 -- 원본 유지"]


def restyle_scripts(client: LLMClient, scripts: dict[int, str]) -> dict[int, RestyleResult]:
    """Rewrite one section's (several slides') scripts in a single LLM call.

    Every slide's rewrite is validated (``_validate``); slides that fail are
    batched into a single re-request. A slide still failing after that retry
    keeps its original script (``kept_original=True``, with reasons recorded)
    rather than risk silently changing the lecture's content.
    """
    if not scripts:
        return {}

    template = _load_instruction()
    new_scripts = _request_slides(client, _messages(scripts, template), temperature=0.5)

    results: dict[int, RestyleResult] = {}
    failed: dict[int, str] = {}
    for n, original in scripts.items():
        restyled, extra_reasons = _pick(new_scripts, n, original)
        reasons = extra_reasons + _validate(original, restyled)
        if reasons:
            failed[n] = original
        results[n] = RestyleResult(
            original=original,
            script=restyled,
            kept_original=False,
            reasons=reasons,
            metrics_before=compute_metrics(original),
            metrics_after=compute_metrics(restyled),
        )

    if not failed:
        return results

    retried_scripts = _request_slides(client, _messages(failed, template), temperature=0.5)
    for n, original in failed.items():
        restyled, extra_reasons = _pick(retried_scripts, n, original)
        reasons = extra_reasons + _validate(original, restyled)
        if reasons:
            results[n] = RestyleResult(
                original=original,
                script=original,
                kept_original=True,
                reasons=reasons,
                metrics_before=compute_metrics(original),
                metrics_after=compute_metrics(original),
            )
        else:
            results[n] = RestyleResult(
                original=original,
                script=restyled,
                kept_original=False,
                reasons=[],
                metrics_before=compute_metrics(original),
                metrics_after=compute_metrics(restyled),
            )
    return results
