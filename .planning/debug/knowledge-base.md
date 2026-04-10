# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## pipeline-functional-verification — stop flag 잔류 및 stage 오기록 버그 3건
- **Date:** 2026-04-10
- **Error patterns:** stop flag, StopIteration, _clear_stop_flag, mark_stopped, stage, pipeline, rerun, early return
- **Root cause:** (1) rerun_scripts_and_media early return 경로에서 _clear_stop_flag 미호출로 stop flag 영구 잔류; (2) update_script_and_rebuild가 _render_media_stage 진입 전 _clear_stop_flag 미호출로 이전 중지 플래그에 의해 즉시 StopIteration 발생 후 미처리; (3) rerun_scripts_and_media except StopIteration에서 항상 "script" stage 사용으로 TTS/video 단계 중지 시 잘못된 stage 기록
- **Fix:** (1) early return 직전 _clear_stop_flag(job_id) 추가; (2) _render_media_stage 호출 전 _clear_stop_flag(job_id) 추가; (3) try 블록에 current_stage 변수 도입하여 단계별 올바른 stage 기록
- **Files changed:** lecture_auto/demo/pipeline.py
---

