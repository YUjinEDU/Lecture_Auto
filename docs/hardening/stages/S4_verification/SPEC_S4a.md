# S4-a SPEC — STT 검증 상태 구분 + CER 기록 (F1)

참조: `../../PLAN.md` S4, `../../00_context/VERIFIED_FACTS.md`, `../../decisions/DECISIONS.md` (D-08)

## 현재 (lecture_auto/pipeline/raon_tts.py:101)
`check_transcription_fidelity(pipe, audio_path, expected_text) -> list[str]`
- STT 예외 → `[]`, 빈 전사/빈 기대문 → `[]` : 검사 불능이 통과처럼 보임.
- 반복(3연속 단어, 2단어 구 반복)과 길이 비율(<0.55, >1.60)만 검사. 내용 비교 없음.

## 목표
- **기존 gate 의미를 바꾸지 않는다**: 기존 호출자가 쓰는 `reasons: list[str]` 반환·판정은 그대로.
- 옆에 상태 정보를 추가: 새 함수 `evaluate_transcription(pipe, audio_path, expected_text) -> TranscriptionCheck`
  - `status`: `"pass" | "fail" | "unavailable"` (예외·빈 전사·빈 기대문 = `unavailable`, reasons 있으면 `fail`, 그 외 `pass`)
  - `reasons: list[str]` (기존과 동일 규칙)
  - `transcript: str | None`, `cer: float | None`
- `check_transcription_fidelity`는 `evaluate_transcription(...).reasons`를 반환하는 얇은 래퍼로 유지(기존 반환값 동일).
- 모델 위치: 작은 dataclass 또는 Pydantic 모델. 웹에서 쓸 예정이므로 Pydantic 권장, 위치는 `raon_tts.py` 안이나 `lecture_auto/schemas/`에 둔다(기존 스키마 관례 확인 후 결정, 보고서에 이유).

## CER
- `CER = (S + D + I) / len(reference)` — 문자 단위 **Levenshtein 편집거리 DP**로 직접 구현(difflib 금지: 최소 편집 수가 아님).
- 정규화: 공백 전부 제거, 문장부호(`.,!?·…"'()[]` 등) 제거, 영문 소문자화. 원문 정규화 규칙을 함수 docstring에 명시.
- 기준 문자열이 비면 `cer=None`.
- **합격선 없음(D-08)**: CER은 기록만, status 판정에 쓰지 않는다.

## 호출자
`grep -rn "check_transcription_fidelity\|transcribe_audio" lecture_auto scripts tests`로 모든 호출자 확인.
`synthesize_raon_slide`에서 `verify_stt=True`일 때 결과를 기존 trace/log에 status·cer도 남기도록 추가(동작은 불변).

## 필수 테스트 (pipe는 mock, `pipe.stt`만 가짜)
1. `pipe.stt`가 예외 → `status="unavailable"`, `check_transcription_fidelity`는 기존처럼 `[]`.
2. 빈 전사 → `unavailable`.
3. 길이 비슷하지만 내용이 다른 전사("…문제를 이해하는…" vs "…아이디어를 검증하는…") → `status="pass"`지만 `cer`가 0.2 이상으로 기록됨(내용 차이를 수치로 잡는지 확인).
4. 동일 문장(공백·문장부호만 다름) → `cer == 0.0`.
5. 반복 전사 → `fail`, reasons에 기존 문자열 형식 유지.
6. CER 단위 테스트: `"abc"` vs `"abd"` = 1/3, `"abc"` vs `"ab"` = 1/3, `"abc"` vs `"abcd"` = 1/3.

## 금지
- `scripts/batch_generate_lectures.py`, `lecture_auto/pipeline/video.py`, `lecture_auto/pipeline/tts.py` 수정(S1 작업자가 병행 수정 중).
- 새 의존성(jiwer 등) 추가. AGENTS.md 수정. `data/`, `output/`, `api.txt` 접근.
