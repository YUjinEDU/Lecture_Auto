# S22 Architecture Debate & Technical Specification: Korean Lecture Prosody, Conversational Restyle & Paralinguistic Audio Mastering

**Stage**: S22 — Korean Lecture Prosody & Conversational Restyle  
**Date**: 2026-10-08  
**Participants**:
- **Speech Prosody & Acoustics Researcher** (음성학 및 음향 연구원)
- **Pipeline Systems & Zero-Regression Architect** (파이프라인 무회귀 시스템 아키텍트)
- **LLM Prompt & Korean Pedagogy Engineer** (대본 리스타일링 및 프롬프트 엔지니어)

---

## 1. Debate Agenda & Problem Statement

S21에서 오디오 마스터링(80Hz HPF, 320Hz Peaking EQ, 3000Hz Peaking EQ, 6200Hz De-esser, Soft-knee 투명 리미터, 테일 트림)을 통해 **신호 레벨의 노이즈 플로어를 29.6 dB 감쇄**시키며 스튜디오 수준의 정갈함을 확보했다.

하지만 사용자 및 교수님의 핵심 니즈:
> *"이상한 노이즈 없는 것은 해결되었다. 하지만 진짜 사람이 말하는 것 같은 자연스러움, 감정, 사람의 말투로 발전하려면 무엇을 해야 하는가?"*

이에 대해 3명의 엔지니어가 시스템 무회귀성, 음향학적 원리, 런타임 효율성 관점에서 치열하게 토론한다.

---

## 2. Agent Debate Log

### Round 1: 슬라이드별 동적 레퍼런스(Dynamic Reference) vs 단일 고정 앵커(Single Anchor)

- **LLM Prompt Engineer**:
  > "슬라이드 1번(도입부)에는 활기차고 에너지 넘치는 교수님의 오디오 클립을 넣고, 슬라이드 2번(개념 정의)에는 차분하고 진중한 클립을 넣으면 슬라이드 성격에 맞게 감정이 조절되지 않을까요?"

- **Speech Prosody Researcher**:
  > "절대 안 됩니다. 그것은 음성 합성 분야에서 대표적인 **'Snake Oil(잘못된 환상)'**입니다.
  > 최근 ReStyle-TTS(ACL 2026)와 NaturalSpeech 3(ICML 2024) 연구에서 규명되었듯, 완전한 Factorized Disentanglement(FACodec/DCFG) 구조가 아닌 일반 Autoregressive 음성 복제 모델(Raon-Speech-9B 포함)은 레퍼런스 음성의 피치와 에너지를 화자의 고유 음색(Vocal Tract Anatomy)으로 해석합니다.
  > 슬라이드마다 레퍼런스 클립을 바꾸면 화자 유사도(SECS)가 0.88에서 0.65로 폭락합니다. 즉, 1번 슬라이드가 끝나고 2번 슬라이드로 넘어갈 때 **'다른 교수가 말하는 것 같은 목소리 변형'**이 발생합니다."

- **Pipeline Systems Architect**:
  > "연구원의 지적에 100% 동의합니다. 또한 시스템 관점에서도 레퍼런스 오디오를 슬라이드별로 분기하면:
  > 1. 캐시 키 계산 시 레퍼런스 해시가 슬라이드마다 달라져 캐시 관리가 파편화됩니다.
  > 2. 레퍼런스 오디오 파일 간의 룸 앰비언스 차이, 마이크 거리 차이로 인해 슬라이드 연결부에서 급격한 배경음 단절이 일어납니다.
  > **결론**: S21에서 구축한 정갈한 스튜디오 음성(`reference_v2.wav`)을 **전 슬라이드 단일 불변 앵커**로 고정하고, 감정과 억양 변화는 오직 **대본의 구어체 구조와 운율 마커**로만 제어해야 합니다."

---

### Round 2: 대본 리스타일링(`restyle.py`)과 K-ToBI 억양학의 통합

- **Speech Prosody Researcher**:
  > "한국어 억양 체계인 K-ToBI(Sun-Ah Jun)에 따르면, 한국어 청취자가 가장 자연스럽게 느끼는 강의 억양은 **액센트구(AP) 주기**와 **종결어미 억양곡선**입니다.
  > 1. **AP 호흡 분할**: 한 호흡에 쏟아내는 글자를 4~7음절 단위로 쉼표(`,`)로 분할하면 모델이 $150\sim 200\text{ms}$의 미세 휴지와 함께 F0 피크 리셋을 수행합니다.
  > 2. **종결어미 황금비**:
  >    - `~요 / ~어요` (60%): 친근한 설명 (L%/HL% 완만한 하강)
  >    - `~습니다` (25%): 신뢰감 있는 권위와 마무리 (L% 하강)
  >    - `~죠 / ~까요?` (15%): 청자 주의 환기 및 공감대 형성 (LH%/LHL% 피치 상승)
  > 3. **담화 표지**: 슬라이드 시작 시 *'자, 이번에는...'*, 전환부에서 *'그렇다면 왜 그럴까요?'*를 넣으면 문장 시작부 F0가 30~50Hz 부스트되어 강의의 활력이 생깁니다."

- **LLM Prompt Engineer**:
  > "현재 `lecture_auto/pipeline/restyle.py`와 `lecture_auto/prompts/restyle_instruction.md`가 이미 존재합니다.
  > 기존 규칙은 단순히 `합니다/습니다`를 줄이고 `그래서/이제`를 늘리는 것에 치중되어 있었습니다.
  > 이 프롬프트를 K-ToBI 강의 운율 지침으로 업그레이드하되, **글자 수 제약(원문의 95%~108%)**, **전문 용어 및 영어 보존**, **사실 왜곡 금지** 원칙을 엄격하게 유지해야 합니다."

- **Pipeline Systems Architect**:
  > "좋습니다. `restyle.py`는 이미 LLM 출력 검증 게이트(`compute_metrics`, 글자 수 비율 체크, 영어 단어 일치 체크)를 갖추고 있습니다.
  > 프롬프트 템플릿에:
  > - `~요`(60%), `~습니다`(25%), `~죠/~까요`(15%) 비율 가이드
  > - 긴 복문 금지 및 4~7음절 쉼표 호흡 분할 가이드
  > - 슬라이드 첫머리 담화 표지 자연스러운 배치
  > 를 추가하고, `RestyleResult` 메트릭에 `yo_ratio`, `subnida_ratio`, `question_ratio`를 산출하도록 안전하게 확장하면 기존 테스트와 100% 호환됩니다."

---

### Round 3: 오디오 마스터링 내 룸 톤(Room Tone) 디더링 및 슬라이드 간 패딩

- **Speech Prosody Researcher**:
  > "인간 귀는 완전한 디지털 제로(`0.0` 무음) 구간을 들으면 이어폰에서 게이트가 닫히는 듯한 압력감과 이질감을 느낍니다(Clark SSW 2019).
  > 실제 스튜디오 녹음은 항상 미세한 공기감(Room Tone)이 흐릅니다.
  > 따라서 `audio_mastering.py`에서 테일 트림 후 뒤에 붙는 패딩 및 슬라이드 간 연결 무음 구간에 **$-58\text{ dBFS}$ 수준의 잔잔한 가우시안 룸 톤(Low-pass filtered ambient dither)**을 합성해야 합니다."

- **Pipeline Systems Architect**:
  > "기술적 제약 사항을 확인하겠습니다:
  > 1. **VRAM 점유**: 0 VRAM이어야 합니다. `scipy.signal`과 `numpy` 기반 CPU DSP로 3ms 이내에 처리되어야 합니다.
  > 2. **무음 보존**: 입력이 완전한 무음(zero audio)일 때는 룸톤을 덧칠해선 안 됩니다.
  > 3. **클리핑 방지**: 룸톤 가산 후 피크가 1.0을 넘지 않도록 리미터 파이프라인 안쪽에 안전하게 위치해야 합니다.
  > 4. **슬라이드 간 전환 패딩**: 현재 `video.py`에서 슬라이드 간 연결 시 기본 650ms의 표준 패딩을 제공하도록 정돈합니다."

---

## 3. Consensus & Implementation Action Plan (S22)

세 엔지니어 전원 일치로 다음 3개 액션 플랜을 확정:

### Phase 1: `docs/` 및 아키텍처 토론 기록 확정 및 커밋
- `LITERATURE_SURVEY.md` 및 `DEBATE_AND_RESEARCH.md` 작성.
- 기존 S21 변경사항과 함께 1차 커밋 실행.

### Phase 2: `audio_mastering.py` 룸 톤(Room Tone) 디더링 엔진 구현 & 단위 테스트
- CPU 기반 룸 톤 생성기 (`synthesize_room_tone`: LPF 1200Hz 가우시안 노이즈, -58 dBFS).
- `master_lecture_audio` 체인에 룸 톤 디더링 통합 (선택적 활성화 지원).
- `tests/test_audio_mastering.py`에 무음/유음 룸톤 검증 테스트 추가.

### Phase 3: `restyle_instruction.md` 및 `restyle.py` K-ToBI 운율 지침 고도화
- K-ToBI 억양구 쉼표 분할, 어미 황금비(요 60%, 습니다 25%, 죠/까요 15%), 담화 표지 유도.
- 메트릭 계산기에 억양 분포 추적 필드 추가.
- `tests/test_restyle.py` 무회귀 통과 검증.

### Phase 4: A/B 벤치마크 및 비교 측정
- 기존 대본 vs S22 K-ToBI 운율 대본의 피치 분산도 실측 및 비교 청취 리포트 작성.
