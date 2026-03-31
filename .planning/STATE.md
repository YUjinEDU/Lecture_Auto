---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
stopped_at: Completed 04-02-PLAN.md
last_updated: "2026-03-31T11:14:34.464Z"
progress:
  total_phases: 5
  completed_phases: 3
  total_plans: 15
  completed_plans: 13
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-23)

**Core value:** PPT 한 장을 넣으면 교수님 스타일의 강의 스크립트와 음성이 나온다
**Current focus:** Phase 04 — tts-delivery

## Current Position

Phase: 04 (tts-delivery) — EXECUTING
Plan: 3 of 3

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**

- Last 5 plans: none yet
- Trend: -

*Updated after each plan completion*
| Phase 01-foundation P01 | 12 | 2 tasks | 9 files |
| Phase 01-foundation P02 | 3 | 1 tasks | 4 files |
| Phase 01-foundation P03 | 20 | 2 tasks | 5 files |
| Phase 01.1 P01.1-01 | 20 | 2 tasks | 4 files |
| Phase 01.1-mvp-demo P02 | 15 | 2 tasks | 4 files |
| Phase 02-vlm-pipeline P01 | 15 | 2 tasks | 15 files |
| Phase 02-vlm-pipeline P02 | 340 | 2 tasks | 6 files |
| Phase 03 P02 | 12 | 2 tasks | 8 files |
| Phase 03 P03 | 25 | 3 tasks | 12 files |
| Phase 04-tts-delivery P01 | 3 | 2 tasks | 5 files |
| Phase 04-tts-delivery P02 | 3 | 2 tasks | 6 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Init]: FastAPI BackgroundTasks 사용 (Celery 불필요, 단일 교수 워크플로우)
- [Init]: GPU 서버 로컬 디스크 저장 (S3 대비 1000x 빠름, 추가 비용 0)
- [Init]: Next.js는 GPU 서버를 직접 노출하지 않음 (server-to-server secret 방식)
- [Phase 01-foundation]: ShapeRecord bounding box in EMU, no speaker_notes field, LectureStyle with 3 Literal axes (density/tone/approach), JobPaths with 8 subdirs
- [Phase 01-foundation]: PP_PLACEHOLDER.SUBTITLE maps to text_role=title (same as TITLE/CENTER_TITLE)
- [Phase 01-foundation]: EMU font size conversion: font.size / 12700 (not Pt() constructor)
- [Phase 01-foundation]: Font issues are warnings only (D-13): pipeline never stops for tofu detection
- [Phase 01-foundation]: Per-job LibreOffice UserInstallation dir prevents lock-file races
- [Phase 01.1]: VLM prompt includes parsed slide text alongside image (text-grounded prompting) to prevent hallucination
- [Phase 01.1-mvp-demo]: transformers lazy-import pattern keeps tts.py importable without GPU stack
- [Phase 01.1-mvp-demo]: assemble_video matches PNG/WAV by parsing slide number from filename suffix
- [Phase 02-vlm-pipeline]: Status derived from last_progress (not Celery AsyncResult) for simplicity
- [Phase 02-vlm-pipeline]: SSE ping=15s keep-alive to prevent proxy timeouts; auth middleware deferred to INFRA-03
- [Phase 03]: cpu_queue for script tasks separates Claude subprocess from GPU workload
- [Phase 03]: Per-slide checkpointing in task (not wrapping generate_scripts()) for resumability
- [Phase 03]: Direct GPU API calls from Next.js client (NEXT_PUBLIC_GPU_API_URL) for SSE and lower latency
- [Phase 04-tts-delivery]: qwen-tts package (Qwen3TTSModel) replaces raw transformers for cleaner voice-clone API
- [Phase 04-tts-delivery]: Base model (not CustomVoice) used for voice cloning via generate_voice_clone()
- [Phase 04-tts-delivery]: Per-professor voice storage under VOICE_REF_ROOT env var, default professor_id for MVP
- [Phase 04-tts-delivery]: ZIP_STORED compression for WAV/MP4 (already compressed, no CPU overhead)
- [Phase 04-tts-delivery]: Combined scripts.json array in ZIP instead of per-slide JSON files

### Roadmap Evolution

- Phase 01.1 inserted after Phase 1: MVP Demo — python run.py E2E demo pipeline on localhost (INSERTED)

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1 blocker]: Next.js 포털 Supabase Auth 현황 확인 필요 (기존 auth.users와 스키마 맞춤)
- [Pre-Phase 2]: GPU 서버 2번째 GPU 유무 확인 필요 (VLM+TTS 동시 구동 가능 여부)
- [Pre-Phase 3]: `claude -p` subprocess stdout 스트리밍 동작 검증 필요 (문서화된 API 아님)
- [Pre-Phase 3]: Max Plan 월별 토큰 한도 확인 필요 (토큰 예산 설계 기준)

## Session Continuity

Last session: 2026-03-31T11:14:34.461Z
Stopped at: Completed 04-02-PLAN.md
Resume file: None
