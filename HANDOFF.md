# Lecture Auto 프로젝트 인수인계 문서 (Handoff Document)

**작성 일자**: 2026-10-09  
**최신 커밋**: `2ea32bc` (`origin/master` 동기화 완료)  
**테스트 상태**: `pytest` 526개 전체 100% PASS, `ruff check` 0 errors  
**대상 시스템**: 교수 강의 슬라이드(PPTX/PDF) 기반 자동 스크립트 생성 및 고품질 음성 복제(TTS) / 비디오 합성 파이프라인

---

## 1. 프로젝트 개요 및 핵심 아키텍처

교수님의 강의 슬라이드(PDF/PPTX)를 입력받아 **대본 생성 ➔ 음성 복제(TTS) ➔ 자막(SRT/VTT) ➔ 최종 MP4 영상 합성**을 자동화하는 내부 파이프라인입니다.

### 3대 실행 드라이버
1. **Interactive CLI (`run.py`)**: 6단계(파싱 ➔ VLM ➔ 대본 ➔ TTS ➔ 자막 ➔ 영상) 대화형 검증 실행기 (`[y/n]` 게이트 포함).
2. **배치 대량 생성기 (`scripts/batch_generate_lectures.py`)**: 실제 교과목(AI활용현업문제해결, 종합설계 등) 대량 배치 파이프라인.
3. **Async API & Workers (`lecture_auto/api/`, `lecture_auto/tasks/`)**: FastAPI + Celery + Redis 기반 비동기 서비스 레이어.

---

## 2. 최근 주요 작업 및 달성 성과 (S21 ~ S22)

### 2.1 S21: 스튜디오 음성 마스터링 체인 구축
- **문제점**: 원본 교수님 음성 레퍼런스 및 생성 음성에 교실 울림(Boxiness), 저주파 럼블(HVAC 노이즈), 치찰음(Sibilance) 및 말끝 늘어짐(Mumbling tail) 존재.
- **해결책 (`lecture_auto/pipeline/audio_mastering.py`)**:
  - 순수 CPU `scipy.signal` DSP 기반 6단계 마스터링 체인 구축 (추가 VRAM 0 MB, 3ms 이내 완료).
  - 80Hz 2차 Zero-phase High-pass Filter (HVAC 저주파 차단).
  - 320Hz Peaking EQ (-1.8 dB, 강의실 박시 룸 울림 컷).
  - 3000Hz Peaking EQ (+1.5 dB, 자음 명료도 부스트).
  - 6200Hz Split-band De-esser (-2.5 dB, 고주파 치찰음 억제).
  - 선형 보존형 Soft-Knee 리미터 (피크 0.95 천장 유지).
  - EBU R128 (-20 LUFS) 방송 규격 통합 라우드니스 정규화.
  - VAD 역방향 에너지 스캔 기반 테일 트림 (`trim_speech_tail`, 70ms 안전 패드).
- **실측 성과**:
  - 신규 스튜디오 레퍼런스 [`data/audio_ref/reference_v2.wav`](file:///home/dbsdosdb/workspace/Lecture_Auto/data/audio_ref/reference_v2.wav) 구축.
  - 노이즈 플로어 **-38.8 dB ➔ -68.4 dB (29.6 dB 노이즈 감쇄)** 달성.
  - 비디오 합성기([`video.py`](file:///home/dbsdosdb/workspace/Lecture_Auto/lecture_auto/pipeline/video.py)) 및 배치 스크립트([`batch_generate_lectures.py`](file:///home/dbsdosdb/workspace/Lecture_Auto/scripts/batch_generate_lectures.py))에 마스터링 옵션 및 환경변수 연동 완료.

---

### 2.2 S22: 한국어 강의 운율학(K-ToBI) 및 파이프라인 정상화
- **연구 및 토론**: 최신 논문(Interspeech, ICASSP, ACL 2023–2026) 및 한국어 운율학(K-ToBI) 서베이 완료 ([`LITERATURE_SURVEY.md`](file:///home/dbsdosdb/workspace/Lecture_Auto/docs/hardening/stages/S22_prosody_style/LITERATURE_SURVEY.md), [`DEBATE_AND_RESEARCH.md`](file:///home/dbsdosdb/workspace/Lecture_Auto/docs/hardening/stages/S22_prosody_style/DEBATE_AND_RESEARCH.md)).
- **단일 앵커 고정 원칙**: 슬라이드별 레퍼런스 교체 시 화자 유사도(SECS $0.88 \to 0.65$)가 붕괴되는 현상 방어 ➔ `reference_v2.wav` 단일 앵커 고정.
- **스튜디오 룸 톤 디더링 (`synthesize_room_tone`)**: 디지털 0.0 무음 구간에 $-58\text{ dBFS}$ (1200Hz LPF 가우시안 앰비언스) 디더링 합성으로 이어폰 게이팅 노이즈 및 청취 피로도 제거.
- **K-ToBI 구어체 대본 가이드 (`restyle_instruction.md`, `restyle.py`)**:
  - 종결어미 황금비: `~요`(60%), `~습니다`(25%), `~죠/~까요`(15%).
  - 액센트구(AP) 호흡 쉼표(`,`) 가이드 및 `compute_metrics` 지표 확장.
- **주요 버그 해결 및 파이프라인 정상화 (`raon_tts.py`)**:
  1. **단어 잘림(Chopped words) 해결**: 세그먼트 트리밍 시 안전 여유 마진이 50ms로 너무 짧아 첫 자음과 종결어미가 잘리던 문제를 **선두 80ms, 말미 100ms**로 대폭 확장하고 **5ms 코사인 페이드**를 적용하여 단어 잘림 완벽 박멸.
  2. **톤 불안정 및 가성 튐 해결**: `TTS_TEMPERATURE = 0.85` 상수는 기존 캐시 무회귀를 위해 유지하되, 런타임 인퍼런스는 `LECTURE_AUTO_TTS_TEMPERATURE` (기본값 `0.72`)로 안정화하여 피치 튐 억제.

---

## 3. 핵심 파일 및 디렉터리 맵

```text
Lecture_Auto/
├── lecture_auto/
│   ├── pipeline/
│   │   ├── audio_mastering.py       # [S21/S22] 6단계 DSP 마스터링 & 룸톤 디더링
│   │   ├── raon_tts.py              # [S22] Raon-Speech-9B 세그먼트 생성 & 안전 트리밍
│   │   ├── restyle.py               # [S22] K-ToBI 구어체 리스타일러 & 메트릭 계산기
│   │   ├── video.py                 # 슬라이드 PNG + WAV -> MP4 비디오 합성
│   │   ├── cache.py                 # SHA-256 기반 캐시 및 원자적 파일 쓰기
│   │   └── script_gen.py            # Claude 기반 1차 대본 생성기
│   └── prompts/
│       └── restyle_instruction.md   # [S22] 한국어 강의 화법 및 어미 황금비 프롬프트
├── scripts/
│   ├── build_voice_reference.py     # reference_v2.wav 스튜디오 정제 생성기
│   ├── bench_voice_quality.py       # S21 음향 노이즈 감쇄 벤치마크
│   ├── bench_prosody_style.py       # S22 운율 및 피치(F0) 벤치마크
│   └── batch_generate_lectures.py   # 강의 대량 배치 실행 스크립트
├── data/
│   ├── audio_ref/
│   │   ├── reference_v1.wav         # 기존 레퍼런스 (보존됨)
│   │   ├── reference_v2.wav         # [S21] 정제된 클린 스튜디오 레퍼런스
│   │   ├── comparison_s21/          # S21 노이즈 전후 비교 음성 WAV
│   │   └── comparison_s22/          # S22 운율 및 단어잘림 해결 비교 음성 WAV
└── docs/hardening/stages/
    ├── S21_audio_quality/           # S21 보고서 및 토론록
    └── S22_prosody_style/           # S22 문헌 서베이, 토론록, 실측 보고서
```

---

## 4. 비교 청취 파일 경로 (Verification Audio Files)

현 서버 로컬 파일 시스템에서 직접 들어볼 수 있는 오디오 목록입니다:

### 4.1 S22 운율 및 단어 잘림 정상화 최종본
- **[최종 권장] 단어 잘림 해결 + 다이내믹 강약 조절 완료**:
  ```text
  /home/dbsdosdb/workspace/Lecture_Auto/data/audio_ref/comparison_s22/slide_02_normalized_fixed.wav
  ```
- **초기 K-ToBI 대본 (어미 롤러코스터 비교용)**:
  ```text
  /home/dbsdosdb/workspace/Lecture_Auto/data/audio_ref/comparison_s22/slide_02_concept_ktobi_prosody.wav
  ```
- **구형 문어체 낭독 음성 (로봇 국어책 읽기 비교용)**:
  ```text
  /home/dbsdosdb/workspace/Lecture_Auto/data/audio_ref/comparison_s22/slide_02_concept_legacy.wav
  ```

### 4.2 S21 스튜디오 노이즈 제거 비교
- **S21 스튜디오 마스터링 음성**:
  ```text
  /home/dbsdosdb/workspace/Lecture_Auto/data/audio_ref/comparison_s21/slide_02_concept_v2_studio_mastered.wav
  ```
- **구형 원본 레퍼런스 음성**:
  ```text
  /home/dbsdosdb/workspace/Lecture_Auto/data/audio_ref/comparison_s21/slide_02_concept_v1_legacy.wav
  ```

---

## 5. 환경변수 설정 가이드

파이프라인 실행 시 적용 가능한 주요 환경변수입니다:

| 환경변수 | 기본값 | 설명 |
| :--- | :---: | :--- |
| `LECTURE_AUTO_REF_VOICE` | `None` (내부 v1 fallback) | 레퍼런스 음성 오버라이드. 스튜디오 정제본 적용 시 `data/audio_ref/reference_v2.wav` 지정 권장. |
| `LECTURE_AUTO_MASTER_AUDIO` | `"1"` | 비디오 합성 시 `audio_mastering.py` 마스터링 체인 적용 여부 (`"1"` 또는 `"0"`). |
| `LECTURE_AUTO_TTS_TEMPERATURE` | `"0.72"` | Raon TTS 런타임 샘플링 온도 (0.70~0.75 권장, 피치 튐 방지). |

---

## 6. 테스트 및 검증 명령어

가상환경(`.venv`) 내에서 아래 명령어들을 실행합니다:

```bash
# 1. 전체 단위/통합 테스트 (526개 테스트 100% PASS 확인)
.venv/bin/pytest tests/

# 2. 코드 스타일 및 린트 검사 (0 errors 확인)
/home/dbsdosdb/.local/bin/ruff check lecture_auto/ tests/ scripts/

# 3. S22 운율 벤치마크 실행 (텍스트 메트릭 분석)
.venv/bin/python scripts/bench_prosody_style.py

# 4. S22 운율 벤치마크 실행 (GPU 실제 음성 합성 포함)
.venv/bin/python scripts/bench_prosody_style.py --synth-audio --device cuda:0
```

---

## 7. 향후 연구 및 백로그: Gemini TTS (NotebookLM) 도입 방안

### 7.1 배경 및 동기
- 로컬 9B 모델(Raon-Speech-9B)은 단일 문장이 길어질 경우 침묵(오디오 붕괴)이 발생하는 구조적 한계가 존재하여 세그먼트 분할이 필수적입니다.
- 반면 Google Gemini Native Audio (Gemini TTS API)는 문장 길이에 구애받지 않고 NotebookLM 수준의 압도적인 자연어 대화/강의 음성을 제공합니다.

### 7.2 요금 계산서 (2026년 10월 공식 요금 기준)
- **오디오 토큰 공식**: 1초 = 25 토큰 (1분 = 1,500 토큰).
- **강의 1개 규모**: 평균 슬라이드 25~30장, 대본 약 9,000자, **재생 시간 20~25분 (약 30,000~37,500 토큰)**.
- **모델별 비용 (환율 1,380원 기준)**:
  * `gemini-3.8-flash-tts` ($9/1M tokens): **강의 1편당 약 370원 ~ 460원** ⭐ (가장 추천)
  * `gemini-2.5-pro-preview-tts` ($20/1M tokens): **강의 1편당 약 820원 ~ 1,030원**
  * ➔ **한 학기 전체(15개 강의)를 제작해도 약 5,500원 ~ 12,000원에 불과하여 경제성이 매우 뛰어남**.

### 7.3 후속 작업 제안
1. Google AI Studio에서 Gemini API Key 발급 및 `.env` 등록.
2. `lecture_auto/tts/gemini_tts.py` 어댑터 구현 (`lecture_auto.tts.base.TTSEngine` 상속).
3. 교수님 육성 오디오를 멀티모달 프롬프트로 전달하여 음색과 억양을 복제하는 파이프라인 검증.

---

**인수인계 완료 상태**: 현재 마스터 브랜치는 모든 테스트가 통과하고, 단어 잘림이 수정되었으며, 원격 저장소(`origin/master`)에 최신 상태로 푸시되어 있습니다.
