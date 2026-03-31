---
phase: 04-tts-delivery
plan: 01
subsystem: tts
tags: [qwen-tts, voice-clone, celery, gpu-queue, pydantic, ffmpeg]

# Dependency graph
requires:
  - phase: 01.1-mvp-demo
    provides: "Original tts.py with transformers-based TTS, video.py assemble_video"
  - phase: 02-vlm-pipeline
    provides: "Celery task pattern (vlm_tasks.py), progress publisher, celery_app routing"
  - phase: 03-script-ui
    provides: "Script JSON files (script_{NNN}.json) and script approval flow"
provides:
  - "Refactored TTS pipeline using qwen-tts Base model with voice clone support"
  - "Resumable Celery TTS task (synthesize_job_task) on gpu_queue"
  - "Single-slide re-TTS task (regenerate_slide_tts_task) for D-05 workflow"
  - "Per-professor voice reference storage (voice_store.py)"
  - "TTS Pydantic response schemas (VoiceRegisterResponse, TTSStatusResponse, TTSRegenerateResponse, PackageResponse)"
  - "Audio merge utility (merge_audio) for concatenating per-slide WAVs"
affects: [04-02, 04-03, 05-frontend-tts]

# Tech tracking
tech-stack:
  added: [qwen-tts, Qwen3TTSModel]
  patterns: [lazy-load singleton per worker, file-based checkpointing, voice-clone with fallback]

key-files:
  created:
    - lecture_auto/tasks/tts_tasks.py
    - lecture_auto/storage/voice_store.py
    - lecture_auto/schemas/tts.py
  modified:
    - lecture_auto/pipeline/tts.py
    - lecture_auto/tasks/celery_app.py

key-decisions:
  - "qwen-tts package (Qwen3TTSModel) replaces raw transformers for cleaner voice-clone API"
  - "Base model (not CustomVoice) used for voice cloning support via generate_voice_clone()"
  - "Per-professor voice storage under VOICE_REF_ROOT env var, default professor_id for MVP"

patterns-established:
  - "TTS lazy-load singleton: _tts_model global + _get_tts() mirrors VLM pattern exactly"
  - "Voice clone fallback: generate_voice_clone() when ref exists, generate_custom_voice() otherwise"
  - "merge_audio() excludes its own output file from concatenation to prevent recursion"

requirements-completed: [TTS-01, TTS-02, TTS-04]

# Metrics
duration: 3min
completed: 2026-03-31
---

# Phase 04 Plan 01: TTS Pipeline + Celery Tasks Summary

**qwen-tts Base model with voice clone/fallback, resumable Celery TTS task on gpu_queue, per-professor voice storage**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-31T11:06:23Z
- **Completed:** 2026-03-31T11:09:03Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Refactored TTS from transformers/CustomVoice to qwen-tts/Base model with voice_clone + custom_voice fallback
- Created resumable Celery tasks (synthesize_job_task, regenerate_slide_tts_task) with per-slide file-based checkpointing
- Built per-professor voice reference storage with WebM-to-WAV conversion via ffmpeg
- Added merge_audio() for concatenating per-slide WAVs and video assembly post-TTS

## Task Commits

Each task was committed atomically:

1. **Task 1: Refactor tts.py + voice_store.py + TTS schemas** - `843b349` (feat)
2. **Task 2: Create tts_tasks.py + update celery_app.py routing** - `fffbea2` (feat)

## Files Created/Modified
- `lecture_auto/pipeline/tts.py` - Refactored: qwen-tts Qwen3TTSModel, voice clone + fallback, merge_audio()
- `lecture_auto/tasks/tts_tasks.py` - New: synthesize_job_task + regenerate_slide_tts_task Celery tasks
- `lecture_auto/storage/voice_store.py` - New: save_voice_ref, get_voice_ref, convert_webm_to_wav
- `lecture_auto/schemas/tts.py` - New: VoiceRegisterResponse, TTSStatusResponse, TTSRegenerateResponse, PackageResponse
- `lecture_auto/tasks/celery_app.py` - Updated: added tts.* -> gpu_queue routing

## Decisions Made
- Used qwen-tts package (Qwen3TTSModel.from_pretrained) instead of raw transformers for cleaner voice-clone/custom-voice API
- Selected Base model (not CustomVoice) as it supports both generate_voice_clone() and generate_custom_voice()
- Per-professor voice storage under VOICE_REF_ROOT env var with "default" professor_id for MVP (no auth yet)

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all functions are fully wired to real dependencies.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- TTS pipeline and Celery tasks ready for API route integration (04-02)
- Voice store ready for voice registration endpoint (04-02)
- TTS schemas ready for FastAPI response models (04-02)
- celery_app.py routing complete for tts.* tasks

## Self-Check: PASSED

All 5 files found. Both commit hashes (843b349, fffbea2) verified in git log.

---
*Phase: 04-tts-delivery*
*Completed: 2026-03-31*
