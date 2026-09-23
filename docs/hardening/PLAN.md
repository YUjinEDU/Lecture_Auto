# 제작 파이프라인 안정화 계획 (웹 인터페이스 이전 단계)

작성: 2026-09-23 · 기준 HEAD `ad05c65` · 근거: `.claude/LECTURE_TTS_RESEARCH_HANDOFF.md`, `docs/260923_review.md`

## 최종 목표와 이번 범위

최종 목표는 **웹 인터페이스에서 교수님이 대본 검수 → 음성 청취·승인 → 부분 재생성 → 최종 영상까지 진행**하는 것.
이번 범위는 **그 직전까지**: 웹 UI가 그대로 올라탈 수 있는 파일 계약(JSON)과 CLI 동작을 배치 경로
(`scripts/batch_generate_lectures.py`)에서 먼저 확정한다. UI·API 엔드포인트·포털 코드는 만들지 않는다.

설계 원칙: 웹에서 쓸 상태는 **Pydantic 스키마(`lecture_auto/schemas/`) + atomic JSON 파일**로 둔다.
나중에 FastAPI가 같은 파일을 읽고 쓰면 되게 한다. 새 DB·프레임워크·레지스트리 금지.

## 공통 규칙 (모든 단계)

- 작업 전 `CLAUDE.md`, 루트 `AGENTS.md`, 수정 디렉터리의 `AGENTS.md`를 읽는다.
- 함수 수정 전 모든 호출자를 `grep`으로 찾는다. 공유 함수는 한 곳에서 고친다.
- 테스트는 mock·임시 파일만 사용(GPU/네트워크/Redis 금지). 합성은 `synthesize_raon_slide`를 mock.
- 기준선: `.venv/bin/python -m pytest -q --ignore=tests/test_parser.py` → **262 passed, 8 failed**
  (health 버전, llm env 2건, approve broker, test_video 4건). 단계 후 새 실패 0건이어야 한다.
  `test_video` 4건처럼 기존 실패를 해당 단계가 건드리면 고쳐도 된다(가짜 WAV가 원인).
- `data/`, `output/`의 실데이터는 읽기만. `api.txt`는 열지 않는다. `data/audio_ref/**` 덮어쓰기 금지.
- 기존 동작을 바꾸는 부분은 커밋 메시지와 보고서에 명시.
- 보고 형식: 변경 파일 / 해결한 항목 ID / 추가 테스트 / pytest 결과(숫자) / 남은 문제.

## 단계

### S1. 출력 정합성 — 영상에 들어가는 파일이 정확해야 한다
| ID | 내용 | 완료 조건(테스트) |
|---|---|---|
| S1-a (F5) | `merge_audio`가 WAV **목록**을 받게 하고 `assemble_video`는 `slide_pairs`의 WAV만 병합. 디렉터리 호출자(`tasks/tts_tasks.py`, `demo/*`)는 기존 동작 유지(목록을 만들어 넘기거나 dir도 허용) | 폴더에 무관한 WAV가 있어도 병합 결과에 포함되지 않음 |
| S1-b (F5) | `assemble_video`에 누락 WAV 시 예외를 내는 엄격 모드. 배치 경로는 엄격 모드 사용 | 필수 WAV 누락 → 예외, MP4 미생성 |
| S1-c (F2, D-05) | 기존 WAV가 **있으면** 합성은 `slide_NNN.cand.wav`에만 쓰고 기존 WAV·hash는 절대 건드리지 않음(성공·실패 무관, 교체는 S2의 `--promote`). 기존 WAV가 **없으면** 지금처럼 `out_wav`에 쓰고 통과 시에만 hash 기록(실패 시 hash 없이 남겨 DRAFT 조립 가능) | 기존 WAV가 재생성(성공·실패 모두) 후에도 바이트 동일, `.cand.wav` 생성 |
| S1-d | TTS 캐시 키에 `target_seconds`(=`max_seconds`) 포함 | 목표 시간 변경 시 캐시 무효 |
| S1-e (F4) | 조립에 쓰는 WAV 중 하나라도 현재 캐시 키로 `is_cache_valid`가 아니면(실패·미기록·키 불일치) `<stem>_DRAFT.mp4`로 출력, 최종 경로에는 쓰지 않음. S2에서 "또는 승인됨"으로 확장 | 무효 1건 → DRAFT 경로만 생성, 전부 유효 → 최종 경로 |

### S2. 승인 목록 + 타임라인 — 웹 UI의 데이터 계약
- `lecture_auto/schemas/`에 `ApprovalManifest`(슬라이드 번호 → 승인 WAV 파일명, sha256, 승인 시각, 메모)
  와 `Timeline`(슬라이드 번호, 시작초, 길이, wav sha256) 모델 추가. 파일: `work/<lec>/approved.json`,
  `output/<name>.timeline.json`.
- **승인된 슬라이드는 캐시 키·합성 버전이 바뀌어도 재생성하지 않는다.** 재생성은 `--slides`로 명시
  했을 때만, 그 경우도 S1-c 후보 흐름을 따른다(승인은 자동으로 옮겨가지 않음).
- 승인 WAV의 sha256이 파일과 다르면 조립 중단(오염 감지).
- CLI: `--approve 1-48` / `--approve-passing`(현재 gate 통과본 일괄) / `--promote 12`(후보를 승인본으로).
- 조립 시 `timeline.json` 출력(교수님이 "12번 슬라이드 05:31" 식으로 지적할 수 있게).
- 완료 조건: 합성 버전을 바꾼 상태에서 전체 실행해도 승인 슬라이드는 synth mock이 호출되지 않음.

### S3. 부분 교체·재사용을 설정으로
- 강의별 `slide_overrides`(예: 1번 슬라이드 PNG/WAV 지정)로 `…_인트로교체.mp4` 같은 수작업을 재현 가능하게.
- `clone_from` 사용 시 원본·대상 PDF의 본문 페이지 동일성 검사(렌더 PNG 해시 또는 텍스트 비교), 불일치 페이지 보고.
- 전제: 인트로 교체본 제작 방법을 사용자에게 확인(현재 저장소에 스크립트 없음).

### S4. 음성 검증 의미 보강 (코드 부분은 S1과 병행 가능)
- S4-a (F1): `check_transcription_fidelity` → 결과를 `pass/fail/unavailable`로 구분, 한국어 CER
  (공백 제거·정규화, stdlib `difflib` 또는 편집거리 직접 구현) 기록. STT 예외·빈 전사 = `unavailable`.
  CER 합격선은 정하지 않고 **기록만**; 기존 반복/길이 사유는 유지.
- S4-b: 참조 음성 확정용 A/B 스크립트(동일 대본·seed로 `ref_phone_norm.wav` vs `reference_v1.wav`),
  gate/smoke 스크립트의 참조 경로를 배치와 일치. **GPU 실행과 청취 판정은 사람 단계.**

### S5. 남은 강의 제작
S1–S4 병합 후 실제 제작. 교수님 피드백은 timeline 기준으로 수집 → `--slides` 재생성 → 후보 청취 → `--promote`.

## 진행 방식

Sonnet 작업자가 단계별로 별도 git worktree에서 구현·테스트·커밋. 감독(Opus)이 diff 검토, pytest 재실행,
완료 조건 확인 후 사용자 승인을 받아 병합. 순서: **S1 ∥ S4-a → S2 → S3 → S4-b(GPU) → S5**.

## 사용자 확인 필요

1. `api.txt` 키 폐기·재발급(사용자 작업) 후 git 이력 정리 여부.
2. 남은 제작 대상 목록(01·04 결과물 존재, 02·03·05 작업 폴더 없음).
3. 교수님이 긍정 평가한 음성이 어느 참조 음성으로 만들어졌는지.
4. 인트로 교체본 제작 방법.
