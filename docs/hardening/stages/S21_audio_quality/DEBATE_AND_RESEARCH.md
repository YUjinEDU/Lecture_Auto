# S21 DEBATE & RESEARCH — 강의 음성 품질 고도화 연구 및 토론 기록

- **작성일**: 2026-10-08
- **목표**: 교수님이 지적하신 "늘어짐, 어눌함, 이상한 노이즈(쇳소리, 기계음, 룸 잔향)"를 근본적으로 해결하여 진짜 사람 같은 스튜디오 음성 달성.
- **참여 에이전트**:
  - `Agent A`: Senior Speech & Audio Processing Researcher (음향 신호 처리 및 신경망 음성 모델 관점)
  - `Agent B`: Senior Pipeline & Production Systems Architect (Lecture Auto 파이프라인 및 무회귀 안정성 관점)

---

## 1. 핵심 쟁점별 토론 및 팩트 체크

### 쟁점 1: 참조 음성(Reference Audio)의 노이즈 전파 (Noise Bleed-Through)

* **Agent A (연구원)**:
  - 현재 쓰는 `reference_v1.wav`는 실제 강의실 녹음(`professor_past_lecture_2025.wav`)에서 8.7초를 따온 것.
  - Raon-Speech-9B는 ECAPA-TDNN(192차원)으로 화자 임베딩을 추출하는데, 강의실의 룸 잔향(RT60 > 0.4s)과 배경 HVAC 험 노이즈를 "화자 고유의 음향 특징"으로 함께 학습·인코딩함.
  - 이로 인해 생성되는 모든 슬라이드 음성에 텁텁한 박시(Boxy) 잔향과 쇳소리/노이즈 플로어가 묻어남.
  - **해결책**: 참조 음성을 DeepFilterNet 3(감쇄 12~15dB 제한) 또는 스튜디오급 신호처리로 오프라인 1회 정제하여 노이즈와 룸 잔향을 제거해야 함.
* **Agent B (아키텍트)**:
  - **경고**: `reference_v1.wav` 파일을 인플레이스로 덮어쓰면 `ref_voice_bytes` 해시가 변경되어 **기존 배치 수백 개 슬라이드의 캐시가 전면 무효화**됨. 또한 `reference_v1.wav.json`의 SHA-256 검증이 깨짐.
  - **합의 결론**:
    1. 기존 `reference_v1.wav`는 그대로 보존 (기존 배치 무회귀 보장).
    2. 정제된 참조 음성은 `data/audio_ref/reference_v2.wav`로 신규 생성하고 sidecar JSON 메타데이터를 함께 기록.
    3. `REF_VOICE_VERSION` 환경변수 또는 파라미터로 선택 가능하게 격리.

---

### 쟁점 2: 샘플링 온도($T$) 및 메탈릭 쇳소리/어눌함

* **Agent A (연구원)**:
  - 현재 `TTS_TEMPERATURE = 0.85`를 사용 중이나, `modeling_raon.py` 분석 결과 **`top_p` (Nucleus Sampling)가 전혀 적용되지 않고 있음** (`top_p = 1.0` 기본값).
  - Mimi 32-RVQ 코덱에서 낮은 확률의 롱테일 토큰이 샘플링될 때 고주파 양자화 노이즈(metallic chirping/쇳소리)가 유발됨.
  - 또한 내장된 `ras_enabled` (반복 방지 샘플링)가 페널티 없이 동일한 확률 분포에서 다시 multinomial draw하는 버그성 로직을 가지고 있음.
  - **해결책**: $T = 0.72 \sim 0.75$, $\text{top\_p} = 0.88 \sim 0.90$ 도입 권고.
* **Agent B (아키텍트)**:
  - **경고**: `TTS_TEMPERATURE = 0.85`는 `_tts_cache_key`에 명시적으로 들어가 있음. 온도를 바꾸면 난수 시드 경로 전체가 바뀌어 기존에 통과하던 슬라이드가 탈락할 수 있음.
  - **합의 결론**:
    1. 당장 글로벌 상수를 변경하지 않고, 새 버전(v14) 또는 A/B 비교 벤치마크 스크립트(`scripts/bench_voice_quality.py`)에서 샘플을 생성하여 청취 평가.
    2. 입증된 후 점진적으로 버전 범프(`TTS_SYNTH_VERSION`)와 함께 채택.

---

### 쟁점 3: 문장 끝 늘어짐(End-of-Utterance Dragging) 및 테일 환각

* **Agent A (연구원)**:
  - 텍스트 토큰이 소진된 후 어텐션이 분산되면서 저에너지 발화(vocal fry, 중얼거림, 기계음)의 어트랙터에 빠짐.
  - Raon 모델 자체의 `_trim_last_frame`은 1프레임(80ms)만 잘라내므로 0.5~2초간 질질 끄는 테일을 막지 못함.
  - **해결책**: 역방향 다중 피처 VAD (단시간 에너지 + 스펙트럴 플럭스 + 영교차율 ZCR)를 통해 실제 발화가 끝난 지점을 역추적하고 60~80ms 행오버 후 15ms 코사인 페이드아웃 적용.
* **Agent B (아키텍트)**:
  - **경고**: 한국어는 종성 받침(-다, -요, -습니다 등)이나 호흡 소리가 어말에 위치하므로, 거칠게 에너지만 보고 자르면 끝 음절이 잘려 STT 게이트에서 `cer > 0.25`로 탈락함.
  - **합의 결론**:
    1. 60~80ms 안전 행오버(Safety Pad)를 철저히 보장.
    2. STT 게이트 통과 여부를 회귀 테스트로 검증.

---

### 쟁점 4: 마스터링 체인 (DSP vs 신경망) 및 VRAM 안정성

* **Agent A (연구원)**:
  - 방송/강의 스튜디오 품질을 위해 5단계 체인 제안:
    (1) 80Hz HPF (럼블 제거)
    (2) 320Hz 노치(-1.8dB) + 3kHz 존재감(+1.5dB) EQ
    (3) 5.5~7.5kHz 디에서(De-esser: 치찰음 억제)
    (4) 소프트니 컴프레서 (다이내믹스 균일화)
    (5) -20 LUFS 노멀라이즈
* **Agent B (아키텍트)**:
  - **절대 원칙**: **CUDA 신경망 디노이저(Demucs 등)는 런타임 배치에 절대 사용 금지.**
    - Raon-Speech-9B가 이미 VRAM 20~22GB를 차지하고 있어 추가 딥러닝 모델 로드 시 즉시 CUDA OOM 발생.
  - `scipy.signal` (Butterworth SOS 및 IIR Biquad)은 표준 CPU 연산으로 0 VRAM, 지연시간 < 5ms로 수행 가능 (`pyproject.toml`에 `scipy` 이미 포함).
  - **순서 원칙**: STT 내용 일치 검사(`evaluate_transcription`)가 끝난 뒤, 최종 저장 및 비디오 병합 직전에 마스터링 체인을 적용해야 게이트 왜곡을 방지할 수 있음.
* **합의 결론**:
  - 순수 Python/SciPy 기반의 고속 스튜디오 마스터링 DSP 체인(`lecture_auto/pipeline/audio_mastering.py`) 구축.
  - 무거운 GPU 의존성 제로, 완전 결정론적(Deterministic) 처리.

---

## 2. 확정된 실천 계획 (S21 Roadmap)

1. **Step 1: 정제된 참조 음성(`reference_v2.wav`) 오프라인 빌드**
   - 원본 교수님 음성에서 80Hz HPF + 스튜디오 디노이징/디리버브 적용.
   - `data/audio_ref/reference_v2.wav` 및 `reference_v2.wav.json` 생성.
2. **Step 2: 순수 SciPy 기반 오디오 마스터링 모듈 구현**
   - `lecture_auto/pipeline/audio_mastering.py` 구현.
   - HPF 80Hz + 320Hz 박시 컷 + 6kHz 치찰음 디에싱 + 부드러운 레벨링.
3. **Step 3: 테일 환각 트림 로직 정밀화 (`_trim_tail_hallucination`)**
   - 어말 60~80ms 안전 패드 보장 역방향 VAD.
4. **Step 4: 비교 청취 벤치마크 스크립트 작성 및 A/B 테스트**
   - 동일 슬라이드 대본 2~3개에 대해 [기존 v1 vs S21 고품질 체인] 생성 비교.
   - 노이즈, 늘어짐, 선명도 비교 청취 파일 추출.
