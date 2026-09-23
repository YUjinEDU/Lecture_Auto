# S9 SPEC — 조각 합격 판정을 받아쓰기 기반으로 (D-15)

근거: `EXPERIMENT.md`(같은 폴더), `../../decisions/DECISIONS.md` D-15. 기준: master HEAD.
대상: `lecture_auto/pipeline/raon_tts.py`, `lecture_auto/pipeline/script_gen.py`, `scripts/batch_generate_lectures.py`, 관련 테스트.

## 문제 (실험으로 확인됨)
- 조각 gate의 길이 하한(`_MIN_DURATION_RATIO` × 5.7자/초)이 빠르게 말한 **정상** 조각을 잘림으로 오판 → 재시도·분할 폭증(첫 시도 합격 28%).
- `tts_continuation` 시도는 prefill이 나쁘면 전혀 다른 말을 만들고, 길이·에너지 gate는 이를 못 거른다.
- 시드가 고정이라 `--slides` 재생성이 바이트 단위로 같은 결과를 낸다(04-1 슬라이드 5·6 실측).

## 작업 항목
### S9-a 조각 합격 판정
`_synthesize_segment_with_gate`(및 필요한 호출 경로)에서 각 시도마다:
1. 기존 싼 검사 먼저: 과길이(`> expected × _MAX_DURATION_RATIO`), 목소리 비율(`_MIN_VOICED_RATIO`), 내부 무음(`_MAX_INTERNAL_SILENCE_S`). 하나라도 실패하면 STT 없이 불합격.
2. 통과하면 STT(`evaluate_transcription`, 조각 wav를 임시 파일로 써서) → **합격 = status "pass" 그리고 CER ≤ `_MAX_SEGMENT_CER = 0.25`**.
3. 길이 하한(`min_seconds`)은 합격 판정에서 **제외**(값은 trace·기록용으로만 유지 가능).
4. STT를 쓸 수 없을 때(파이프라인에 `stt` 없음 / `verify_stt=False` / status "unavailable"): 기존 판정(길이 하한 포함)으로 폴백 — 기존 동작 보존.
5. 불합격 시 차선책 선택 기준: STT 있으면 CER 낮은 순(동률이면 무음 짧은 순), 없으면 기존 점수.
6. `_trace` 기록에 `cer`, `stt_status`, 불합격 이유(`reason`: long/voiced/silence/stt/cer/short)를 추가.
- `verify_stt`를 조각 단위까지 전달: 배치 기본 켬, `--no-stt`면 조각 STT도 끔.

### S9-b 이어붙이기 중단
- `plan_attempts`는 continuation 여부와 무관하게 plain tts 시드 4개만 반환. slide 합성 경로에서 `tts_continuation`을 호출하지 않는다.
- `SegmentQC.call`/`continuation_from`/`boundary_review`는 스키마 유지(값은 "tts"/None/[]가 됨). 스키마 필드 삭제 금지.

### S9-c 말하기 속도 상수
- `raon_tts._CHARS_PER_SECOND`와 `script_gen.SPEECH_CHARS_PER_SECOND`를 **7.0**으로(서로 동기 유지, 주석에 실험 근거).
- 이 때문에 바뀌는 프롬프트 기대값 픽스처(`tests/fixtures/*baseline*.txt` 등)는 **의도된 변경**으로 갱신하고 보고에 명시.

### S9-d 재생성 시 다른 시드
- 강제 재생성(`--slides`로 지정된 슬라이드 = 후보 생성 경로)에서는 다른 시드 집합 `TTS_RESEED_SEEDS = (97, 113, 131, 151)`을 쓴다. 일반 합성은 기존 `TTS_SEEDS` 앞 4개.
- 전달 방식은 최소로(예: `synthesize_raon_slide(..., seeds=...)`). 캐시 키는 바꾸지 않는다(같은 입력의 다른 유효 결과).

### S9-e 버전
- `TTS_SYNTH_VERSION`을 `"v12-stt-gate-plain"`으로. (기존 음성의 캐시가 무효가 되는 것은 의도됨 — 01·04는 재실행 안 함(D-14), 04-1은 전체 재제작 예정.)

## 필수 테스트 (mock만, 실제 GPU/STT 금지)
1. 길이가 하한보다 짧지만 STT pass·CER 0.05인 시도 → 첫 시도 합격(재시도 없음)
2. 길이·무음 정상이지만 CER 0.6 → 불합격, 다음 시드 시도
3. 무음 초과 시도 → STT 호출 없이 불합격(STT mock 호출 횟수로 확인)
4. STT 없음/`verify_stt=False` → 기존 판정(길이 하한 포함)과 동일 동작
5. 전부 불합격 → CER 가장 낮은 시도가 차선책으로 반환
6. `plan_attempts(True)`도 plain만, slide 합성에서 `tts_continuation` 미호출
7. `--slides` 강제 재생성 → `TTS_RESEED_SEEDS` 사용, 일반 합성 → `TTS_SEEDS`
8. 두 속도 상수 7.0 동기(assert)
9. 기존 테스트 전부 통과(바뀐 기대값은 이유와 함께 보고)

## 금지
- 실제 GPU/LLM/STT 실행, `data/`·`output/` 쓰기, `data/audio_ref/**`.
- 슬라이드 단위 판정(`_slide_gate_failures`)·세그먼트 분할 규칙·split/redraw 구조 변경(속도 상수 변경으로 인한 값 변화는 허용).
- AGENTS.md·docs/ 수정, 새 의존성.
