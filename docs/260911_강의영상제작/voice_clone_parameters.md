# 교수님 음성 복제(Voice Cloning) 최적 파라미터 및 레퍼런스 사양서

- **선정된 최적 모델**: `sample_v3_combined` (사용자 청음 검증 완료)
- **적용 모델**: `KRAFTON/Raon-Speech-9B` (9B 파라미터 End-to-End Speech-LLM)

---

## 1. 레퍼런스 오디오(Reference Audio) 사양

가장 자연스럽고 풍부한 음색을 위해 스마트폰 최신 육성과 과거 실전 강의 음성을 결합한 **하이브리드 레퍼런스**를 구축하여 적용합니다.

- **최종 레퍼런스 파일 경로**: `data/audio_ref/test_variants/ref_combined.wav`
- **총 재생 시간**: 47.64초
- **오디오 포맷**:
  - Sample Rate: 24,000 Hz (Raon-Speech native sample rate)
  - Channels: 1 (Mono)
  - Bit Depth: 16-bit PCM (`pcm_s16le`)
- **구성 요소**:
  1. `260911_교수님음성 .m4a` (스마트폰 최신 녹음, 17.69초 정규화본): 교수님의 최신 음색 지문 제공
  2. `공감과디브리핑-AI활용현업문제해결-2025.m4a` (20분 시점 또렷한 강의 발화, 30.00초): 마이크 직음의 명료한 딕션 및 강의 발성 제공
- **전처리 파이프라인 (FFmpeg)**:
  - `silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB`: 잡음 및 선두 무음 제거
  - `loudnorm`: EBU R128 방송 표준 음량(-23 LUFS) 정규화
  - `concat`: 두 음성 무손실 병합

---

## 2. 모델 인퍼런스(Inference) 최적 파라미터

Raon-Speech-9B 파이프라인 호출 시 적용되는 핵심 파라미터 값입니다:

| 파라미터 | 최적 설정값 | 기본값 | 설명 및 효과 |
| :--- | :---: | :---: | :--- |
| **`device`** | `cuda:0` | - | NVIDIA RTX A6000 (48GB VRAM) 전용 가속 |
| **`dtype`** | `bfloat16` | - | 메모리 절약(약 18GB VRAM) 및 최고 속도 연산 |
| **`temperature`** | **`0.85`** | 1.2 | 발음의 안정성과 딕션 정확도를 높이고 톤 튐 방지 |
| **`ras_enabled`** | `True` | False | Repetition Avoidance Search: 음소 반복/더듬거림 방지 |
| **`ras_window_size`**| `50` | 50 | 반복 감지 윈도우 크기 |
| **`speaker_audio`** | `ref_combined.wav` | None | SpeechBrain ECAPA-TDNN 화자 임베딩 벡터 주입 |
| **`sampling_rate`** | `24000` | 24000 | 고품질 24kHz 모노 WAV 출력 |

---

## 3. 오디오 후처리 및 영상 합성 연계
- 슬라이드별 생성된 WAV는 ffmpeg 영상 합성 시 AAC 192k 고음질로 인코딩되어 MP4 비디오 스트림과 완벽히 동기화됩니다.
