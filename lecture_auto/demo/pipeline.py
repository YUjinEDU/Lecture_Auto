from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pdfplumber

from lecture_auto.demo.state import (
    append_event,
    append_version,
    create_job,
    get_job,
    mark_failed,
    mark_stopped,
    set_artifact,
    update_stage,
    update_metadata,
    upsert_slide,
)
from lecture_auto.pipeline.parser_pdf import parse_pdf
from lecture_auto.pipeline.renderer import pdf_to_pngs
from lecture_auto.pipeline.tts import (
    load_tts as load_qwen_tts,
    merge_audio,
    synthesize_slide as synthesize_qwen_slide,
)
from lecture_auto.pipeline.video import assemble_video
from lecture_auto.schemas.manifest import LectureStyle, SlideManifest, SlideRecord
from lecture_auto.storage.jobs import JobPaths


REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_ROOT = REPO_ROOT / "data" / "demo_jobs"
DEFAULT_SCRIPT_MODEL = "gpt-5.4-mini"
DEFAULT_GPT_VLM_MODEL = "gpt-5.4-mini"
DEFAULT_TTS_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
SCRIPT_BATCH_SIZE = 8
DEMO_FAST_TTS_SLIDE_LIMIT = 18
SCRIPT_PROMPT_VERSION = "demo-v3"
PIPELINE_SCHEMA_VERSION = "demo-saas-v1"
_TTS_LOCK = threading.Lock()
_STOP_FLAGS: dict[str, threading.Event] = {}
_QWEN_TTS_MODEL = None
_LOCAL_TTS_MODEL = None
_LOCAL_TTS_TOKENIZER = None


def _job_snapshot_path(job_id: str) -> Path:
    return get_demo_job_paths(job_id).job_dir / "job_state.json"


def _default_job_settings(
    *,
    target_minutes: int,
    audience: str = "학부 전공",
    explanation_style: str = "개념 중심",
    lecture_density: str = "표준형",
    learner_profile: str = "",
    delivery_notes: str = "",
    use_vlm: bool = True,
) -> dict:
    return {
        "target_minutes": max(1, target_minutes),
        "audience": audience or "학부 전공",
        "explanation_style": explanation_style or "개념 중심",
        "lecture_density": lecture_density or "표준형",
        "learner_profile": learner_profile.strip(),
        "delivery_notes": delivery_notes.strip(),
        "use_vlm": bool(use_vlm),
    }


def _base_pipeline_meta() -> dict:
    return {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "prompt_version": SCRIPT_PROMPT_VERSION,
        "llm_model": os.environ.get("DEMO_SCRIPT_MODEL", DEFAULT_SCRIPT_MODEL),
        "vlm_model": os.environ.get("DEMO_VLM_MODEL", "Qwen/Qwen3-VL-4B-Instruct"),
        "tts_model": os.environ.get("DEMO_QWEN_TTS_MODEL", DEFAULT_TTS_MODEL),
        "tts_mode": "clone",
        "seed_mode": "temperature_0.2",
    }


def _base_library(filename: str, lecture_name: str) -> dict:
    return {
        "folder": Path(filename).stem,
        "collection": "최근 강의",
        "display_name": lecture_name,
        "artifact_tree": [],
    }


def _save_job_snapshot(job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        return
    snapshot_path = _job_snapshot_path(job_id)
    snapshot_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_job_snapshot(job_id: str) -> dict | None:
    snapshot_path = _job_snapshot_path(job_id)
    if not snapshot_path.exists():
        return None
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def _refresh_library_artifacts(job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        return
    artifact_tree = []
    if job["filename"]:
        artifact_tree.append({"kind": "pdf", "label": job["filename"]})
    artifact_tree.extend(
        [
            {"kind": "rendered", "label": "rendered/ slide previews"},
            {"kind": "script", "label": "scripts/ slide scripts"},
            {"kind": "audio", "label": "audio/ per-slide wav"},
            {"kind": "video", "label": "artifacts/ lecture mp4"},
        ]
    )
    library = job.get("library") or _base_library(job["filename"], job["lecture_name"])
    library["artifact_tree"] = artifact_tree
    update_metadata(job_id, library=library)
    _save_job_snapshot(job_id)


def _add_version_entry(job_id: str, *, kind: str, summary: str, slide_number: int | None = None, payload: dict | None = None) -> None:
    append_version(
        job_id,
        {
            "version_id": uuid.uuid4().hex[:8],
            "time": datetime.now(UTC).isoformat(),
            "kind": kind,
            "slide_number": slide_number,
            "summary": summary,
            "payload": payload or {},
        },
    )
    _save_job_snapshot(job_id)


def create_demo_job(filename: str, lecture_name: str, target_minutes: int, *, settings: dict | None = None) -> dict:
    job_id = uuid.uuid4().hex[:10]
    merged_settings = _default_job_settings(target_minutes=target_minutes, **(settings or {}))
    job = create_job(
        job_id,
        filename,
        lecture_name,
        target_minutes,
        settings=merged_settings,
        glossary={},
        version_history=[],
        pipeline_meta=_base_pipeline_meta(),
        library=_base_library(filename, lecture_name),
    )
    _save_job_snapshot(job_id)
    return job


def get_demo_job_paths(job_id: str) -> JobPaths:
    return JobPaths(job_id, root=DEMO_ROOT).ensure_dirs()


def save_uploaded_pdf(job_id: str, filename: str, content: bytes) -> Path:
    job_paths = get_demo_job_paths(job_id)
    safe_name = Path(filename).name or "lecture.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{Path(safe_name).stem}.pdf"
    target = job_paths.input_dir / safe_name
    target.write_bytes(content)
    return target


def save_voice_reference(job_id: str, filename: str, content: bytes) -> Path:
    job_paths = get_demo_job_paths(job_id)
    ext = Path(filename).suffix.lower() or ".webm"
    source_path = job_paths.input_dir / f"voice_reference{ext}"
    source_path.write_bytes(content)

    wav_path = job_paths.input_dir / "voice_reference.wav"
    if ext != ".wav":
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-ar",
                "24000",
                "-ac",
                "1",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            wav_path = source_path
    else:
        wav_path = source_path

    update_metadata(job_id, voice_reference_name=Path(filename).name)
    append_event(job_id, "tts", f"Voice reference saved: {Path(filename).name}")
    _save_job_snapshot(job_id)
    return wav_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_line(text: str) -> str:
    cleaned = (
        text.replace("\u2022", " ")
        .replace("\uf0b6", " ")
        .replace("", " ")
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


def _should_use_fast_tts(manifest: SlideManifest) -> bool:
    # Voice clone (Qwen TTS) is always preferred.
    # Set DEMO_FORCE_FAST_TTS=1 to fall back to local TTS for debugging.
    if os.environ.get("DEMO_FORCE_FAST_TTS", "").strip() == "1":
        return True
    return False


def _get_stop_flag(job_id: str) -> threading.Event:
    if job_id not in _STOP_FLAGS:
        _STOP_FLAGS[job_id] = threading.Event()
    return _STOP_FLAGS[job_id]


def request_stop(job_id: str) -> None:
    """Signal a running pipeline to stop at the next checkpoint."""
    _get_stop_flag(job_id).set()
    update_metadata(job_id, status="stopping")
    append_event(job_id, "pipeline", "사용자가 중지를 요청했습니다. 현재 단계 완료 후 중지됩니다.")


def _clear_stop_flag(job_id: str) -> None:
    _STOP_FLAGS.pop(job_id, None)


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


def _run_gpt_vlm(slide: SlideRecord, image_path: Path, pdf_path: Path) -> dict:
    """Analyze a slide image using GPT-4o vision. Falls back to heuristic on error."""
    import base64

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
        from openai import OpenAI

        image_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model_id,
            temperature=0.1,
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "low"}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        text = response.choices[0].message.content.strip()
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


def _build_script_slide_payloads(
    manifest: SlideManifest,
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

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
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
    response = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(**request_kwargs)
            break
        except Exception as exc:
            last_error = exc
            if "429" not in str(exc):
                raise
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    if response is None:
        raise last_error or RuntimeError("OpenAI script generation failed.")
    content = response.choices[0].message.content or ""
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


def _get_local_tts():
    global _LOCAL_TTS_MODEL, _LOCAL_TTS_TOKENIZER
    if _LOCAL_TTS_MODEL is not None and _LOCAL_TTS_TOKENIZER is not None:
        return _LOCAL_TTS_MODEL, _LOCAL_TTS_TOKENIZER

    with _TTS_LOCK:
        if _LOCAL_TTS_MODEL is not None and _LOCAL_TTS_TOKENIZER is not None:
            return _LOCAL_TTS_MODEL, _LOCAL_TTS_TOKENIZER

        import torch
        from transformers import AutoTokenizer, VitsModel

        model_id = os.environ.get("DEMO_TTS_MODEL", "facebook/mms-tts-kor")
        _LOCAL_TTS_TOKENIZER = AutoTokenizer.from_pretrained(model_id)
        _LOCAL_TTS_MODEL = VitsModel.from_pretrained(model_id)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _LOCAL_TTS_MODEL = _LOCAL_TTS_MODEL.to(device)
        _LOCAL_TTS_MODEL.eval()
        return _LOCAL_TTS_MODEL, _LOCAL_TTS_TOKENIZER


def _get_qwen_tts():
    global _QWEN_TTS_MODEL
    if _QWEN_TTS_MODEL is not None:
        return _QWEN_TTS_MODEL

    with _TTS_LOCK:
        if _QWEN_TTS_MODEL is not None:
            return _QWEN_TTS_MODEL
        _QWEN_TTS_MODEL = load_qwen_tts(os.environ.get("DEMO_QWEN_TTS_MODEL", DEFAULT_TTS_MODEL))
        return _QWEN_TTS_MODEL


def _split_tts_segments(text: str, limit: int = 180) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    parts = re.split(r"(?<=[.!?])\s+|(?<=[다요죠])\s+", normalized)
    segments: list[str] = []
    current = ""
    for part in parts:
        chunk = part.strip()
        if not chunk:
            continue
        candidate = f"{current} {chunk}".strip()
        if current and len(candidate) > limit:
            segments.append(current)
            current = chunk
        else:
            current = candidate
    if current:
        segments.append(current)
    return segments or [normalized]


def _synthesize_with_flite_fallback(text: str, output_path: Path) -> None:
    safe = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"flite=text='{safe}':voice=slt",
        "-ar",
        "24000",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg flite synthesis failed")


def _synthesize_with_local_korean_fallback(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import numpy as np
        import soundfile as sf
        import torch

        model, tokenizer = _get_local_tts()
        device = next(model.parameters()).device
        sample_rate = int(getattr(model.config, "sampling_rate", 16000))
        segments = _split_tts_segments(text)
        waves: list[np.ndarray] = []

        for segment in segments:
            inputs = tokenizer(segment, return_tensors="pt")
            inputs = {key: value.to(device) for key, value in inputs.items()}
            with torch.no_grad():
                waveform = model(**inputs).waveform[0].detach().cpu().numpy()
            waves.append(waveform.astype("float32"))
            waves.append(np.zeros(int(sample_rate * 0.12), dtype="float32"))

        merged = np.concatenate(waves[:-1] if len(waves) > 1 else waves)
        sf.write(str(output_path), merged, sample_rate)
    except Exception:
        _synthesize_with_flite_fallback(text, output_path)


def _get_default_voice_reference_path() -> Path | None:
    shared_dir = DEMO_ROOT / "_shared"
    shared_dir.mkdir(parents=True, exist_ok=True)

    for candidate in (
        REPO_ROOT / "박유진음성.wav",
        REPO_ROOT / "박유진음성.m4a",
    ):
        if not candidate.exists():
            continue
        if candidate.suffix.lower() == ".wav":
            return candidate

        wav_path = shared_dir / "park_yujin_default.wav"
        if wav_path.exists() and wav_path.stat().st_mtime >= candidate.stat().st_mtime:
            return wav_path
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(candidate),
                "-ar",
                "24000",
                "-ac",
                "1",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and wav_path.exists():
            return wav_path
    return None


def _resolve_voice_reference(job_id: str) -> tuple[Path | None, str | None]:
    job_paths = get_demo_job_paths(job_id)
    job = get_job(job_id) or {}
    for candidate in (
        job_paths.input_dir / "voice_reference.wav",
        job_paths.input_dir / "voice_reference.webm",
    ):
        if candidate.exists():
            return candidate, Path(job.get("voice_reference_name") or candidate.name).name

    default_ref = _get_default_voice_reference_path()
    if default_ref is not None:
        return default_ref, "박유진음성.m4a (기본)"
    return None, None


def _synthesize_demo_tts(text: str, output_path: Path, voice_reference: Path | None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        model = _get_qwen_tts()
        synthesize_qwen_slide(model, text, output_path, voice_ref_path=voice_reference)
        return
    except Exception:
        _synthesize_with_local_korean_fallback(text, output_path)


def _input_pdf_path(job_paths: JobPaths) -> Path | None:
    pdf_files = sorted(job_paths.input_dir.glob("*.pdf"))
    return pdf_files[0] if pdf_files else None


def _load_saved_notes(job_paths: JobPaths, manifest: SlideManifest) -> list[dict]:
    notes: list[dict] = []
    pdf_path = _input_pdf_path(job_paths)
    for slide in manifest.slides:
        slide_number = slide.slide_number
        note_path = job_paths.vlm_dir / f"vlm_note_{slide_number:03d}.json"
        if note_path.exists():
            loaded = json.loads(note_path.read_text(encoding="utf-8"))
            if pdf_path is not None:
                loaded = _normalize_vlm_payload(loaded, slide, pdf_path)
                note_path.write_text(json.dumps(loaded, ensure_ascii=False, indent=2), encoding="utf-8")
            notes.append(loaded)
        else:
            notes.append({})
    return notes


def _render_script_stage(job_id: str, manifest: SlideManifest, notes: list[dict]) -> list[dict]:
    job_paths = get_demo_job_paths(job_id)
    job = get_job(job_id) or {}
    settings = job.get("settings") or {}
    target_seconds = (manifest.target_minutes * 60) / max(1, manifest.slide_count)
    scripts: list[dict] = []
    generated_scripts: dict[int, str] = {}

    slide_payloads = _build_script_slide_payloads(manifest, notes, target_seconds, settings)
    try:
        total_batches = max(1, (len(slide_payloads) + SCRIPT_BATCH_SIZE - 1) // SCRIPT_BATCH_SIZE)
        for batch_index, start in enumerate(range(0, len(slide_payloads), SCRIPT_BATCH_SIZE), start=1):
            chunk = slide_payloads[start:start + SCRIPT_BATCH_SIZE]
            generated_scripts.update(_call_script_model_batch(chunk, target_seconds, settings))
            append_event(
                job_id,
                "script",
                f"LLM 스크립트 배치 생성 완료 {batch_index}/{total_batches}",
            )
    except Exception as exc:
        append_event(job_id, "script", f"LLM batch script fallback used: {exc}")

    for idx, slide in enumerate(manifest.slides, start=1):
        next_title = _extract_title(manifest.slides[idx]) if idx < len(manifest.slides) else None
        fallback_script = _compose_script(slide, notes[idx - 1], next_title, target_seconds)
        script = fallback_script
        generated_script = generated_scripts.get(slide.slide_number)
        if generated_script:
            script["script"] = generated_script
            script["keywords"] = _extract_keywords(generated_script)
            script["tts_text"] = generated_script
        script_path = job_paths.scripts_dir / f"script_{slide.slide_number:03d}.json"
        script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        scripts.append(script)
        upsert_slide(
            job_id,
            slide.slide_number,
            {
                "script": script,
                "evidence": _evidence_payload(slide, notes[idx - 1], script),
            },
        )
        progress = int(idx / max(1, len(manifest.slides)) * 100)
        update_stage(job_id, "script", status="running", progress=progress, detail=f"슬라이드 {idx}/{len(manifest.slides)} 스크립트 생성 완료")
    pipeline_meta = job.get("pipeline_meta") or _base_pipeline_meta()
    pipeline_meta["last_script_generated_at"] = datetime.now(UTC).isoformat()
    update_metadata(job_id, pipeline_meta=pipeline_meta)
    append_event(job_id, "script", "발표 스크립트 생성 단계 완료")
    update_stage(job_id, "script", status="done", progress=100, detail="모든 슬라이드 스크립트 생성 완료")
    _add_version_entry(job_id, kind="script_generation", summary="전체 슬라이드 스크립트 재생성 완료")
    return scripts


def _render_media_stage(job_id: str, manifest: SlideManifest, scripts: list[dict]) -> None:
    job_paths = get_demo_job_paths(job_id)
    voice_reference, voice_label = _resolve_voice_reference(job_id)
    fast_tts = _should_use_fast_tts(manifest)
    pipeline_meta = (get_job(job_id) or {}).get("pipeline_meta") or _base_pipeline_meta()
    pipeline_meta["tts_mode"] = "fast_local" if fast_tts else "qwen_clone"
    if voice_label:
        update_metadata(job_id, voice_reference_name=voice_label)
        append_event(job_id, "tts", f"음성 레퍼런스 등록: {voice_label}")
    if fast_tts:
        append_event(
            job_id,
            "tts",
            f"슬라이드 수가 많아 속도 우선 음성 모드 사용: {manifest.slide_count}장 문서는 로컬 한국어 TTS로 생성",
        )

    tts_detail = "빠른 데모 음성 생성 시작" if fast_tts else "보이스 클론 음성 생성 시작"
    update_stage(job_id, "tts", status="running", progress=10, detail=tts_detail)
    wav_paths: list[Path] = []
    glossary = (get_job(job_id) or {}).get("glossary") or {}
    for idx, script in enumerate(scripts, start=1):
        _check_stop(job_id, "tts")
        wav_path = job_paths.audio_dir / f"audio_{script['slide_number']:03d}.wav"
        tts_text = _apply_glossary(script["tts_text"], glossary)
        if fast_tts:
            _synthesize_with_local_korean_fallback(tts_text, wav_path)
        else:
            _synthesize_demo_tts(tts_text, wav_path, voice_reference)
        wav_paths.append(wav_path)
        upsert_slide(
            job_id,
            script["slide_number"],
            {
                "audio_url": f"/demo/api/jobs/{job_id}/audio/{script['slide_number']}/wav",
                "tts_preview": tts_text,
            },
        )
        progress = int(idx / max(1, len(scripts)) * 100)
        update_stage(job_id, "tts", status="running", progress=progress, detail=f"슬라이드 {idx}/{len(scripts)} 음성 생성 완료")
    merged_path = job_paths.audio_dir / "lecture_merged.wav"
    merge_audio(job_paths.audio_dir, merged_path)
    set_artifact(job_id, "merged_audio_url", f"/demo/api/jobs/{job_id}/audio/merged")
    append_event(job_id, "tts", "슬라이드별 음성과 병합 오디오 생성 완료")
    update_stage(job_id, "tts", status="done", progress=100, detail="음성 합성 완료")

    _check_stop(job_id, "video")
    png_paths = sorted(job_paths.rendered_dir.glob("slide_*.png"))
    update_stage(job_id, "video", status="running", progress=90, detail="단일 MP4로 최종 강의 영상 조립 중")
    output_video = job_paths.artifacts_dir / f"lecture_{job_id}.mp4"
    assemble_video(
        png_paths=png_paths,
        wav_paths=wav_paths,
        video_dir=job_paths.artifacts_dir / "video_clips",
        output_path=output_video,
        job_id=job_id,
    )
    set_artifact(job_id, "video_url", f"/demo/api/jobs/{job_id}/video")
    append_event(job_id, "video", f"Lecture video assembled: {output_video.name}")
    update_stage(job_id, "video", status="done", progress=100, detail="Lecture MP4 generated")
    pipeline_meta["last_media_generated_at"] = datetime.now(UTC).isoformat()
    update_metadata(job_id, pipeline_meta=pipeline_meta)
    _refresh_library_artifacts(job_id)
    _add_version_entry(job_id, kind="media_generation", summary="음성과 최종 영상 산출물 갱신 완료")

def _write_manifest(
    job_id: str,
    pdf_path: Path,
    slides: list[SlideRecord],
    lecture_name: str,
    target_minutes: int,
) -> SlideManifest:
    job = get_job(job_id) or {}
    settings = job.get("settings") or {}
    density = str(settings.get("lecture_density", "표준형")).lower()
    manifest = SlideManifest(
        job_id=job_id,
        file_sha256=sha256_file(pdf_path),
        lecture_name=lecture_name,
        subject_name="Demo Lecture",
        target_audience=str(settings.get("audience", "presentation")),
        target_minutes=max(1, target_minutes),
        style=LectureStyle(
            density="detailed" if "자세" in density else "concise",
            tone="formal",
            approach="explanatory",
        ),
        slide_count=len(slides),
        slides=slides,
    )
    job_paths = get_demo_job_paths(job_id)
    job_paths.manifest_path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return manifest


def _check_stop(job_id: str, current_stage: str) -> None:
    """Raise StopIteration if stop was requested for this job."""
    if _get_stop_flag(job_id).is_set():
        raise StopIteration(f"사용자 요청으로 파이프라인이 {current_stage} 단계에서 중지되었습니다.")


def run_demo_pipeline(job_id: str, pdf_path: Path, lecture_name: str, target_minutes: int) -> None:
    job_paths = get_demo_job_paths(job_id)
    current_stage = "parse"
    _clear_stop_flag(job_id)
    update_metadata(job_id, status="running")
    try:
        job = get_job(job_id) or {}
        settings = job.get("settings") or {}
        pipeline_meta = job.get("pipeline_meta") or _base_pipeline_meta()
        pipeline_meta["input_sha256"] = sha256_file(pdf_path)
        pipeline_meta["started_at"] = datetime.now(UTC).isoformat()
        update_metadata(job_id, pipeline_meta=pipeline_meta)
        _save_job_snapshot(job_id)

        current_stage = "parse"
        update_stage(job_id, "parse", status="running", progress=15, detail="PDF 구조 분석 중")
        slides = parse_pdf(pdf_path)
        manifest = _write_manifest(job_id, pdf_path, slides, lecture_name, target_minutes)
        append_event(job_id, "parse", f"Parsed {len(slides)} slides from PDF")
        update_stage(job_id, "parse", status="done", progress=100, detail=f"총 {len(slides)}개 슬라이드 파싱 완료")
        _check_stop(job_id, current_stage)

        current_stage = "render"
        update_stage(job_id, "render", status="running", progress=25, detail="슬라이드 미리보기 생성 중")
        png_paths = pdf_to_pngs(pdf_path, job_paths.rendered_dir)
        append_event(job_id, "render", f"Rendered {len(png_paths)} slide previews")
        update_stage(job_id, "render", status="done", progress=100, detail=f"총 {len(png_paths)}개 슬라이드 이미지 생성 완료")
        _check_stop(job_id, current_stage)

        current_stage = "vlm"
        vlm_model = os.environ.get("DEMO_VLM_MODEL", DEFAULT_GPT_VLM_MODEL)
        update_stage(job_id, "vlm", status="running", progress=5, detail=f"GPT 슬라이드 시각 분석 시작 ({vlm_model})")
        notes: list[dict] = []
        for idx, slide in enumerate(manifest.slides, start=1):
            _check_stop(job_id, current_stage)
            png_path = job_paths.rendered_dir / slide.png_path
            note = _run_gpt_vlm(slide, png_path, pdf_path)
            note_path = job_paths.vlm_dir / f"vlm_note_{slide.slide_number:03d}.json"
            note_path.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
            notes.append(note)
            upsert_slide(
                job_id,
                slide.slide_number,
                {
                    "title": _extract_title(slide),
                    "png_url": f"/demo/api/jobs/{job_id}/slides/{slide.slide_number}/png",
                    "vlm_note": note,
                    "evidence": _evidence_payload(slide, note, None),
                },
            )
            progress = int(idx / max(1, len(manifest.slides)) * 100)
            update_stage(job_id, "vlm", status="running", progress=progress, detail=f"슬라이드 {idx}/{len(manifest.slides)} 시각 분석 완료")
        append_event(job_id, "vlm", f"GPT 슬라이드 시각 분석 완료 ({len(manifest.slides)}개)")
        update_stage(job_id, "vlm", status="done", progress=100, detail="모든 슬라이드 시각 분석 완료")
        _check_stop(job_id, current_stage)

        current_stage = "script"
        update_stage(job_id, "script", status="running", progress=55, detail="GPT 강의 스크립트 생성 중")
        scripts = _render_script_stage(job_id, manifest, notes)
        _check_stop(job_id, current_stage)

        current_stage = "tts"
        _render_media_stage(job_id, manifest, scripts)

        current_stage = "package"
        update_stage(job_id, "package", status="running", progress=95, detail="다운로드 패키지 정리 중")
        set_artifact(job_id, "package_url", f"/demo/api/jobs/{job_id}/package/download")
        append_event(job_id, "package", "ZIP 패키지 다운로드 준비 완료")
        update_stage(job_id, "package", status="done", progress=100, detail="데모 산출물 준비 완료")
        _refresh_library_artifacts(job_id)
        _save_job_snapshot(job_id)
    except StopIteration as exc:
        mark_stopped(job_id, current_stage, str(exc))
        _save_job_snapshot(job_id)
    except Exception as exc:
        mark_failed(job_id, current_stage, str(exc))
        _save_job_snapshot(job_id)
    finally:
        _clear_stop_flag(job_id)


def launch_demo_pipeline(job_id: str, pdf_path: Path, lecture_name: str, target_minutes: int) -> None:
    thread = threading.Thread(
        target=run_demo_pipeline,
        args=(job_id, pdf_path, lecture_name, target_minutes),
        daemon=True,
    )
    thread.start()


def update_script_and_rebuild(job_id: str, slide_number: int, script_text: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise FileNotFoundError(f"Job not found: {job_id}")

    job_paths = get_demo_job_paths(job_id)
    script_path = job_paths.scripts_dir / f"script_{slide_number:03d}.json"
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: slide {slide_number}")

    data = json.loads(script_path.read_text(encoding="utf-8"))
    previous_script = data.get("script", "")
    target_seconds = float(data.get("target_seconds") or 12)
    normalized_script = _trim_script_to_budget(script_text, target_seconds)
    data["script"] = normalized_script
    data["keywords"] = _extract_keywords(normalized_script)
    data["edited"] = True
    data["edited_at"] = datetime.now(UTC).isoformat()
    data["tts_text"] = re.sub(r"\s+", " ", normalized_script).strip() or f"{slide_number}번 슬라이드를 설명합니다."
    script_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = SlideManifest.model_validate_json(job_paths.manifest_path.read_text(encoding="utf-8"))
    note_path = job_paths.vlm_dir / f"vlm_note_{slide_number:03d}.json"
    note = json.loads(note_path.read_text(encoding="utf-8")) if note_path.exists() else {}
    slide = manifest.slides[slide_number - 1]
    upsert_slide(
        job_id,
        slide_number,
        {
            "script": data,
            "evidence": _evidence_payload(slide, note, data),
        },
    )
    append_event(job_id, "script", f"Slide {slide_number} script edited")
    scripts = []
    for path in sorted(job_paths.scripts_dir.glob("script_*.json")):
        scripts.append(json.loads(path.read_text(encoding="utf-8")))

    _clear_stop_flag(job_id)
    _render_media_stage(job_id, manifest, scripts)
    set_artifact(job_id, "package_url", f"/demo/api/jobs/{job_id}/package/download")
    update_stage(job_id, "package", status="done", progress=100, detail="Outputs refreshed after edit")
    _add_version_entry(
        job_id,
        kind="script_edit",
        slide_number=slide_number,
        summary=f"{slide_number}번 슬라이드 스크립트 수정",
        payload={"previous_script": previous_script, "new_script": normalized_script},
    )
    _save_job_snapshot(job_id)
    return data


def update_glossary(job_id: str, glossary: dict[str, str]) -> dict:
    normalized = {
        _normalize_line(key): _normalize_line(value)
        for key, value in glossary.items()
        if _normalize_line(key) and _normalize_line(value)
    }
    update_metadata(job_id, glossary=normalized)
    append_event(job_id, "tts", f"발음 사전 갱신: {len(normalized)}개 항목")
    _add_version_entry(job_id, kind="glossary_update", summary="발음 사전 업데이트", payload={"glossary": normalized})
    _save_job_snapshot(job_id)
    return normalized


def rerun_tts_only(job_id: str, slide_number: int | None = None) -> None:
    try:
        job_paths = get_demo_job_paths(job_id)
        manifest = SlideManifest.model_validate_json(job_paths.manifest_path.read_text(encoding="utf-8"))
        scripts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(job_paths.scripts_dir.glob("script_*.json"))]
        target_scripts = [item for item in scripts if slide_number is None or item["slide_number"] == slide_number]
        if not target_scripts:
            raise FileNotFoundError("No scripts available for TTS rerun.")

        voice_reference, _ = _resolve_voice_reference(job_id)
        glossary = (get_job(job_id) or {}).get("glossary") or {}
        fast_tts = _should_use_fast_tts(manifest)
        update_stage(job_id, "tts", status="running", progress=5, detail="선택한 음성 산출물 재생성 중")
        for index, script in enumerate(target_scripts, start=1):
            _check_stop(job_id, "tts")
            wav_path = job_paths.audio_dir / f"audio_{script['slide_number']:03d}.wav"
            tts_text = _apply_glossary(script["tts_text"], glossary)
            if fast_tts:
                _synthesize_with_local_korean_fallback(tts_text, wav_path)
            else:
                _synthesize_demo_tts(tts_text, wav_path, voice_reference)
            upsert_slide(job_id, script["slide_number"], {"audio_url": f"/demo/api/jobs/{job_id}/audio/{script['slide_number']}/wav", "tts_preview": tts_text})
            progress = int(index / max(1, len(target_scripts)) * 100)
            update_stage(job_id, "tts", status="running", progress=progress, detail=f"선택 음성 {index}/{len(target_scripts)} 재생성 완료")

        merged_path = job_paths.audio_dir / "lecture_merged.wav"
        merge_audio(job_paths.audio_dir, merged_path)
        set_artifact(job_id, "merged_audio_url", f"/demo/api/jobs/{job_id}/audio/merged")
        update_stage(job_id, "tts", status="done", progress=100, detail="선택한 음성 산출물 재생성 완료")
        append_event(job_id, "tts", "TTS 부분 재실행 완료")
        _add_version_entry(job_id, kind="tts_rerun", slide_number=slide_number, summary="TTS 산출물 재실행 완료")
        _save_job_snapshot(job_id)
    except StopIteration as exc:
        mark_stopped(job_id, "tts", str(exc))
        _save_job_snapshot(job_id)
    except Exception as exc:
        mark_failed(job_id, "tts", str(exc))
        _save_job_snapshot(job_id)


def rerun_video_only(job_id: str) -> None:
    try:
        job_paths = get_demo_job_paths(job_id)
        png_paths = sorted(job_paths.rendered_dir.glob("slide_*.png"))
        wav_paths = sorted(job_paths.audio_dir.glob("audio_*.wav"))
        if not png_paths or not wav_paths:
            raise FileNotFoundError("Rendered slides or audio are missing for video rerun.")
        _check_stop(job_id, "video")
        update_stage(job_id, "video", status="running", progress=20, detail="기존 오디오로 영상만 다시 조립 중")
        output_video = job_paths.artifacts_dir / f"lecture_{job_id}.mp4"
        assemble_video(
            png_paths=png_paths,
            wav_paths=wav_paths,
            video_dir=job_paths.artifacts_dir / "video_clips",
            output_path=output_video,
            job_id=job_id,
        )
        set_artifact(job_id, "video_url", f"/demo/api/jobs/{job_id}/video")
        update_stage(job_id, "video", status="done", progress=100, detail="영상 재조립 완료")
        append_event(job_id, "video", "영상만 재조립 완료")
        _add_version_entry(job_id, kind="video_rerun", summary="최종 영상 재조립 완료")
        _refresh_library_artifacts(job_id)
        _save_job_snapshot(job_id)
    except StopIteration as exc:
        mark_stopped(job_id, "video", str(exc))
        _save_job_snapshot(job_id)
    except Exception as exc:
        mark_failed(job_id, "video", str(exc))
        _save_job_snapshot(job_id)


def rerun_scripts_and_media(job_id: str, target_minutes: int | None = None, settings_updates: dict | None = None) -> None:
    job = get_job(job_id)
    if job is None:
        raise FileNotFoundError(f"Job not found: {job_id}")

    job_paths = get_demo_job_paths(job_id)
    if not job_paths.manifest_path.exists():
        update_stage(job_id, "script", status="failed", detail="파싱 결과가 없습니다. 전체 파이프라인을 처음부터 실행해주세요.")
        append_event(job_id, "script", "재실행 실패: manifest.json 없음 (PDF 파싱 단계가 완료되지 않음)")
        update_metadata(job_id, status="failed")
        _clear_stop_flag(job_id)
        return
    manifest = SlideManifest.model_validate_json(job_paths.manifest_path.read_text(encoding="utf-8"))
    if target_minutes is not None:
        manifest = manifest.model_copy(update={"target_minutes": max(1, target_minutes)})
        job_paths.manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        update_metadata(job_id, target_minutes=max(1, target_minutes))
        append_event(job_id, "script", f"목표 강의 시간을 {max(1, target_minutes)}분으로 변경")
    if settings_updates:
        merged_settings = {**(job.get("settings") or {}), **settings_updates}
        merged_settings["target_minutes"] = manifest.target_minutes
        update_metadata(job_id, settings=merged_settings)
        append_event(job_id, "script", "강의 설정 패널 기준으로 설명 설정 반영")

    _clear_stop_flag(job_id)
    update_metadata(job_id, status="running")
    current_stage = "script"
    try:
        notes = _load_saved_notes(job_paths, manifest)
        update_stage(job_id, "script", status="running", progress=5, detail="저장된 VLM 결과를 기준으로 스크립트 재생성 중")
        scripts = _render_script_stage(job_id, manifest, notes)
        current_stage = "tts"
        _render_media_stage(job_id, manifest, scripts)
        set_artifact(job_id, "package_url", f"/demo/api/jobs/{job_id}/package/download")
        update_stage(job_id, "package", status="done", progress=100, detail="재생성된 산출물 반영 완료")
        _save_job_snapshot(job_id)
    except StopIteration as exc:
        mark_stopped(job_id, current_stage, str(exc))
        _save_job_snapshot(job_id)
    except Exception as exc:
        mark_failed(job_id, current_stage, str(exc))
        _save_job_snapshot(job_id)
    finally:
        _clear_stop_flag(job_id)


def launch_rerun(job_id: str, target_minutes: int | None = None, settings_updates: dict | None = None) -> None:
    thread = threading.Thread(
        target=rerun_scripts_and_media,
        args=(job_id, target_minutes, settings_updates),
        daemon=True,
    )
    thread.start()


def restore_job_from_disk(job_id: str) -> dict | None:
    existing = get_job(job_id)
    if existing is not None:
        return existing

    job_paths = get_demo_job_paths(job_id)
    if not job_paths.job_dir.exists():
        return None

    snapshot = _load_job_snapshot(job_id)

    input_files = sorted(job_paths.input_dir.glob("*.pdf"))
    filename = input_files[0].name if input_files else f"{job_id}.pdf"
    lecture_name = Path(filename).stem
    target_minutes = 8
    manifest: SlideManifest | None = None
    if job_paths.manifest_path.exists():
        manifest = SlideManifest.model_validate_json(job_paths.manifest_path.read_text(encoding="utf-8"))
        lecture_name = manifest.lecture_name
        target_minutes = manifest.target_minutes

    job = create_job(
        job_id,
        filename,
        lecture_name,
        target_minutes,
        settings=(snapshot or {}).get("settings"),
        glossary=(snapshot or {}).get("glossary"),
        version_history=(snapshot or {}).get("version_history"),
        pipeline_meta=(snapshot or {}).get("pipeline_meta"),
        library=(snapshot or {}).get("library"),
        recovery=(snapshot or {}).get("recovery"),
    )
    append_event(job_id, "package", "디스크에서 기존 작업 메타데이터 복구")

    if job_paths.manifest_path.exists():
        update_stage(job_id, "parse", status="done", progress=100, detail="파싱 결과 복구 완료")
    if list(job_paths.rendered_dir.glob("slide_*.png")):
        update_stage(job_id, "render", status="done", progress=100, detail="슬라이드 미리보기 복구 완료")

    slide_count = manifest.slide_count if manifest else 0
    if slide_count and manifest:
        notes = _load_saved_notes(job_paths, manifest)
        scripts = []
        for idx, slide in enumerate(manifest.slides, start=1):
            slide_payload = {
                "title": _extract_title(slide),
                "png_url": f"/demo/api/jobs/{job_id}/slides/{slide.slide_number}/png",
            }
            note = notes[idx - 1]
            if note:
                slide_payload["vlm_note"] = note
            script_path = job_paths.scripts_dir / f"script_{slide.slide_number:03d}.json"
            if script_path.exists():
                script = json.loads(script_path.read_text(encoding="utf-8"))
                scripts.append(script)
                slide_payload["script"] = script
                slide_payload["evidence"] = _evidence_payload(slide, note, script)
            else:
                slide_payload["evidence"] = _evidence_payload(slide, note, None)
            wav_path = job_paths.audio_dir / f"audio_{slide.slide_number:03d}.wav"
            if wav_path.exists():
                slide_payload["audio_url"] = f"/demo/api/jobs/{job_id}/audio/{slide.slide_number}/wav"
            upsert_slide(job_id, slide.slide_number, slide_payload)

        if any(notes):
            update_stage(job_id, "vlm", status="done", progress=100, detail="VLM 분석 결과 복구 완료")
        if scripts:
            update_stage(job_id, "script", status="done", progress=100, detail="스크립트 복구 완료")
        if list(job_paths.audio_dir.glob("audio_*.wav")):
            update_stage(job_id, "tts", status="done", progress=100, detail="생성된 음성 복구 완료")
            set_artifact(job_id, "merged_audio_url", f"/demo/api/jobs/{job_id}/audio/merged")
        if list(job_paths.artifacts_dir.glob("lecture_*.mp4")):
            update_stage(job_id, "video", status="done", progress=100, detail="강의 영상 복구 완료")
            update_stage(job_id, "package", status="done", progress=100, detail="다운로드 산출물 복구 완료")
            set_artifact(job_id, "video_url", f"/demo/api/jobs/{job_id}/video")
            set_artifact(job_id, "package_url", f"/demo/api/jobs/{job_id}/package/download")

    _, voice_label = _resolve_voice_reference(job_id)
    if voice_label:
        update_metadata(job_id, voice_reference_name=voice_label)

    _refresh_library_artifacts(job_id)
    _save_job_snapshot(job_id)
    return get_job(job_id)


def restore_all_jobs_from_disk() -> list[dict]:
    DEMO_ROOT.mkdir(parents=True, exist_ok=True)
    restored: list[dict] = []
    for path in sorted(DEMO_ROOT.iterdir()):
        if not path.is_dir() or path.name.startswith("_"):
            continue
        has_manifest = (path / "parsed" / "manifest.json").exists()
        has_snapshot = (path / "job_state.json").exists()
        has_pdf = any((path / "input").glob("*.pdf"))
        if not has_manifest and not has_pdf and not has_snapshot:
            continue
        job = restore_job_from_disk(path.name)
        if job:
            restored.append(job)
    return restored
