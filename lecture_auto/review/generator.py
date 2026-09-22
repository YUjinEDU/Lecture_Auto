"""Generates easy review scripts and interactive Q&A answers from lecture materials."""
from __future__ import annotations

import json
import logging
from typing import Any

from lecture_auto.llm.base import LLMClient
from lecture_auto.llm.openai_client import OpenAILLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_EASY_REVIEW = """당신은 대학교 강의를 학생들의 복습용으로 재구성하는 친절하고 유능한 교수님 페르소나입니다.
실제 수업에서 교수님이 하신 말씀(실강 녹음 전사본)과 슬라이드 내용을 결합하여,
학생이 시험 직전 90초 만에 완벽히 이해할 수 있는 [복습용 쉬운 해설 스크립트]와 [핵심 요약], [시험/과제 힌트]를 JSON 형식으로 작성하세요.

[말투 가이드]
- 교재 요약문('~합니다', '~입니다') 대신 실제 교수님 강의 구어체('~죠', '~거든요', '~있겠죠?', '자', '우리가')를 사용하세요.
- 군더더기나 말더듬은 걷어내되, 교수님이 실제 강조한 심리 분석, 직관적인 비유, 실무 예시를 살리세요.
- 스크립트 분량은 약 90초 (450~550자 내외)로 작성하세요.

출력 형식은 반드시 아래 JSON이어야 합니다:
{
  "easy_script": "90초 복습 해설 본문",
  "key_point": "슬라이드 핵심 요약 한 줄",
  "exam_hint": "교수님이 강조한 시험/과제 출제 포인트 한 줄"
}"""

SYSTEM_PROMPT_QNA = """당신은 대학교 강의를 진행하신 교수님입니다.
학생이 복습 도중 특정 슬라이드를 보며 궁금한 점을 질문했습니다.
해당 슬라이드의 내용과 실제 수업에서 설명했던 맥락을 바탕으로,
학생에게 직접 말하듯 친절하고 명쾌하게 2~3문장(구어체, ~죠, ~거든요)으로 답변해 주세요."""


def generate_easy_review(
    slide_text: str,
    transcript_segment: str,
    *,
    client: LLMClient | None = None,
) -> dict[str, str]:
    """Generates 90s easy review script, key point, and exam hint."""
    if client is None:
        client = OpenAILLMClient()

    user_prompt = f"""### 슬라이드 내용:
{slide_text}

### 실제 수업(실강) 발언:
{transcript_segment}

위 내용을 바탕으로 학생이 쉽게 이해할 수 있는 90초 복습 해설과 핵심/시험 포인트를 JSON으로 작성해 주세요."""

    raw_response = client.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT_EASY_REVIEW},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )

    clean_text = raw_response.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    clean_text = clean_text.strip()

    try:
        data = json.loads(clean_text)
        return {
            "easy_script": data.get("easy_script", ""),
            "key_point": data.get("key_point", ""),
            "exam_hint": data.get("exam_hint", ""),
        }
    except Exception as e:
        logger.error("Failed to parse JSON response: %s (raw: %s)", e, raw_response)
        return {
            "easy_script": clean_text,
            "key_point": "핵심 개념을 복습하세요.",
            "exam_hint": "슬라이드의 주요 용어와 예시를 숙지하세요.",
        }


def answer_student_question(
    slide_title: str,
    slide_text: str,
    easy_script: str,
    question: str,
    *,
    client: LLMClient | None = None,
) -> str:
    """Answers a student's question about a specific slide in professor persona."""
    if client is None:
        client = OpenAILLMClient()

    context = f"""슬라이드 제목: {slide_title}
슬라이드 내용:
{slide_text}

슬라이드 쉬운 해설:
{easy_script}

학생 질문:
{question}"""

    response = client.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT_QNA},
            {"role": "user", "content": context},
        ],
        temperature=0.3,
        max_tokens=300,
    )
    return response.strip()
