# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-23)

**Core value:** PPT 한 장을 넣으면 교수님 스타일의 강의 스크립트와 음성이 나온다
**Current focus:** Phase 1 — Foundation

## Current Position

Phase: 1 of 4 (Foundation)
Plan: 0 of TBD in current phase
Status: Ready to plan
Last activity: 2026-03-23 — Roadmap created, phases derived from 29 v1 requirements

Progress: [░░░░░░░░░░] 0%

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

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Init]: FastAPI BackgroundTasks 사용 (Celery 불필요, 단일 교수 워크플로우)
- [Init]: GPU 서버 로컬 디스크 저장 (S3 대비 1000x 빠름, 추가 비용 0)
- [Init]: Next.js는 GPU 서버를 직접 노출하지 않음 (server-to-server secret 방식)

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1 blocker]: Next.js 포털 Supabase Auth 현황 확인 필요 (기존 auth.users와 스키마 맞춤)
- [Pre-Phase 2]: GPU 서버 2번째 GPU 유무 확인 필요 (VLM+TTS 동시 구동 가능 여부)
- [Pre-Phase 3]: `claude -p` subprocess stdout 스트리밍 동작 검증 필요 (문서화된 API 아님)
- [Pre-Phase 3]: Max Plan 월별 토큰 한도 확인 필요 (토큰 예산 설계 기준)

## Session Continuity

Last session: 2026-03-23
Stopped at: Roadmap created, REQUIREMENTS.md traceability updated
Resume file: None
