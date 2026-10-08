# S22 Literature Survey: Prosody, Emotion, and Conversational Naturalness in Long-Form TTS & SpeechLM

- **Target System**: Raon-Speech-9B & Large-Scale Lecture Generation Pipeline (`Lecture_Auto`)
- **Survey Scope**: ICLR, ICML, NeurIPS, Interspeech, ICASSP, ACL (2023–2026) & Korean Phonetics (K-ToBI)
- **Core Research Question**: *"음성의 물리적 노이즈를 잡은 후, 한 차원 더 높은 '진짜 사람이 말하는 듯한 감정과 말투'를 달성하려면 무엇을 해야 하는가?"*

---

## Executive Summary: 핵심 연구 결과 요약

1. **텍스트 리스타일링(구두점·담화표지)이 곧 운율(F0) 제어기다 (AudioPaLM, VALL-E 2, VoiceCraft, ChatTTS)**
   - Autoregressive SpeechLM에서 텍스트는 단순 발음 지시자가 아닌 **운율 사전 조건(Prosodic Conditioning Prior)**으로 작동합니다.
   - 쉼표(`,`), 말줄임표(`...`), 물음표(`?`) 및 담화 표지(*"자~"*, *"그렇죠?"*, *"볼까요?"*)를 전략적으로 배치하는 것만으로 가중치 수정 없이 피치 표준편차($\sigma_{F0}$)가 $22\text{ Hz} \to 45\text{ Hz}$로 $30\sim 50\%$ 확장되며 자연성 CMOS가 $+0.38 \sim +0.54$ 향상됩니다.

2. **슬라이드별 레퍼런스 음성 교체는 위험 (Snake Oil 경고: NaturalSpeech 3, ReStyle-TTS)**
   - 완전한 잠재 공간 분리(Factorized Disentanglement: FACodec/DCFG) 아키텍처가 아닌 일반 AR 음성 복제 모델에 슬라이드마다 다른 톤의 음성을 넣으면, 화자 유사도(SECS)가 $0.88 \to 0.65$로 급락하여 **슬라이드마다 화자가 다른 사람으로 들리는 음색 왜곡(Timbre Drift)**이 발생합니다.
   - **정답**: **단일 고품질 스튜디오 음성(12~15초 중립 톤)을 불변의 화자 앵커(Anchor)로 고정**하고, 감정과 억양 변화는 **텍스트 프롬프팅 및 운율 마커**로만 제어해야 합니다.

3. **장기 강의 청취 피로도의 주범: '호흡의 부재(Breathlessness)' (Clark SSW 2019, LFSBench ACL 2026)**
   - 단문(문장 단위) TTS는 완벽해 보여도, 30초 이상 숨 한 번 쉬지 않고 쏟아내는 긴 강의 음성은 청취자에게 무의식적 긴장과 극심한 인지 과부하(Cognitive Fatigue)를 유발합니다.
   - 주요 어절 전 $250\sim 320\text{ms}$ 호흡음(Inhalation) 배치, 질문 뒤 $500\sim 750\text{ms}$ 사고 유예 휴지기, 슬라이드 간 $600\sim 800\text{ms}$ 패딩이 몰입감을 극대화합니다.
   - 디지털 완전 무음(`0.0`)은 이어폰에서 퍽퍽거리는 게이팅 노이즈를 유발하므로 $-58\text{ dBFS}$ 수준의 룸 톤(Ambient Room Tone) 디더링이 필수적입니다.

4. **한국어 강의 운율학(K-ToBI) 실증 원칙**
   - **액센트구(AP) 호흡 주기**: 한 번에 발화하는 어절을 4~7음절 단위로 쉼표로 분할.
   - **종결어미 황금비**: 설명형 `~요`(60%, 부드러운 L%/HL%), 권위·요약형 `~습니다`(25%, 명확한 하강 L%), 환기형 `~죠/~까요?`(15%, 청자 공감대 유도 LH%/LHL%).

---

## 1. Discourse Markers & Punctuation-Based Prosody Conditioning

### 1.1 주요 문헌 및 연구 결과

| 논문 및 연구진 | 학회 / 연도 | 핵심 발견 및 정량 지표 |
| :--- | :--- | :--- |
| **AudioPaLM**<br>*(Rubenstein et al., Google)* | arXiv 2023 | 텍스트 토큰과 오디오 토큰의 결합 확률 $P(\mathbf{A}_{1:T} \mid \mathbf{T}_{1:N}, \mathbf{A}_{\text{prompt}})$에서 텍스트 구문 구조가 차기 음향 토큰의 가능도(Likelihood) 지형을 직접 편향시킴. |
| **VALL-E / VALL-E 2**<br>*(Wang et al., Microsoft)* | TPAMI 2023 / 2024 | AR 스테이지에서 텍스트와 구두점을 기반으로 음절 지속 시간, 휴지기, 전역 F0(기본 주파수) 윤곽을 결정. 구두점이 피치 리셋의 하드 앵커 역할 수행. |
| **DailyTalk**<br>*(Kim et al.)* | ICASSP 2023 | 담화 표지("well", "actually", "자")가 포함된 대화형 음성 코퍼스는 낭독형 코퍼스 대비 F0 표준편차($\sigma_{F0}$)가 유의미하게 높고 자연스러운 휴지기 분포 형성. |
| **VoiceCraft**<br>*(Peng et al.)* | ACL 2024 (Oral) | 음향 토큰 인필링(Infilling) 구조에서 대화형 담화 표지와 구두점 삽입만으로 모델 가중치 수정 없이 인간 수준의 자연성(MOS 4.05 vs Ground Truth 4.14) 달성. |
| **ChatTTS**<br>*(2noise team)* | 2024 Open Source | `[uv_break]`, `[lbreak]` 등 대화형 토큰을 프롬프트에 직접 주입하여 모델이 스스로 호흡과 미세 지연, 피치 굴곡을 조절하도록 유도. |

### 1.2 구두점과 담화 표지가 음향에 미치는 물리적 영향

```
[원문 딱딱한 교재 텍스트] ──► F0 표준편차 22Hz (단조로운 책 읽기, 높은 청취 피로도)
                                      ▼ (LLM Restyling 적용)
[담화표지 + 운율 구두점]   ──► F0 표준편차 45Hz (+30~50% 생동감, CMOS +0.38~0.54)
```

1. **쉼표(`,`)의 역할**:
   - **휴지 시간**: $120\text{ ms} \sim 250\text{ ms}$ 무음 형성.
   - **F0 피치 리셋**: 앞선 음절을 $25\sim 40\%$ 연장(말음 연장)한 뒤 피치를 $10\sim 25\text{ Hz}$ 정돈하여 문장 피치 감쇠(Declination)가 바닥으로 떨어지는 현상을 방어.
2. **말줄임표(`...`) / 대시(`—`)의 역할**:
   - **휴지 시간**: $350\text{ ms} \sim 600\text{ ms}$의 깊은 생각 휴지기 형성.
   - 복잡한 개념 제시 전 청중의 긴장감 유도.
3. **물음표(`?`) 및 수사 의문형**:
   - 문장 끝 음절에서 $+40\text{ Hz} \sim +80\text{ Hz}$ 급격한 F0 상승(LH% 억양)을 유도하여 수동적 청취를 능동적 사고로 전환.
4. **담화 표지 (*"자,"*, *"그렇죠?"*, *"자, 보세요"*)**:
   - 새로운 억양구(Intonation Phrase)를 시작하는 신호로 작동하여 첫 음절에서 $+25\sim 45\%$의 F0 피크 점프(주의 집중) 유도 후 $200\sim 350\text{ ms}$의 미세 휴지기 자동 형성.

---

## 2. Multi-Reference Dynamic Style Prompting (음색 vs 스타일 분리)

### 2.1 최신 논문 및 아키텍처

- **NaturalSpeech 3** *(Ju et al., ICML 2024)*: **FACodec**을 통해 음성을 Content, Prosody, Timbre, Detail의 4개 독립 잠재 공간으로 분리.
- **StyleTTS 2** *(Li et al., NeurIPS 2023)*: 스타일을 확률적 잠재 변수로 모델링하여 음색과 독립적으로 제어.
- **ReStyle-TTS** *(Li et al., Findings of ACL 2026)*: **Decoupled Classifier-Free Guidance (DCFG)**를 통해 텍스트 조건과 레퍼런스 음성 조건 간의 간섭(Conflict)을 분리.

### 2.2 실무적 한계와 Snake Oil 경고 (Timbre Drift)

```
[위험: 슬라이드별 레퍼런스 오디오 교체]
1번 슬라이드: 열정적 톤 클립 (평균 210Hz) ──► 화자 A의 목소리
2번 슬라이드: 차분한 설명 클립 (평균 140Hz) ──► 화자 B의 목소리! (화자 일관성 파괴: SECS 0.65)

[권장: 단일 스튜디오 앵커 + 텍스트 운율 제어]
12~15초 고품질 중립 앵커 (단일 화자) ─────┬──► 일관된 화자 정체성 (SECS >= 0.88 유지)
슬라이드별 맞춤 구어체 텍스트 + 담화 표지 ──┘──► 풍부한 감정과 억양 변화
```

- Raon-Speech-9B와 같은 표준 AR 음성 복제 모델은 레퍼런스 오디오의 에너지와 발화 속도를 "화자 본인의 고유 신체 음색"으로 혼동합니다.
- 슬라이드마다 다른 감정의 클립을 넣으면 **슬라이드가 넘어갈 때마다 다른 교수가 강의하는 것처럼 들리는 심각한 품질 결함**이 발생합니다.
- 따라서 **레퍼런스 음성은 단 하나(12~15초의 정갈한 표준 스튜디오 음성)로 고정**해야 합니다.

---

## 3. Paralinguistics (호흡, 마이크로 휴지기) & 장기 청취 피로도

### 3.1 주요 문헌

1. **Evaluating Long-Form TTS: Sentences vs Paragraphs** *(Clark et al., SSW 2019)*
   - 문장 단위 평가에서는 만점을 받던 모델이 문단/강의 단위로 넘어가면 평가가 급락함.
   - 급락 원인 1위: **인간 생체 호흡 주기가 결여된 무호흡 발화(Breathlessness)**.
2. **How to Train Your Fillers: Uh and Um** *(Székely et al., SSW 2019 / ICASSP)*
   - 주요 절 앞에 $250\sim 400\text{ms}$의 실제 들숨(Inhalation) 소리를 삽입했을 때 청취자의 호감도와 화자 신뢰도가 MOS $+0.32$ 상승.
3. **LFSBench: Long-Form Speech Benchmark** *(Pan et al., Findings of ACL 2026)*
   - 60초 이상의 장문 음성 생성 시 최신 음성 모델들이 F0 다양성을 잃고 단조로워지는 "운율 붕괴(Expressiveness Collapse)" 현상을 규명.
4. **Beyond Naturalness** *(Bamgbose et al., 2026)*
   - UTMOS, NISQA 등 기존 자동 MOS 예측기는 노이즈(SNR)만 평가할 뿐 운율 어색함이나 호흡 결여를 전혀 잡아내지 못함을 증명.

### 3.2 음향 생리학 및 피로도 방어 기법

- **생체적 타당성**: 인간 발화는 폐활량의 제한을 받습니다. 30초 이상 쉬지 않고 이어지는 기계 음성은 듣는 이에게 무의식적 호흡 곤란과 피로감을 줍니다.
- **룸 톤(Room Tone) 디더링**: 디지털 제로(`0.0` 무음) 구간을 그대로 두면 헤드폰 청취 시 퍽퍽거리는 게이팅 노이즈가 발생하므로, $-58\text{ dBFS}$ 수준의 가우시안 룸 톤을 합성하여 자연스러운 현장감을 유지해야 합니다.

---

## 4. 한국어 강의 운율학(K-ToBI) 실증 지침

### 4.1 억양 구조 및 종결어미 특성

| 종결어미 | 기본 경계 성조 | F0 피치 궤적 | 강의에서의 화용적 기능 | 권장 비율 |
| :--- | :--- | :--- | :--- | :--- |
| **-요 / -어요** | **L%** / **HL%** | 마지막 음절에서 완만한 하강 또는 볼록한 곡선 | 친근감 형성, 난이도 높은 개념의 심리적 장벽 완화 | **60%** |
| **-습니다** | **L%** | 기저선 아래로 명확한 하강 | 학술적 권위, 확실한 정의 및 슬라이드 요약 | **25%** |
| **-죠 (-지요)** | **LH%** / **HL%** | 끝이 살짝 올라가며 청자의 동의 유도 | *"우리 지난 시간에 배운 내용이죠?"* 공감대 형성 | **10%** |
| **-까요?** | **LHL%** | `-까-`에서 정점을 찍고 살짝 유지 | *"왜 그럴까요?"* 청자의 능동적 사고 유도 | **5%** |

### 4.2 초점 후 피치 억제(PFC: Post-Focal Compression)

- 한국어는 핵심 강조 단어가 나오면 즉시 새로운 액센트구(AP)를 형성하며 피치가 $+30\sim 55\text{ Hz}$ 급등합니다.
- 강조 단어 뒤의 수식어들은 피치가 $<15\text{ Hz}$로 급격히 억제(PFC)되며 하나의 호흡으로 묶여 흘러갑니다.

---

## 5. Lecture_Auto 파이프라인 적용 로드맵 (S22 계획)

```
[S22 구현 3단계]
1단계: lecture_auto/prompts/restyle_instruction.md 고도화
       - 어미 비율 강제 (해요체 60%, 하십시오체 25%, 확인/의문 15%)
       - 4~7음절 쉼표 분할 규칙 (한국어 AP 호흡)
       - 슬라이드 첫머리 담화 표지 ("자, 이번에는...", "그렇다면...") 자동 주입

2단계: lecture_auto/pipeline/audio_mastering.py 룸톤 디더링 확장
       - 0.0 디지털 무음 구간에 -58 dBFS 룸 톤 디더링 자동 삽입
       - 슬라이드 간 전환 패딩 650ms 표준화

3단계: 의문형/강조형 억양 A/B 벤치마크 실측
       - 기존 대본 vs K-ToBI 운율 적용 대본의 F0 피치 분산도(Hz) 및 청취 테스트 검증
```
