"""S16 (D-18): summarize what an earlier lecture of a series actually said.

Input is the final on-disk scripts (what was spoken, hand edits included), not
the plan. Opt-in only: the batch calls this when a LECTURES entry has an
explicit ``previous`` key.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from pydantic import ValidationError

from lecture_auto.pipeline.cache import (
    content_hash,
    is_cache_valid,
    write_cache_hash,
    write_text_atomic,
)
from lecture_auto.pipeline.script_gen import strip_markdown_json_fence
from lecture_auto.schemas.lecture_plan import LectureMemory

logger = logging.getLogger(__name__)

_MEMORY_SYSTEM_PROMPT = (
    "당신은 연속 강의의 지난 시간 내용을 정리하는 조교입니다. "
    "제공된 것은 지난 강의에서 실제로 말한 슬라이드별 대본입니다. "
    "대본에 실제로 나온 내용만 근거로 삼고, 없는 내용을 추측하지 마세요.\n"
    "다음 JSON 형식으로만 출력하세요:\n"
    '{"covered_concepts": ["<다룬 핵심 개념, 최대 12개>"], '
    '"running_examples": ["<반복해서 쓴 사례, 최대 3개>"], '
    '"closing_hook": "<마지막에 다음 시간에 다룬다고 예고한 내용, 없으면 빈 문자열>"}'
)


def load_lecture_scripts(work_dir: Path) -> dict[int, str]:
    """slide number -> final script text from ``<work_dir>/scripts/script_NNN.json``."""
    scripts: dict[int, str] = {}
    for p in sorted((Path(work_dir) / "scripts").glob("script_*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        scripts[int(data["slide_number"])] = data["script"]
    return scripts


def _scripts_text(scripts: dict[int, str]) -> str:
    return "\n\n".join(f"[슬라이드 {n}]\n{scripts[n]}" for n in sorted(scripts))


def summarize_lecture(client, lecture_name: str, scripts: dict[int, str], lecture_id: str = "") -> LectureMemory:
    """One text-LLM call; one re-ask on malformed JSON, then raise."""
    body = _scripts_text(scripts)
    messages = [
        {"role": "system", "content": _MEMORY_SYSTEM_PROMPT},
        {"role": "user", "content": f"[강의명] {lecture_name}\n\n{body}"},
    ]
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    for attempt in range(2):
        raw = client.chat(messages)
        try:
            data = json.loads(strip_markdown_json_fence(raw))
            return LectureMemory(
                lecture_id=lecture_id or lecture_name,
                covered_concepts=list(data.get("covered_concepts", []))[:12],
                running_examples=list(data.get("running_examples", []))[:3],
                closing_hook=data.get("closing_hook", "") or "",
                source_sha256=sha,
            )
        except (json.JSONDecodeError, ValidationError, AttributeError, TypeError):
            if attempt:
                raise
            logger.warning("Lecture memory %r: malformed JSON from LLM -- re-asking once", lecture_name)


def load_or_create_memory(
    client, lecture_id: str, lecture_name: str, work_dir: Path, llm_config: str
) -> LectureMemory:
    """Memory of the lecture in ``work_dir``, cached in ``lecture_memory.json`` (+ .hash)."""
    scripts = load_lecture_scripts(work_dir)
    if not scripts:
        raise FileNotFoundError(
            f"previous lecture {lecture_id!r} has no generated scripts in {Path(work_dir) / 'scripts'} "
            "-- generate it first"
        )
    path = Path(work_dir) / "lecture_memory.json"
    key = content_hash(_MEMORY_SYSTEM_PROMPT, lecture_name, _scripts_text(scripts), llm_config)
    if is_cache_valid(path, key):
        return LectureMemory(**json.loads(path.read_text(encoding="utf-8")))
    memory = summarize_lecture(client, lecture_name, scripts, lecture_id)
    write_text_atomic(path, json.dumps(memory.model_dump(), ensure_ascii=False, indent=2))
    write_cache_hash(path, key)
    return memory
