# S11 SPEC — 슬라이드 단위 판정 오판 2건 수정

근거(04-2 실제 제작, 2026-09-25, 감독 확인):
- 불합격 3장 모두 조각 단위는 전부 합격(fallback 0).
- 4번(1,654자, 3:48)·19번(2,365자, 5:08): 슬라이드 전체 STT 전사가 870자·835자에서 끊김 → `stt_short(0.53/0.35)`로 불합격. **긴 음성 전체 STT가 앞부분만 전사**하는 것이 원인(음성 결함 아님).
- 15번: 대본 253자, target_seconds 20 → 음성 37s가 `long(37s>20s)`. 대본을 정상 속도로 다 읽은 것이고 음성 결함 아님(대본이 계획보다 김).

## 작업 항목
### S11-a 슬라이드 STT를 조각 STT로 대체
- 조각 STT(D-15)가 실제로 쓰인 슬라이드는 **전체 음성 STT를 하지 않는다.** 대신 `SlideQC.stt`(`TranscriptionCheck`)를 조각 결과로 채운다:
  status = 모든 조각의 채택본이 STT pass면 "pass", 하나라도 fail이면 "fail", 조각 STT가 없었던 조각이 있으면 "unavailable"; cer = 조각 글자 수 가중 평균; transcript = 조각 전사를 공백으로 이어 붙임; reasons = 불합격 조각의 이유를 `seg{index}:{reason}` 형태로.
- 이 슬라이드 STT 결과가 gate 이유에 들어가는 방식은 기존과 같게(fail이면 reasons가 gate에 반영).
- `SegmentQC`에 선택 필드 `stt_status: str | None = None`, `cer: float | None = None`(채택된 시도의 값) 추가. 스키마 삭제 금지.
- 조각 STT를 못 쓴 경우(verify_stt False / stt 없음)는 기존 전체 STT 경로 그대로.

### S11-b 슬라이드 "long" 기준
- `_slide_gate_failures`의 long 판정 기준을 `max(max_seconds, char_count / _CHARS_PER_SECOND) × _MAX_DURATION_RATIO`로. (폭주·늘어짐 검출 목적은 유지, 대본이 계획보다 긴 것은 음성 결함으로 보지 않음.)
- 음성이 `max_seconds × _MAX_DURATION_RATIO`를 넘으면 경고 로그만(“대본이 계획 분량보다 김”).

### S11-c 버전은 올리지 않는다
- 합성 결과(바이트)는 바뀌지 않고 합격 판정만 바뀌므로 `TTS_SYNTH_VERSION` 유지(올리면 04-2의 합격 슬라이드 16장이 전부 재합성 대상이 됨). 이유를 코드 주석에.

## 필수 테스트 (mock만)
1. 조각 STT 사용 시 전체 음성 STT 미호출(STT mock 호출 수 = 조각 수), SlideQC.stt가 조각 가중 CER·이어붙인 전사로 채워짐
2. 조각 하나가 STT fail로 차선책이면 슬라이드 stt status "fail", reasons에 `seg{n}:` 포함
3. 조각 STT 없음 → 기존 전체 STT 경로
4. 대본 253자·max_seconds 20·음성 37s → long 아님, 음성이 글자 기준 1.35배 초과면 long
5. 기존 테스트 전부 통과
## 금지
- 조각 판정·분할·시드·음량/공백 처리 변경, 실제 GPU/LLM/STT, `data/`·`output/`, AGENTS.md·docs/, 새 의존성.
