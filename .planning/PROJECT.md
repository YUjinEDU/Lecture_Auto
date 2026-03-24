# Lecture Auto — 강의 자동화 파이프라인

## What This Is

교수님의 PPT 강의자료를 입력하면, 슬라이드별 강의 스크립트와 음성을 자동 생성하는 내부용 파이프라인 시스템. 연구실 내부 포털에 통합되어 교수님이 직접 사용하며, 생성된 스크립트를 검수/편집한 뒤 TTS 음성까지 한 번에 받을 수 있다.

## Core Value

PPT 한 장을 넣으면 교수님 스타일의 강의 스크립트와 음성이 나온다 — 이 흐름이 끊기지 않아야 한다.

## Requirements

### Validated

- [x] PPTX 파일 업로드 및 구조 파싱 (텍스트, shape, notes 추출) — Validated in Phase 01.1: mvp-demo
- [x] 슬라이드별 PNG 이미지 렌더링 — Validated in Phase 01.1: mvp-demo
- [x] VLM 기반 시각 해설 노트 생성 (전 슬라이드) — Validated in Phase 01.1: mvp-demo (VLM-01/02/03)
- [x] Claude Code 기반 강의 스크립트 자동 생성 — Validated in Phase 01.1: mvp-demo (SCRIPT-01/02/03/04)
- [x] Qwen3-TTS 음성 합성 (교수님 Voice Clone 포함) — Validated in Phase 01.1: mvp-demo (TTS-01/02/04)
- [x] 중간 산출물 JSON 저장 및 검증 — Validated in Phase 01.1: mvp-demo

### Active

- [ ] 강의 메타데이터 입력 (강의명, 대상, 시간, 스타일)
- [ ] 슬라이드별 스크립트 검수/편집 UI
- [x] 비동기 작업 관리 (제출 → 상태 폴링 → 결과 반환) — Validated in Phase 2: vlm-pipeline (INFRA-02)
- [ ] 연구실 포털 통합 (교수님 내부 포털 페이지)
- [ ] 슬라이드 단위 부분 재생성
- [ ] 최종 패키지 다운로드 (스크립트 + 음성)

### Out of Scope

- TTS 음성 합성 외의 영상 렌더링 (Remotion 등) — 후속 프로젝트로 분리
- LMS 업로드 자동화 — 현재 수동 업로드로 충분
- 실시간 웹 편집기 — 슬라이드별 텍스트 편집이면 충분
- 기존 강의 영상 STT — 별도 프로세스로 진행
- OAuth/외부 인증 — Supabase Auth로 충분
- 모바일 앱 — 웹 포털로 충분

## Context

### 배경

교수님이 보유한 대량의 PPT 강의자료를 기반으로, 강의 설명 스크립트를 자동 생성하고 이후 TTS 및 영상화 단계로 연결할 수 있는 내부용 자동화 시스템이 필요하다.

### 기술 환경

**파이프라인 (GPU 서버)**
- Python 3.11+, FastAPI
- python-pptx (PPT 파싱)
- LibreOffice CLI (PPTX → PDF → PNG 렌더링)
- Qwen3-VL 시리즈 (시각 해설 노트 생성, 로컬)
- Claude Code `claude -p` (강의 스크립트 작성, Max Plan)
- Qwen3-TTS (음성 합성 + Voice Clone, 로컬)
- Pydantic (JSON 스키마 검증)

**프론트엔드 (연구실 포털)**
- Next.js 16 (App Router, Turbopack)
- TypeScript, Tailwind CSS v4
- Supabase (PostgreSQL + Auth + Storage)
- Vercel 배포
- pnpm

### 기존 패턴

연구실 포털에 이미 검증된 패턴이 있음:
- 서버 모니터링: Python 에이전트 → Supabase REST API → Next.js 프론트엔드
- 데이터 파이프라인: 외부 스크립트 → Supabase → 프론트엔드 조회
- 강의 자동화도 동일한 비동기 작업 패턴으로 연동

### 파이프라인 흐름

```
[PPTX 업로드]
  → [PPT Parser] → Slide Manifest JSON
  → [LibreOffice Renderer] → Slide PNGs
  → [Qwen3-VL] → Visual Notes JSON (전 슬라이드)
  → [Claude Code] → Lecture Scripts JSON
  → [교수님 검수/편집]
  → [Qwen3-TTS] → Audio Files (Voice Clone)
  → [최종 패키지 다운로드]
```

### 아키텍처

```
┌─ Vercel ─────────────────────────┐
│  Next.js 16 포털 (App Router)     │
│  Supabase Auth (professor role)   │
│  강의 자동화 UI 페이지             │
│    └→ API Route → FastAPI 호출    │
└──────────┬───────────────────────┘
           │ REST API (async)
┌──────────┴───────────────────────┐
│  GPU 서버 (FastAPI)               │
│  작업 제출 → 상태 폴링 → 결과 반환  │
│                                   │
│  ├─ python-pptx (파싱)            │
│  ├─ LibreOffice (렌더링)          │
│  ├─ Qwen3-VL (시각 해설 노트)     │
│  ├─ Claude Code (스크립트 작성)    │
│  └─ Qwen3-TTS (음성 합성)        │
│                                   │
│  파일 저장: /data/work/{job_id}/   │
│  상태 저장: Supabase              │
└───────────────────────────────────┘
```

### 파일 저장 구조

```
/data/work/{job_id}/
  input/        # 원본 PPTX
  parsed/       # Slide Manifest JSON
  rendered/     # 슬라이드 PNG
  vlm/          # Visual Notes JSON
  scripts/      # 강의 스크립트 JSON
  audio/        # TTS 음성 파일
  logs/         # 실행 로그
  artifacts/    # 최종 패키지
```

### 사용자

- 컴공 교수님 (직접 사용, 기술적 역량 있음)
- 연구실 내부 포털의 교수님 권한으로 접근

### 교수님 스타일 반영

- 프롬프트 엔지니어링으로 설명 스타일 제어 (NotebookLM 방식)
- Few-shot 예시 또는 기존 강의 트랜스크립트 참조 가능
- Qwen3-TTS Voice Clone으로 교수님 목소리 재현 (3초 오디오)

### 운영 비용

| 구성요소 | 비용 |
|----------|------|
| python-pptx, LibreOffice | 0 (오픈소스) |
| Qwen3-VL | 0 (로컬 GPU) |
| Claude Code | 0 (Max Plan 구독) |
| Qwen3-TTS | 0 (로컬 GPU) |
| 파일 저장 | 0 (GPU 서버 디스크) |
| **총 운영 비용** | **0원** |

## Constraints

- **GPU 서버**: Qwen3-VL + Qwen3-TTS 동시 구동 가능한 VRAM 필요
- **Vercel 타임아웃**: Next.js API Route는 10-60초 제한 → 비동기 패턴 필수
- **Claude Code**: `claude -p` 파이프 모드로 호출, Max Plan 범위 내 사용
- **인증**: Supabase Auth professor role만 접근 가능
- **재현성**: 같은 입력 + 같은 설정이면 동일 파이프라인 재실행 가능해야 함
- **검수성**: 교수님이 텍스트만 보고 수정 가능한 산출물 형식

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| VLM으로 Qwen3-VL 시리즈 채택 | 로컬 실행 가능, 비용 0, 한국어 지원 | ✓ Validated (Phase 01.1) |
| 슬라이드 분류 불필요 | VLM이 로컬이므로 전 슬라이드 처리해도 비용 0 | ✓ Validated (Phase 01.1) |
| Claude Code로 스크립트 작성 | Max Plan 활용 비용 0, 높은 작문 품질 | ✓ Validated (Phase 01.1) |
| Qwen3-TTS + Voice Clone | 로컬 실행, 한국어 지원, 교수님 목소리 재현 | ✓ Validated (Phase 01.1) |
| FastAPI + REST API 연동 | 기존 포털 패턴과 동일, 비동기 작업 지원 | ✓ Validated (Phase 2) |
| GPU 서버 로컬 파일 저장 | 용량 무제한, 추가 비용 0, ML 파이프라인과 근접 | ✓ Validated (Phase 01.1) |
| Gradio 제외, 포털 직접 통합 | 인증 연동, 일관된 UX, 기존 인프라 활용 | — Pending (Phase 2+) |
| 교수님 스타일은 프롬프트 기반 | STT 별도 진행, 프롬프트/few-shot으로 충분 | ✓ Validated (Phase 01.1) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-24 after Phase 2 (vlm-pipeline) complete — 비동기 Celery+Redis VLM 파이프라인, FastAPI 작업 라우트, SSE 진행률 스트리밍 구축*
