# S0 SPEC — 기존 테스트 오류 정리 + 참조 음성 통일

참조: `../../README.md`(상태판), `../../decisions/DECISIONS.md` (D-12). 기준: master `fa3bca9` 이후 HEAD.

## 목표
전체 `pytest`가 **옵션 없이** 통과하는 상태(현재: `--ignore=tests/test_parser.py`를 붙여도 319 passed / 4 failed).

## 항목
| ID | 현재 증상 | 해야 할 일 |
|---|---|---|
| S0-a | `tests/test_parser.py`가 존재하지 않는 `lecture_auto.pipeline.parser`를 import → 수집 오류 | 이 테스트가 원래 검증하던 대상(현재 `parser_pptx.py`/`parser_pdf.py` 중 무엇인지)을 git log로 확인. 대상이 있으면 import를 고치고, 이미 다른 테스트가 같은 내용을 덮고 있으면 중복임을 보고서에 근거와 함께 쓰고 삭제 |
| S0-b | `test_jobs_api::test_health_endpoint` 실패 | 원인(버전 문자열 기대값 등) 확인 후 **실제 코드가 맞는지 테스트가 맞는지** 판단해 한쪽을 고친다 |
| S0-c | `test_llm::test_env_overrides_models`, `test_missing_api_key_raises` 실패 | 저장소 루트 `.env`가 `load_dotenv()`로 읽혀 테스트 환경이 오염되는 것으로 추정(작업자 보고). 테스트가 실제 `.env`에 영향받지 않게 격리(monkeypatch/fixture). 앱 코드의 dotenv 동작은 바꾸지 말 것 — 바꿔야 한다면 이유를 보고 |
| S0-d | `test_scripts_api::TestApproveScripts::test_approve_succeeds_with_all_scripts` 실패 | 이전 기록상 approval broker(Celery/Redis) 연결 문제. 테스트가 Redis 없이 돌도록 mock. 실제 Redis 접속 시도 금지 |
| S0-e | `scripts/recalibrate_gate.py`, `scripts/smoke_tts_gate.py`의 `REF_VOICE`가 `test_variants/ref_phone_norm.wav` | 배치와 같은 `data/audio_ref/reference_v1.wav`로. 가능하면 `batch_generate_lectures.REF_VOICE`를 import해 한 곳에서 관리(순환 import·무거운 import 발생 시 상수 복제 + 주석) |

## 원칙
- 테스트를 skip/xfail로 숨기거나 assert를 느슨하게 만들어 통과시키지 않는다. 불가피하면 이유를 보고서에 명시하고 감독 판단을 받는다.
- 앱 동작 변경은 최소화하고, 바꾼 것은 커밋 메시지·보고서에 명시.
- 원인 판단 근거(에러 메시지, 관련 커밋)를 보고서에 남긴다.

## 완료 조건
- `/home/dbsdosdb/workspace/Lecture_Auto/.venv/bin/python -m pytest -q -p no:cacheprovider` (ignore 없이) → 실패 0, 수집 오류 0
- 보고: 항목별 원인 / 수정 / 근거

## 금지
- `scripts/batch_generate_lectures.py`, `lecture_auto/pipeline/lecture_plan.py` 수정(S3 작업자가 병행 수정 중) — S0-e에서 batch를 **import만** 하는 것은 허용
- `data/`, `output/` 쓰기, `data/audio_ref/**` 수정, AGENTS.md·docs/ 수정, 새 의존성
