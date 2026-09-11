from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pdfplumber

from lecture_auto.schemas.manifest import SlideRecord
from lecture_auto.demo.jobs import (
    REPO_ROOT,
    DEFAULT_SCRIPT_MODEL,
    DEFAULT_GPT_VLM_MODEL,
    SCRIPT_BATCH_SIZE,
    _add_version_entry,
    _load_job_snapshot,
    _save_job_snapshot,
)
from lecture_auto.demo.control import _check_stop


def _normalize_line(text: str) -> str:
    cleaned = (
        text.replace("\u2022", " ")
        .replace("\uf0b6", " ")
        .replace("", " ")
        .replace("•", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("\t", " ")
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\[Q\]\s*Quiz", "퀴즈", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[T\]\s*TeamWork", "팀 활동", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bQuiz\b", "퀴즈", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bTeamWork\b", "팀 활동", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[([A-Za-z])\]", "", cleaned)
    cleaned = re.sub(r"\s*([,.:;!?])\s*", r"\1 ", cleaned)
    cleaned = re.sub(r"\(\s+", "(", cleaned)
    cleaned = re.sub(r"\s+\)", ")", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|/")
    return cleaned


def _language_char_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z가-힣]", text))


def _hangul_count(text: str) -> int:
    return len(re.findall(r"[가-힣]", text))


def _looks_like_noise(text: str) -> bool:
    cleaned = _normalize_line(text)
    if not cleaned:
        return True
    if re.fullmatch(r"[\d\s./:~()_\-]+", cleaned):
        return True
    if re.fullmatch(r"\(?p\.\d+(?:[-~]\d+)?\)?", cleaned, re.IGNORECASE):
        return True
    if _language_char_count(cleaned) < 2:
        return True
    compact = re.sub(r"\s+", "", cleaned)
    if compact and (_language_char_count(cleaned) / len(compact)) < 0.28:
        return True
    return False


def _score_text_candidate(text: str, *, title_bias: bool) -> int:
    cleaned = _normalize_line(text)
    if not cleaned:
        return -999
    alpha = _language_char_count(cleaned)
    digits = len(re.findall(r"\d", cleaned))
    score = alpha * 3 - digits
    if title_bias:
        score += 8
    if 4 <= len(cleaned) <= 60:
        score += 4
    if _hangul_count(cleaned):
        score += 3
    if re.search(r"[A-Za-z]{2,}", cleaned):
        score += 2
    if _looks_like_noise(cleaned):
        score -= 20
    return score


def _dedupe_preserving_order(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        cleaned = _normalize_line(item)
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen


def _has_legacy_english_vlm_text(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "title area centers on",
        "body content highlights",
        "table-like structures are present",
        "visual image blocks appear",
        "the slide uses a top title",
        "dense text may need verbal chunking",
        "key terms should be defined before examples",
    ]
    return any(marker in lowered for marker in markers)


def _extract_title(slide: SlideRecord) -> str:
    scored: list[tuple[int, str]] = []
    for shape in slide.shapes:
        for para in shape.paragraphs:
            cleaned = _normalize_line(para.full_text)
            if not cleaned:
                continue
            scored.append((_score_text_candidate(cleaned, title_bias=(shape.text_role == "title")), cleaned))

    if scored:
        best_score, best_text = max(scored, key=lambda item: item[0])
        if best_score > 0:
            return best_text

    for shape in slide.shapes:
        for para in shape.paragraphs:
            cleaned = _normalize_line(para.full_text)
            if cleaned:
                return cleaned
    return f"Slide {slide.slide_number}"


def _extract_body_lines(slide: SlideRecord) -> list[str]:
    lines: list[str] = []
    title = _extract_title(slide)
    for shape in slide.shapes:
        for para in shape.paragraphs:
            text = _normalize_line(para.full_text)
            if not text or text == title or _looks_like_noise(text):
                continue
            if text not in lines:
                lines.append(text)
    return _dedupe_preserving_order(lines)[:6]


def _evidence_payload(slide: SlideRecord, note: dict | None, script: dict | None = None) -> dict:
    body_lines = _extract_body_lines(slide)
    return {
        "pdf_text": body_lines,
        "vlm_summary": (note or {}).get("visual_summary", ""),
        "vlm_key_elements": (note or {}).get("key_elements", []),
        "final_script": (script or {}).get("script", ""),
        "hallucination_guard": "슬라이드 PDF 원문과 VLM 요약 범위를 벗어나지 않도록 생성",
    }


def _extract_keywords(*parts: str, limit: int = 5) -> list[str]:
    text = " ".join(parts)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[가-힣]{2,}", text)
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
        if len(seen) >= limit:
            break
    return seen or ["lecture", "slide"]


def _apply_glossary(text: str, glossary: dict[str, str]) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized or not glossary:
        return normalized
    for source, target in sorted(glossary.items(), key=lambda item: len(item[0]), reverse=True):
        source_clean = source.strip()
        target_clean = target.strip()
        if not source_clean or not target_clean:
            continue
        normalized = normalized.replace(source_clean, target_clean)
    return normalized


def _script_sentence_budget(target_seconds: float) -> int:
    if target_seconds <= 12:
        return 3
    if target_seconds <= 20:
        return 4
    return 5


def _script_sentence_guide(target_seconds: float) -> str:
    budget = _script_sentence_budget(target_seconds)
    if budget <= 3:
        return "2~3문장"
    if budget == 4:
        return "3~4문장"
    return "4~5문장"


def _trim_script_to_budget(text: str, target_seconds: float) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return normalized

    budget = _script_sentence_budget(target_seconds)
    max_chars = 140 if budget <= 3 else 220 if budget == 4 else 320
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]
    if parts:
        normalized = " ".join(parts[:budget]).strip()
    if len(normalized) <= max_chars:
        return normalized

    clipped = normalized[:max_chars].rsplit(" ", 1)[0].strip(" ,;")
    if clipped and clipped[-1] not in ".!?":
        clipped += "."
    return clipped or normalized[:max_chars]


def _should_use_fast_tts(manifest) -> bool:
    # Voice clone (Qwen TTS) is always preferred.
    # Set DEMO_FORCE_FAST_TTS=1 to fall back to local TTS for debugging.
    if os.environ.get("DEMO_FORCE_FAST_TTS", "").strip() == "1":
        return True
    return False


def _heuristic_vlm_note(slide: SlideRecord, pdf_path: Path) -> dict:
    title = _extract_title(slide)
    body_lines = _extract_body_lines(slide)
    image_count = sum(1 for shape in slide.shapes if shape.has_image)
    table_count = 0
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            if slide.slide_index < len(pdf.pages):
                tables = pdf.pages[slide.slide_index].extract_tables() or []
                table_count = len(tables)
    except Exception:
        table_count = 0

    summary_bits = [f"이 슬라이드는 '{title}'를 중심 주제로 제시합니다"]
    if body_lines:
        summary_bits.append(f"본문에서는 {body_lines[0]} 내용을 강조합니다")
    if image_count:
        summary_bits.append(f"시각 요소는 이미지 블록 {image_count}개가 배치되어 있습니다")
    if table_count:
        summary_bits.append(f"표 형태의 구조가 {table_count}개 포함되어 있습니다")

    return {
        "visual_summary": ". ".join(summary_bits) + ".",
        "key_elements": body_lines[:4] or [title],
        "layout_relations": "상단 제목 아래에 핵심 설명과 보조 정보가 이어지는 전형적인 강의 슬라이드 구조입니다.",
        "teaching_points": body_lines[:3] or [f"{title}의 핵심 개념을 먼저 정의해야 합니다."],
        "possible_confusions": [
            "핵심 용어의 의미를 먼저 분명하게 짚어야 합니다.",
            "예시와 개념 설명의 순서를 분리하면 이해가 쉬워집니다.",
        ],
        "source": "heuristic_fallback",
    }


def _normalize_vlm_payload(payload: dict, slide: SlideRecord, pdf_path: Path) -> dict:
    fallback = _heuristic_vlm_note(slide, pdf_path)

    visual_summary = payload.get("visual_summary")
    if not isinstance(visual_summary, str) or not visual_summary.strip():
        visual_summary = fallback["visual_summary"]
    else:
        visual_summary = _normalize_line(visual_summary)
        if _has_legacy_english_vlm_text(visual_summary):
            visual_summary = fallback["visual_summary"]
        elif _hangul_count(fallback["visual_summary"]) >= 4 and _hangul_count(visual_summary) < 2:
            visual_summary = fallback["visual_summary"]

    def _normalize_list(value: object, *, fallback_items: list[str]) -> list[str]:
        if isinstance(value, list):
            items: list[str] = []
            for entry in value:
                if isinstance(entry, str) and entry.strip():
                    items.append(entry.strip())
                elif isinstance(entry, dict):
                    candidate = next(
                        (
                            str(v).strip()
                            for v in entry.values()
                            if isinstance(v, str) and str(v).strip()
                        ),
                        "",
                    )
                    if candidate:
                        items.append(_normalize_line(candidate))
            items = [item for item in items if item and not _looks_like_noise(item)]
            if fallback_items and _has_legacy_english_vlm_text(" ".join(items)):
                return fallback_items
            if fallback_items and _hangul_count(" ".join(fallback_items)) >= 4 and _hangul_count(" ".join(items)) < 2:
                return fallback_items
            return items[:5] or fallback_items
        if isinstance(value, str) and value.strip():
            cleaned = _normalize_line(value)
            if cleaned and not _looks_like_noise(cleaned):
                if fallback_items and _has_legacy_english_vlm_text(cleaned):
                    return fallback_items
                if fallback_items and _hangul_count(" ".join(fallback_items)) >= 4 and _hangul_count(cleaned) < 2:
                    return fallback_items
                return [cleaned]
        return fallback_items

    layout_relations = payload.get("layout_relations")
    if not isinstance(layout_relations, str) or not layout_relations.strip():
        layout_relations = fallback["layout_relations"]
    else:
        layout_relations = _normalize_line(layout_relations)
        if _has_legacy_english_vlm_text(layout_relations):
            layout_relations = fallback["layout_relations"]
        elif _hangul_count(fallback["layout_relations"]) >= 4 and _hangul_count(layout_relations) < 2:
            layout_relations = fallback["layout_relations"]

    possible_confusions = _normalize_list(
        payload.get("possible_confusions"),
        fallback_items=fallback["possible_confusions"],
    )
    key_elements = _normalize_list(
        payload.get("key_elements"),
        fallback_items=fallback["key_elements"],
    )
    teaching_points = _normalize_list(
        payload.get("teaching_points"),
        fallback_items=fallback["teaching_points"],
    )

    return {
        "visual_summary": visual_summary,
        "key_elements": key_elements,
        "layout_relations": layout_relations,
        "teaching_points": teaching_points,
        "possible_confusions": possible_confusions,
        "source": payload.get("source", "local_vlm"),
    }


def _read_llm_api_key() -> str | None:
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return os.environ["OPENAI_API_KEY"].strip()
    api_path = REPO_ROOT / "api.txt"
    if api_path.exists():
        lines = [line.strip() for line in api_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for value in lines:
            lowered = value.lower()
            if lowered in {"openai", "api_key", "key"}:
                continue
            if value.startswith("sk-") and not value.startswith("sk-or-"):
                return value
    return None


def _run_gpt_vlm(slide: SlideRecord, image_path: Path, pdf_path: Path) -> dict:
    """Analyze a slide image via the unified LLM client. Falls back to heuristic on error."""
    api_key = _read_llm_api_key()
    if not api_key:
        return _heuristic_vlm_note(slide, pdf_path)

    model_id = os.environ.get("DEMO_VLM_MODEL", DEFAULT_GPT_VLM_MODEL)
    title = _extract_title(slide)
    body_text = "\n".join(_extract_body_lines(slide)[:8])
    prompt = (
        "이 강의 슬라이드를 분석하고 반드시 한국어로만 아래 JSON 형식으로 응답하라. "
        "JSON 외에 다른 텍스트는 절대 출력하지 말라.\n"
        "{\n"
        '  "visual_summary": "슬라이드 전체 내용 2-3문장 요약",\n'
        '  "key_elements": ["핵심 개념 또는 용어 목록"],\n'
        '  "layout_relations": "시각 요소 간 배치와 관계 설명",\n'
        '  "teaching_points": ["강의에서 강조할 교육 포인트"],\n'
        '  "possible_confusions": ["학생이 헷갈릴 수 있는 부분"]\n'
        "}\n\n"
        f"슬라이드 파싱 텍스트:\n제목: {title}\n본문:\n{body_text}"
    )

    try:
        from lecture_auto.llm.openai_client import OpenAILLMClient

        client = OpenAILLMClient(api_key=api_key, vlm_model=model_id)
        text = client.analyze_image(
            image_path, prompt, temperature=0.1, max_tokens=500
        ).strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            payload = json.loads(match.group(0))
            payload["source"] = "gpt_vlm"
            return _normalize_vlm_payload(payload, slide, pdf_path)
    except Exception:
        pass

    fallback = _heuristic_vlm_note(slide, pdf_path)
    fallback["source"] = "heuristic_fallback"
    return fallback


def _compose_script(
    slide: SlideRecord,
    note: dict,
    next_title: str | None,
    target_seconds: float,
) -> dict:
    title = _normalize_line(_extract_title(slide))
    body_lines = _extract_body_lines(slide)
    summary = _normalize_line(str(note.get("visual_summary", "")).strip())
    if _has_legacy_english_vlm_text(summary):
        summary = ""
    teaching_points = _dedupe_preserving_order([str(item) for item in (note.get("teaching_points") or []) if str(item).strip()])

    lead_sentence = f"이번 슬라이드에서는 {title} 내용을 설명하겠습니다."
    if _looks_like_noise(title) and body_lines:
        lead_sentence = f"이번 슬라이드에서는 {body_lines[0]} 내용을 중심으로 설명하겠습니다."

    sentence_budget = _script_sentence_budget(target_seconds)
    middle_sentences: list[str] = []
    if summary and not _looks_like_noise(summary):
        middle_sentences.append(summary if summary.endswith(".") else f"{summary}.")
    if body_lines:
        lead = ", ".join(body_lines[:2] if sentence_budget <= 3 else body_lines[:3])
        middle_sentences.append(f"핵심 포인트는 {lead}입니다.")
    if teaching_points:
        middle_sentences.append(f"특히 {teaching_points[0]}의 의미와 맥락을 함께 짚겠습니다.")
    if next_title:
        transition = f"다음 슬라이드에서는 {next_title}로 자연스럽게 이어가겠습니다."
    else:
        transition = "이 슬라이드 설명을 마치고 전체 내용을 정리하겠습니다."
    middle_keep = max(1, sentence_budget - 2)
    sentences = [lead_sentence, *middle_sentences[:middle_keep], transition]

    script = _trim_script_to_budget(" ".join(_dedupe_preserving_order(sentences)), target_seconds)
    keywords = _extract_keywords(title, *body_lines, *teaching_points)
    tts_text = re.sub(r"\s+", " ", script).strip()
    if len(tts_text) < 12:
        tts_text = f"{title}를 설명합니다."

    return {
        "slide_index": slide.slide_index,
        "slide_number": slide.slide_number,
        "target_seconds": round(target_seconds, 1),
        "script": script,
        "keywords": keywords,
        "transition_to_next": transition,
        "edited": False,
        "edited_at": None,
        "tts_text": tts_text,
    }


def _build_script_slide_payloads(
    manifest,
    notes: list[dict],
    target_seconds: float,
    settings: dict | None = None,
) -> list[dict]:
    settings = settings or {}
    slide_payloads = []
    for idx, slide in enumerate(manifest.slides, start=1):
        next_title = _extract_title(manifest.slides[idx]) if idx < len(manifest.slides) else None
        slide_payloads.append(
            {
                "slide_number": slide.slide_number,
                "slide_title": _extract_title(slide),
                "body_lines": _extract_body_lines(slide)[:6],
                "vlm_note": notes[idx - 1],
                "target_seconds": round(target_seconds, 1),
                "next_slide_title": next_title,
                "audience": settings.get("audience", "학부 전공"),
                "explanation_style": settings.get("explanation_style", "개념 중심"),
                "lecture_density": settings.get("lecture_density", "표준형"),
                "learner_profile": settings.get("learner_profile", ""),
                "delivery_notes": settings.get("delivery_notes", ""),
            }
        )
    return slide_payloads


def _call_script_model_batch(
    slide_payloads: list[dict],
    target_seconds: float,
    settings: dict | None = None,
) -> dict[int, str]:
    settings = settings or {}
    api_key = _read_llm_api_key()
    if not api_key:
        raise RuntimeError("OpenAI API key not found. Put an OpenAI key in api.txt or OPENAI_API_KEY.")

    from lecture_auto.llm.openai_client import OpenAILLMClient

    client = OpenAILLMClient(api_key=api_key)
    request_kwargs = {
        "model": os.environ.get("DEMO_SCRIPT_MODEL", DEFAULT_SCRIPT_MODEL),
        "temperature": 0.3,
        "messages": [
            {
                "role": "system",
                "content": (
                    "## 역할\n"
                    "너는 지금 강의실 앞에 서서 학생들에게 직접 강의하고 있는 대학 교수다. "
                    "뒤에는 슬라이드가 투영되어 있고, 앞에는 수강생들이 앉아 있다. "
                    "너의 목소리로, 너의 말투로, 지금 이 순간 강의를 진행하라.\n\n"

                    "## 화자 원칙\n"
                    "- 항상 1인칭 구어체: '~입니다', '~겠습니다', '~봅시다', '~중요합니다'\n"
                    "- 학생들에게 직접 말하는 자연스러운 강의 말투\n"
                    "- 슬라이드를 보면서 설명하되, 슬라이드를 '소개'하거나 '안내'하는 사람이 되지 말 것\n\n"

                    "## 절대 금지 패턴 (아래 패턴이 한 문장이라도 있으면 실패)\n"
                    "✗ '이 슬라이드는 X를 다룹니다/정의합니다/보여줍니다/소개합니다'\n"
                    "✗ '이번 슬라이드에서는 X 내용을 설명하겠습니다' (슬라이드 메타 서술)\n"
                    "✗ '발표자는 Y를 강조합니다' / '교수는 Z를 설명합니다' (3인칭)\n"
                    "✗ 불릿포인트 내용을 그대로 나열해서 읽기\n"
                    "✗ 슬라이드에 없는 사실·예시·배경지식 임의 추가\n\n"

                    "## 올바른 어조 예시\n"
                    "✓ '자, 이 개념에서 제가 강조하고 싶은 건 바로 이겁니다. X는 단순히 Y가 아니라...'\n"
                    "✓ '여기서 핵심을 짚어볼까요. 왜 Z가 중요하냐면...'\n"
                    "✓ '학생들이 이 부분을 자주 헷갈려 하는데, 핵심은 이렇습니다...'\n"
                    "✓ '지금까지 X를 살펴봤으니, 이제 그게 실제로 어떻게 작동하는지 보겠습니다.'\n\n"

                    "## 출력 규칙\n"
                    "반드시 JSON만 반환. 다른 텍스트 일절 금지.\n"
                    "{\"slides\": [{\"slide_number\": 1, \"script\": \"...\"}]}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"지금 강의 중입니다. 아래 각 슬라이드에 대해 교수 본인의 목소리로 강의 대본을 작성하세요.\n\n"

                    f"## 강의 컨텍스트\n"
                    f"- 수강 대상: {settings.get('audience', '학부 전공')}\n"
                    f"- 설명 스타일: {settings.get('explanation_style', '개념 중심')}\n"
                    f"- 강의 밀도: {settings.get('lecture_density', '표준형')} "
                    f"({'핵심만 간결하게' if '요약' in settings.get('lecture_density','') else '자세하고 풍부하게' if '자세' in settings.get('lecture_density','') else '균형 있게 설명'})\n"
                    + (f"- 학생 특성 (이에 맞게 말투와 깊이 조절): {settings.get('learner_profile','').strip()}\n"
                       if settings.get('learner_profile','').strip() else "")
                    + (f"- 교수 전달 스타일 (이 지시를 우선 반영): {settings.get('delivery_notes','').strip()}\n"
                       if settings.get('delivery_notes','').strip() else "")
                    + f"\n## 슬라이드별 제약\n"
                    f"- 목표 발화 시간: 슬라이드당 약 {round(target_seconds)}초 "
                    f"({_script_sentence_guide(target_seconds)})\n"
                    f"- body_lines: PDF 원문 텍스트 — 내용 충실도 최우선\n"
                    f"- vlm_note: 화면 구조·강조 포인트 참고 (보조 정보)\n"
                    f"- 마지막 문장: next_slide_title가 있으면 자연스럽게 연결, 없으면 마무리\n\n"

                    f"## 슬라이드 데이터\n"
                    f"{json.dumps({'slides': slide_payloads}, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
    }
    content: str | None = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            content = client.chat(
                request_kwargs["messages"],
                model=request_kwargs["model"],
                temperature=request_kwargs["temperature"],
            )
            break
        except Exception as exc:
            last_error = exc
            if "429" not in str(exc):
                raise
            if attempt < 2:
                time.sleep(2 * (attempt + 1))

    if content is None:
        raise last_error or RuntimeError("OpenAI script generation failed.")
    content = content or ""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        payload = json.loads(match.group(0))
        slides_payload = payload.get("slides") or []
    else:
        raise RuntimeError("OpenAI response did not contain JSON.")

    if not isinstance(slides_payload, list):
        raise RuntimeError("OpenAI response did not contain a slide list.")

    results: dict[int, str] = {}
    for item in slides_payload:
        if not isinstance(item, dict):
            continue
        try:
            slide_number = int(item.get("slide_number"))
        except Exception:
            continue
        script = _normalize_line(str(item.get("script", "")).strip())
        if _hangul_count(script) >= 10:
            results[slide_number] = _trim_script_to_budget(script, target_seconds)

    if not results:
        raise RuntimeError("Generated scripts were not sufficiently Korean.")
    return results
