"""Glossary and quiz for a lecture, drafted by the text LLM from the final scripts.

Nothing reaches students until the professor approves it: every item carries an
``approved`` flag, a regenerated draft keeps the approved items, and the public view
returns approved items only. Stored as ``data/work_batch/<id>/study.json``.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from lecture_auto.pipeline.cache import write_text_atomic

STUDY_FILE = "study.json"
_MAX_SCRIPT_CHARS = 60000

_PROMPT = """다음은 한 대학 강의의 슬라이드별 대본입니다. 학생 복습 자료를 만들어 주세요.

규칙:
- 대본에 실제로 나온 내용만 씁니다. 대본에 없는 사실을 지어내지 않습니다.
- glossary: 핵심 용어 {n_terms}개 이내. term(용어), definition(대본 내용에 근거한 1~2문장 설명), slide(처음 설명된 슬라이드 번호).
- quiz: 객관식 {n_quiz}문제 이내. question, choices(보기 정확히 4개), answer(정답 보기의 0부터 시작하는 번호),
  explanation(정답 이유 1~2문장), slide(근거 슬라이드 번호).
- 출력은 JSON 객체 하나만: {{"glossary": [...], "quiz": [...]}}

대본:
{scripts}
"""


class GlossaryItem(BaseModel):
    term: str
    definition: str
    slide: int | None = None
    approved: bool = False


class QuizItem(BaseModel):
    question: str
    choices: list[str]
    answer: int
    explanation: str = ""
    slide: int | None = None
    approved: bool = False

    @field_validator("choices")
    @classmethod
    def _four_choices(cls, v: list[str]) -> list[str]:
        if len(v) != 4 or any(not c.strip() for c in v):
            raise ValueError("a quiz item needs exactly 4 non-empty choices")
        return v

    def model_post_init(self, _context) -> None:
        if not 0 <= self.answer < len(self.choices):
            raise ValueError("answer must index one of the choices")


class Study(BaseModel):
    lecture_id: str
    glossary: list[GlossaryItem] = Field(default_factory=list)
    quiz: list[QuizItem] = Field(default_factory=list)
    generated_at: datetime | None = None

    def public(self) -> dict:
        return {
            "glossary": [i.model_dump(exclude={"approved"}) for i in self.glossary if i.approved],
            "quiz": [i.model_dump(exclude={"approved"}) for i in self.quiz if i.approved],
        }


def study_path(work_dir: Path, lec_id: str) -> Path:
    return work_dir / lec_id / STUDY_FILE


def load_study(work_dir: Path, lec_id: str) -> Study:
    path = study_path(work_dir, lec_id)
    if not path.exists():
        return Study(lecture_id=lec_id)
    return Study.model_validate_json(path.read_text(encoding="utf-8"))


def save_study(work_dir: Path, study: Study) -> None:
    write_text_atomic(study_path(work_dir, study.lecture_id), study.model_dump_json(indent=2))


def _scripts_block(scripts: dict[int, dict]) -> str:
    text = "\n\n".join(f"[슬라이드 {n}]\n{sc.get('script', '').strip()}" for n, sc in sorted(scripts.items()))
    return text[:_MAX_SCRIPT_CHARS]


def _parse(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the model did not return a JSON object")
    return json.loads(raw[start: end + 1])


def _valid(model, items: list) -> list:
    out = []
    for item in items if isinstance(items, list) else []:
        try:
            out.append(model.model_validate({**item, "approved": False}))
        except (ValueError, TypeError):
            continue
    return out


def draft_study(
    llm_client, lec_id: str, scripts: dict[int, dict], previous: Study | None = None,
    n_terms: int = 12, n_quiz: int = 8,
) -> Study:
    """New draft; approved items of ``previous`` are kept, unapproved ones are replaced."""
    raw = llm_client.complete_text(
        _PROMPT.format(n_terms=n_terms, n_quiz=n_quiz, scripts=_scripts_block(scripts)), temperature=0.2,
    )
    data = _parse(raw)
    keep_g = [i for i in (previous.glossary if previous else []) if i.approved]
    keep_q = [i for i in (previous.quiz if previous else []) if i.approved]
    seen_terms = {i.term.strip() for i in keep_g}
    seen_q = {i.question.strip() for i in keep_q}
    glossary = keep_g + [i for i in _valid(GlossaryItem, data.get("glossary")) if i.term.strip() not in seen_terms]
    quiz = keep_q + [i for i in _valid(QuizItem, data.get("quiz")) if i.question.strip() not in seen_q]
    return Study(lecture_id=lec_id, glossary=glossary, quiz=quiz, generated_at=datetime.now(UTC))
