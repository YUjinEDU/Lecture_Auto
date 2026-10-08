# S21 REPORT — 강의 음성 품질 고도화 및 노이즈 제거 (완료 보고)

- **작성일**: 2026-10-08
- **목표**: 교수님이 지적하신 음성의 늘어짐, 어눌함, 이상한 노이즈(쇳소리, 기계음, 룸 잔향)를 제거하여 "자연스럽고 깨끗한 스튜디오 강의 음성" 달성.
- **테스트 결과**: 전체 518개 pytest **100% 통과** (기존 511개 + 신규 7개, 무회귀 확인).

---

## 1. 수행 작업 요약

### 1) 참조 음성(Reference Audio) 스튜디오 정제 체인 구현 및 `reference_v2.wav` 빌드
- **원인 규명**: 기존 `reference_v1.wav`의 강의실 배경 에어컨 험 노이즈 및 룸 잔향이 ECAPA-TDNN을 통해 생성 음성 전체로 전파(Noise Bleed-Through)되던 문제.
- **조치**:
  - `scripts/build_voice_reference.py`에 `--clean-studio` 파이프라인 추가 (80Hz HPF + FFT denoiser + 320Hz 룸 박시 컷 + 3kHz 명료도 EQ).
  - 기존 `reference_v1.wav`는 그대로 보존하여 기존 캐시 무회귀 보장.
  - 신규 고품질 참조 음성 `data/audio_ref/reference_v2.wav` 및 `reference_v2.wav.json` 생성 완료.

### 2) 순수 SciPy 기반 오디오 마스터링 체인 구축 (`lecture_auto/pipeline/audio_mastering.py`)
- **Zero VRAM / Zero Dependency 원칙**: PyTorch CUDA OOM 위험을 원천 차단하기 위해 무거운 신경망 대신 `scipy.signal` 기반 DSP 필터 설계.
- **5단계 마스터링 체인**:
  1. 80Hz 2차 Butterworth High-Pass Filter (마이크 럼블 및 DC 오프셋 제거)
  2. 320Hz Biquad Peaking EQ (-1.8dB, Q=1.2) (강의실 룸 박시 공진 제거)
  3. 3000Hz Biquad Peaking EQ (+1.5dB, Q=1.0) (보컬 명료도 및 자음 선명도 향상)
  4. 6200Hz Split-band De-esser (-2.5dB, Q=2.0) (치찰음 "ㅅ, ㅆ, ㅊ" 과도한 쇳소리 감쇄)
  5. Soft-knee 리미터 및 ITU-R BS.1770-4 (-20 LUFS) 음량 정규화
- **정밀 역방향 VAD 테일 트림 (`trim_speech_tail`)**:
  - 단일 스파이크 클릭 노이즈로 인해 늘어지는 어말 환각(Mumbling tail)을 50ms 윈도우 에너지 기반으로 감지 및 트림.
  - 한국어 종성 받침 보존을 위한 70ms 안전 패드 및 15ms 코사인 페이드아웃 적용.

### 3) 실제 A/B 비교 벤치마크 검증 (`scripts/bench_voice_quality.py`)
- GPU 0번(RTX A6000)에서 실제 강의 대본 2종을 대상으로 [기존 v1 vs S21 스튜디오 마스터링 v2] 음성 합성 및 측정:
  - `slide_01_intro`:
    - 기존 v1 Legacy: Noise Floor **-38.8 dB**
    - **S21 Studio v2: Noise Floor -68.4 dB (29.6 dB 노이즈 감쇄 달성!)**
  - `slide_02_concept`:
    - 기존 v1 Legacy: Noise Floor **-61.4 dB**
    - **S21 Studio v2: Noise Floor -77.0 dB (15.6 dB 노이즈 감쇄 달성!)**
  - 생성된 비교 청취 파일 위치: `data/audio_ref/comparison_s21/`

---

## 2. 산출물 및 생성된 파일 목록

| 파일 | 설명 |
|---|---|
| `docs/hardening/stages/S21_audio_quality/DEBATE_AND_RESEARCH.md` | 연구원 vs 시스템 아키텍트 에이전트 간의 심층 리서치 및 토론 기록 |
| `lecture_auto/pipeline/audio_mastering.py` | 5단계 스튜디오 마스터링 DSP 및 테일 트림 모듈 |
| `tests/test_audio_mastering.py` | 마스터링 체인 단위 테스트 (6개 케이스) |
| `scripts/build_voice_reference.py` | `--clean-studio` 옵션 추가된 레퍼런스 빌더 |
| `data/audio_ref/reference_v2.wav` | 스튜디오 클리닝이 적용된 신규 고품질 참조 음성 |
| `data/audio_ref/reference_v2.wav.json` | 신규 참조 음성 SHA-256 및 필터 메타데이터 |
| `scripts/bench_voice_quality.py` | A/B 비교 청취 음성 생성 벤치마크 도구 |
| `data/audio_ref/comparison_s21/*.wav` | 실제 청취 비교용 A/B 음성 파일 4개 |
