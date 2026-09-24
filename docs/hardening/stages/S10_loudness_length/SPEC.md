# S10 SPEC — 조각별 음량 보정 + 긴 공백 줄이기 + 분량 보정 (D-16)

근거(감독 실측, 2026-09-25, 04-1 제작 결과):
- 04-1 불합격 4장은 전부 슬라이드 단위 "silence". 해당 구간을 잘라 STT하면 5번 7.5s·16번 4.8s·23번 3.0s는 **문장 전체가 들어 있는 조용한 조각**(말소리 p90 대비 −18~−20dB). 21번 2.9s(−27dB)·16번 2.0s(−33dB)만 진짜 무음.
- 원인: 조각 raw 음량이 제각각인데(`raon_tts.py` 주석: −28~−41 LUFS) 음량 보정은 이어붙인 슬라이드 전체에 한 번만 → 작게 나온 조각이 청취자에게 음량 저하로 들리고 gate에는 무음으로 보임.
- 분량: 04-1 대본 15,873자 / 실제 2,116s = **7.5자/초**(200ms 쉼 포함 최종 음성 기준). 대본 생성은 계획 예산(40분×7.0자) 대비 94.5%.

## 작업 항목
### S10-a 조각별 음량 보정
- `synthesize_raon_slide`: 각 조각(합격본·차선책·redraw 채택본 모두)을 이어붙이기 **전에** `_loudness_normalize`로 `_TARGET_LUFS`에 맞춘다. 슬라이드 전체 보정은 그대로 유지.
- redraw 판정(슬라이드 기준 energy_reference로 "poor against the slide")은 조각 보정 **후** 이어붙인 음성 기준으로 계산되게 한다.
- 0.4s 미만 조각 등 LUFS 불가 시 기존 함수 동작(그대로 반환) 유지.

### S10-b 긴 공백 줄이기
- 이어붙이고 보정한 슬라이드 음성에서, 슬라이드 기준 무음 프레임(`_RELATIVE_VOICED_THRESHOLD`×p90 미만, 50ms 프레임 — gate와 같은 정의)이 `_MAX_PAUSE_S = 1.0`초보다 길게 이어지면 그 구간을 `_MAX_PAUSE_S`로 줄인다(구간 가운데를 잘라냄, 경계는 10ms 정도 크로스페이드로 딸깍 소리 방지).
- 적용은 슬라이드 gate(`_slide_gate_failures`) **전에**. 줄인 개수·줄인 총 초를 `SlideQC`에 선택 필드로 기록(`pauses_shortened: int = 0`, `pause_seconds_removed: float = 0.0`) — 스키마 추가만, 삭제 금지.
- 근거: 조각은 이제 STT로 내용이 확인되므로(D-15) 남는 긴 저에너지 구간은 내용 없는 공백.

### S10-c 분량 보정 (대본 예산 속도 분리)
- `script_gen.SPEECH_CHARS_PER_SECOND`(대본 예산) = **7.5**(최종 음성 실측). `raon_tts._CHARS_PER_SECOND`(조각 gate 기대 길이) = 7.0 **유지**. 두 값의 동기화 테스트는 "의도적으로 분리됨"을 확인하는 테스트로 바꾸고 양쪽 주석에 근거 기록.
- `scripts/batch_generate_lectures.py`: `TARGET_MINUTES = 40.0`은 그대로 두고, 강의 계획에 넘기는 분을 `TARGET_MINUTES * PLAN_LENGTH_CALIBRATION`(= 1.06, 대본 생성 94.5% 미달 보정, 04-1 실측 주석)으로.

### S10-d 버전
- `TTS_SYNTH_VERSION = "v13-seg-loudnorm-pausecap"`.

## 필수 테스트 (mock만)
1. 음량이 다른 두 조각(예: −20 / −35 LUFS 합성 사인파+잡음) → 이어붙인 결과에서 두 구간 LUFS 차 < 1.5dB
2. 1.0s 초과 무음 구간 → 1.0s로 줄고, 1.0s 이하 공백은 불변, qc에 개수·초 기록
3. 조각 보정 후 조용한 조각이 더 이상 슬라이드 gate의 silence로 잡히지 않음(기존엔 잡히는 입력으로)
4. 속도 상수 7.5/7.0 분리 확인, 계획에 넘기는 분 = 40×1.06
5. 기존 테스트 전부 통과(바뀐 기대값은 이유와 함께 보고)

## 금지
- 조각 합격 판정(D-15)·세그먼트 분할·시드 규칙 변경. 실제 GPU/LLM/STT, `data/`·`output/` 쓰기, `data/audio_ref/**`, AGENTS.md·docs/ 수정, 새 의존성.
