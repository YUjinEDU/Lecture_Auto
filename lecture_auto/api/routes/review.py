"""FastAPI routes for Interactive Review Lecture Player."""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from lecture_auto.review.generator import answer_student_question
from lecture_auto.review.schema import QnARequest, QnAResponse, ReviewPack, ReviewSlideData

router = APIRouter(prefix="/review", tags=["review"])

STATIC_DIR = Path(__file__).resolve().parents[2] / "review" / "static"
DATA_WORK_DIR = Path("data/work").resolve()

# Pre-populated prototype slide data (Slide 31)
PROTOTYPE_SLIDE_31 = ReviewSlideData(
    slide_index=30,
    slide_number=31,
    title="공감 지도사례: 쓰레기 문제",
    image_url="/review/media/slides/prototype_slide_31.png",
    easy_script=(
        "자, 이 공감지도에서 중요한 건 쓰레기 문제를 단순히 ‘시민의식 부족’으로 보면 안 된다는 거예요. "
        "당사자는 버릴 곳이 마땅치 않고 귀찮은 데다, 버리고 나서도 찝찝하죠. "
        "집 입구에는 쓰레기와 냄새, 파리가 보이고, 주변에서는 CCTV 감시나 경고 딱지 이야기를 듣습니다. "
        "그래서 실제 행동은 주로 밤에 몰래 버리거나, 남들이 이미 버린 곳에 같이 버리는 형태로 나타나죠. "
        "여기서 남들이 버린 곳에 버리는 건 단순한 모방이 아니라 심리적 안정감 때문이에요. "
        "‘나만 잘못하는 건 아니다’라는 느낌이 들거든요. "
        "Pain은 버릴 곳을 찾는 스트레스와 죄책감이고, Gain은 집 가까이에서 쉽고 편하게, 죄책감 없이 처리하는 겁니다. "
        "자, 이 생각·감정·환경·행동·고통·욕구를 종합해서 다음 단계인 문제 정의로 넘어가야 하겠죠."
    ),
    key_point="쓰레기 투기는 단순 시민의식 문제가 아니라, 불편한 처리 환경과 죄책감·심리적 안정감이 얽힌 사용자 문제입니다.",
    exam_hint="공감지도 각 항목을 구분하고, 특히 남들이 버린 곳에 버리는 행동의 이유를 ‘심리적 안정감’으로 설명하는 것이 핵심입니다.",
    raw_audio_start_sec=1380.0,
    raw_audio_end_sec=1590.0,
    raw_audio_url="/review/media/audio/prototype_slide_31_raw.mp3",
    ai_audio_url="/review/media/audio/prototype_slide_31_ai.wav",
)


@router.get("", response_class=HTMLResponse)
async def get_review_player_page():
    """Serves the interactive player HTML UI."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Player interface not found")
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


@router.get("/data", response_model=ReviewPack)
async def get_review_data():
    """Returns the review pack data for the current lecture."""
    return ReviewPack(
        course_title="AI활용현업문제해결 (2025)",
        lecture_title="03. 공감과 디브리핑",
        slides=[PROTOTYPE_SLIDE_31],
    )


@router.post("/qna", response_model=QnAResponse)
async def handle_slide_qna(req: QnARequest):
    """Answers a student question about a slide in the professor persona."""
    slide = PROTOTYPE_SLIDE_31
    slide_text = f"제목: {slide.title}\n핵심: {slide.key_point}\n힌트: {slide.exam_hint}"

    answer = answer_student_question(
        slide_title=slide.title,
        slide_text=slide_text,
        easy_script=slide.easy_script,
        question=req.question,
    )

    return QnAResponse(
        slide_index=req.slide_index,
        question=req.question,
        answer_text=answer,
    )


@router.get("/media/slides/{filename}")
async def get_slide_image(filename: str):
    """Serves slide images."""
    file_path = DATA_WORK_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Slide image not found")
    return FileResponse(file_path, media_type="image/png")


@router.get("/media/audio/{filename}")
async def get_audio_file(filename: str):
    """Serves audio files (both raw and AI synthesized)."""
    file_path = DATA_WORK_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    media_type = "audio/mpeg" if filename.endswith(".mp3") else "audio/wav"
    return FileResponse(file_path, media_type=media_type)
