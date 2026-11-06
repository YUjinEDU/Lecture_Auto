"""The lectures that were hard-coded in ``scripts/batch_generate_lectures.py`` before
per-lecture ``project.json`` files existed. Only migration and the no-projects fallback read it."""
from pathlib import Path

BUILTIN_LECTURES: list[dict] = [
    {
        "id": "01_AI현업_02_디자인씽킹개요",
        "name": "02-디자인씽킹 개요",
        "subject": "AI활용현업문제해결",
        "pdf": Path("data/PDF/AI현업문제해결/02-디자인씽킹 개요.pdf"),
    },
    {
        "id": "02_AI현업_03_고객문제이해",
        "name": "03-고객 문제 이해",
        "subject": "AI활용현업문제해결",
        "pdf": Path("data/PDF/AI현업문제해결/03-고객 문제 이해.pdf"),
    },
    {
        "id": "03_AI현업_04_문제정의와아이디에이션",
        "name": "04-문제정의와 아이디에이션",
        "subject": "AI활용현업문제해결",
        "pdf": Path("data/PDF/AI현업문제해결/04-문제정의와 아이디에이션.pdf"),
    },
    {
        "id": "04_종합설계_02_고객문제이해및정의",
        "name": "02_고객 문제 이해 및 정의",
        "subject": "종합설계",
        "pdf": Path("data/PDF/종합설계 2026/1차/02_고객 문제 이해 및 정의.pdf"),
    },
    {
        "id": "05_종합설계_03_문제정의와아이디에이션",
        "name": "03_문제정의와 아이디에이션",
        "subject": "종합설계",
        "pdf": Path("data/PDF/종합설계 2026/1차/03_문제정의와 아이디에이션.pdf"),
        "clone_from": "03_AI현업_04_문제정의와아이디에이션",
    },
    # S3-c (D-10, D-11): PPTX inputs (S3-a converts pptx -> work_dir/input/*.pdf
    # via pptx_to_pdf) + reference lecture scripts (S3-b: reference only, not
    # fed straight to TTS -- see lecture_plan.parse_reference_script).
    {
        "id": "06_종합설계_04-1_아이디어를컨셉으로만들기",
        "name": "04-1_아이디어를 컨셉으로 만들기",
        "subject": "종합설계",
        "pptx": Path("data/PDF/종합설계 2026/04-1_아이디어를 컨셉으로 만들기.pptx"),
        "reference_script": Path("data/PDF/종합설계 2026/04-1_아이디어를컨셉으로만들기_강의스크립트.md"),
    },
    {
        "id": "07_종합설계_04-2_프로토타이핑과테스트",
        "name": "04-2_프로토타이핑과 테스트",
        "subject": "종합설계",
        "pptx": Path("data/PDF/종합설계 2026/04-2_프로토타이핑과 테스트.pptx"),
        "reference_script": Path("data/PDF/종합설계 2026/04-2_프로토타이핑과테스트_강의스크립트.md"),
    },
    {
        "id": "08_종합설계_05_스크럼_활용_애자일_프로세스",
        "name": "05_스크럼 활용 애자일 프로세스",
        "subject": "종합설계",
        "pptx": Path("data/PDF/종합설계 2026/05_스크럼_활용_애자일_프로세스.pptx"),
        "reference_script": Path("data/PDF/종합설계 2026/05_스크럼_활용_애자일_프로세스_강의스크립트.md"),
    },
    {
        "id": "09_종합설계_06_Product_Backlog",
        "name": "06_Product Backlog",
        "subject": "종합설계",
        "pptx": Path("data/PDF/종합설계 2026/06_Product_Backlog.pptx"),
        "reference_script": Path("data/PDF/종합설계 2026/06_Product_Backlog_강의스크립트.md"),
    },
    # 07 (2026-10-19): the supplied *_강의스크립트.md for this deck is LLM-made reference
    # material of no authority (user), so neither entry links it. Two cuts of the
    # same deck; ``target_minutes`` is the plan target (non-binding for the
    # free cut), ``min_minutes`` is a hard floor checked before any TTS runs.
    # ``voice_match`` turns on per-segment spectral matching (voice_match.py).
    {
        "id": "10_종합설계_07_시스템구조_자유분량",
        "name": "07_시스템 구조 설계 및 개발 환경 구축 (자유 분량)",
        "subject": "종합설계",
        "pptx": Path("data/PDF/종합설계 2026/07_시스템구조설계 및 개발환경.pptx"),
        "target_minutes": 18.0,
        "voice_match": True,
        "ref_voice": Path("data/audio_ref/reference_v2.wav"),
        "master_audio": True,
    },
    {
        "id": "11_종합설계_07_시스템구조_30분이상",
        "name": "07_시스템 구조 설계 및 개발 환경 구축 (30분 이상)",
        "subject": "종합설계",
        "pptx": Path("data/PDF/종합설계 2026/07_시스템구조설계 및 개발환경.pptx"),
        "target_minutes": 33.0,
        "min_minutes": 30.0,
        "voice_match": True,
        "ref_voice": Path("data/audio_ref/reference_v2.wav"),
        "master_audio": True,
    },
]
