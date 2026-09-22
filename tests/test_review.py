"""Unit tests for the interactive review module (lecture_auto/review)."""
import json
from unittest.mock import MagicMock

from lecture_auto.review import (
    QnARequest,
    QnAResponse,
    ReviewPack,
    ReviewSlideData,
    answer_student_question,
    generate_easy_review,
)


def test_generate_easy_review_json_parsing():
    mock_client = MagicMock()
    mock_client.chat.return_value = json.dumps({
        "easy_script": "자, 이 슬라이드에서 쓰레기 문제를 한번 같이 살펴보죠.",
        "key_point": "쓰레기 투기의 심리적 원인 분석",
        "exam_hint": "불법투기 이면의 심리적 안정감 개념 출제 주의",
    })

    result = generate_easy_review(
        slide_text="공감지도 쓰레기 문제",
        transcript_segment="이제 요 공감지도를 보고...",
        client=mock_client,
    )

    assert "자, 이 슬라이드에서" in result["easy_script"]
    assert result["key_point"] == "쓰레기 투기의 심리적 원인 분석"
    assert "심리적 안정감" in result["exam_hint"]


def test_generate_easy_review_markdown_json():
    mock_client = MagicMock()
    mock_client.chat.return_value = "```json\n" + json.dumps({
        "easy_script": "복습 스크립트입니다.",
        "key_point": "핵심 요약",
        "exam_hint": "시험 힌트",
    }) + "\n```"

    result = generate_easy_review(
        slide_text="슬라이드",
        transcript_segment="실강",
        client=mock_client,
    )

    assert result["easy_script"] == "복습 스크립트입니다."
    assert result["key_point"] == "핵심 요약"


def test_answer_student_question():
    mock_client = MagicMock()
    mock_client.chat.return_value = "자, 좋은 질문이에요. 그 공식에서 분모는 자유도를 의미하거든요."

    answer = answer_student_question(
        slide_title="공감지도",
        slide_text="내용",
        easy_script="해설",
        question="왜 분모가 n-1인가요?",
        client=mock_client,
    )

    assert "자유도를 의미하거든요" in answer


def test_review_pack_schema():
    slide = ReviewSlideData(
        slide_index=0,
        slide_number=1,
        title="공감지도",
        image_url="/slides/1.png",
        easy_script="해설입니다.",
        key_point="핵심입니다.",
        exam_hint="힌트입니다.",
        raw_audio_start_sec=10.0,
        raw_audio_end_sec=50.0,
    )
    pack = ReviewPack(
        course_title="AI현업문제해결",
        lecture_title="공감과 디브리핑",
        slides=[slide],
    )
    assert pack.slides[0].slide_number == 1
    assert pack.slides[0].raw_audio_end_sec == 50.0


def test_slice_raw_audio_mock(monkeypatch, tmp_path):
    from unittest.mock import MagicMock
    from lecture_auto.review.audio import slice_raw_audio

    mock_run = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
    monkeypatch.setattr("subprocess.run", mock_run)

    out_file = tmp_path / "slice.mp3"
    result = slice_raw_audio("dummy.m4a", 10.0, 20.0, out_file)
    assert result == out_file
    mock_run.assert_called_once()


def test_review_api_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from lecture_auto.api.main import app

    test_client = TestClient(app)

    # 1. GET /review (HTML)
    res = test_client.get("/review")
    assert res.status_code == 200
    assert "<title>Interactive Lecture Player" in res.text

    # 2. GET /review/data (JSON)
    res = test_client.get("/review/data")
    assert res.status_code == 200
    data = res.json()
    assert "slides" in data
    assert data["slides"][0]["slide_number"] == 31

    # 3. POST /review/qna
    monkeypatch.setattr(
        "lecture_auto.api.routes.review.answer_student_question",
        lambda **kwargs: "학생, 좋은 질문이에요! 이 부분은..."
    )
    res = test_client.post("/review/qna", json={"slide_index": 30, "question": "질문있어요!"})
    assert res.status_code == 200
    assert "좋은 질문이에요" in res.json()["answer_text"]


