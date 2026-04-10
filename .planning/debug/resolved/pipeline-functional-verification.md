---
status: resolved
trigger: "파이프라인에 6가지 수정이 적용됐는데 기능적으로 올바르게 동작하는지 검증한다."
created: 2026-04-10T00:00:00Z
updated: 2026-04-10T00:05:00Z
---

## Current Focus

hypothesis: 3개의 버그가 발견되어 수정 완료
test: 정적 분석으로 모든 5개 검증 항목 확인
expecting: 수정 후 코드가 논리적으로 올바름
next_action: 사용자 확인

## Symptoms

expected: 수정된 pipeline.py가 이전과 동일하게 동작하면서 새로운 기능(status=running, 중지 체크, 에러 처리)이 올바르게 작동
actual: 알 수 없음 — 아직 실행 전
errors: 없음
reproduction: 코드 정적 분석 + 로직 검증
started: 방금 수정 완료

## Eliminated

- hypothesis: mark_stopped/mark_failed 시그니처 불일치
  evidence: state.py 249행: mark_stopped(job_id, stage_key, message) — 모든 호출이 올바른 형태
  timestamp: 2026-04-10T00:03:00Z

- hypothesis: rerun_* 함수의 StopIteration catch 누락
  evidence: rerun_tts_only(line 1359), rerun_video_only(line 1390) 모두 StopIteration 명시적 캐치
  timestamp: 2026-04-10T00:03:00Z

- hypothesis: _render_media_stage 내부 StopIteration 전파 불가
  evidence: _render_media_stage에 try-except 없음 → 호출자로 정상 전파됨
  timestamp: 2026-04-10T00:03:00Z

## Evidence

- timestamp: 2026-04-10T00:02:00Z
  checked: state.py mark_stopped, mark_failed 시그니처
  found: mark_stopped(job_id, stage_key, message), mark_failed(job_id, stage_key, error) — 3개 인자
  implication: 검증 항목 C 통과

- timestamp: 2026-04-10T00:02:00Z
  checked: rerun_tts_only try-except (line 1327-1364)
  found: StopIteration → mark_stopped(job_id, "tts", str(exc)); Exception → mark_failed(job_id, "tts", str(exc))
  implication: 검증 항목 A 통과

- timestamp: 2026-04-10T00:02:00Z
  checked: rerun_video_only try-except (line 1367-1395)
  found: StopIteration → mark_stopped(job_id, "video", str(exc)); Exception → mark_failed(job_id, "video", str(exc))
  implication: 검증 항목 A 통과

- timestamp: 2026-04-10T00:03:00Z
  checked: rerun_scripts_and_media early return (line 1404-1408)
  found: manifest 없을 때 _clear_stop_flag 호출 없이 return → stop flag 영구 잔류 가능
  implication: BUG B — 수정 필요

- timestamp: 2026-04-10T00:03:00Z
  checked: rerun_scripts_and_media except StopIteration (line 1432)
  found: mark_stopped(job_id, "script", ...) — TTS/video 단계 중지 시에도 "script" stage로 기록
  implication: BUG E — current_stage 추적 변수 필요

- timestamp: 2026-04-10T00:03:00Z
  checked: update_script_and_rebuild _render_media_stage 호출 (line 1300)
  found: _clear_stop_flag 호출 없이 _render_media_stage 진입 → 이전 중지 플래그 잔류 시 즉시 StopIteration 발생, try-except 없어서 API로 전파
  implication: BUG D — _clear_stop_flag 추가 필요

## Resolution

root_cause: 3개의 버그:
  1. (Bug B) rerun_scripts_and_media의 manifest 없음 early return 경로에서 _clear_stop_flag 미호출 → stop flag 영구 잔류
  2. (Bug D) update_script_and_rebuild가 _render_media_stage 진입 전 _clear_stop_flag 미호출 → 이전 중지 플래그로 StopIteration 발생, 미처리
  3. (Bug E) rerun_scripts_and_media의 except StopIteration에서 항상 "script" stage 사용 → TTS/video 단계 중지 시 잘못된 stage 기록

fix: |
  1. rerun_scripts_and_media early return 직전에 _clear_stop_flag(job_id) 추가
  2. rerun_scripts_and_media try 블록에 current_stage 변수 도입, _render_media_stage 전에 "tts"로 업데이트
  3. update_script_and_rebuild의 _render_media_stage 호출 전에 _clear_stop_flag(job_id) 추가

verification: 정적 분석으로 수정 확인 완료. 실제 GPU 실행 테스트는 불가.
files_changed:
  - lecture_auto/demo/pipeline.py
