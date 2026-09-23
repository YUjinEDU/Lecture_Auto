# S2 REPORT (작업자: Sonnet, 2026-09-23)

- 브랜치 `worktree-agent-ac514760f8c74f7ae`, 커밋 `f94e3ea` → `5528fbb` → `02ce041` (베이스 `ade18f8`)
- 변경: `schemas/production.py`(신규), `pipeline/approval.py`(신규), `scripts/batch_generate_lectures.py`,
  `tests/test_approval.py`(신규), `tests/test_batch_generate_lectures.py`

## 구현
- 스키마: `ApprovedSlide`, `ApprovalManifest`, `TimelineEntry`, `Timeline` (스펙 그대로, `Field(default_factory=dict)`)
- 함수: `load/save_approvals`, `approve`(model_copy), `verify_approved`, `promote_candidate`(prev 보관, 실패본 승격 시 hash 미기록, stale prev hash 제거), `build_timeline`
- 배치: `_synthesize_all_slides`(승인+`--slides` 밖 → 합성 스킵), `_assemble_with_approvals`(오염 시 중단, DRAFT=무효 AND 미승인, timeline 기록), `assemble_only()`(LLM·TTS·렌더링 없음)
- CLI: `--approve`, `--approve-passing`(기존 승인 덮어쓰지 않음), `--promote`(+`--allow-failed`, `--note`), `--assemble-only` — 상호배타, `--only`가 정확히 1개 강의일 때만

## 기존 동작 변경
- `--only` 범위 밖 인덱스 → 모델 로드 전 `parser.error` (예전엔 `--only 0`이 조용히 5번 강의)
- 정상 실행도 승인 슬라이드 스킵, 조립마다 timeline.json 생성

## 테스트
스펙 10종 + 보강(총 20건). 뮤테이션 확인: #6·#7·#8a·#8b는 해당 가드를 끄면 실패함을 확인(8b는 처음 거짓양성 발견 후 수정)

## pytest
296/4 → **319 passed / 4 failed** (기존 4건)

## 남은 문제(작업자 제기)
- `process_lecture` 배선은 코드 검토로만 확인
- 디스크 JSON에 `target_seconds`가 없으면 승인/assemble-only와 전체 파이프라인의 키가 달라질 수 있음(05번 1번 슬라이드)
- `--allow-failed`/`--note`는 `--promote` 없이 조용히 무시, 승인 모드에서 `--slides`/`--shard` 무시
- `--assemble-only`는 기존 `rendered/` PNG 사용(PDF 변경 후 재렌더 전이면 오래된 이미지)
