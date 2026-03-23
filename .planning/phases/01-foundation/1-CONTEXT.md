# Phase 1: Foundation - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Phase Boundary

검증된 슬라이드 JSON과 PNG 아티팩트를 생성할 수 있는 인프라가 구동된다.

PPTX 업로드 → Slide Manifest JSON 생성 + 슬라이드 PNG 렌더링 + FastAPI 인증 헬스체크.
VLM 시각 노트, 스크립트 생성, TTS는 이 단계 범위 밖이다.

</domain>

<decisions>
## Implementation Decisions

### 설명 스타일 입력 (INPUT-02)
- **D-01:** 프리셋 선택 + 자유 텍스트 보충 두 가지 모두 지원
- **D-02:** 3개 축으로 구성: 밀도(간결↔상세) / 말투(격식체↔구어체) / 접근방식(설명형↔질문유도형)
- **D-03:** 스타일은 강의 전체 단일 적용 (슬라이드별 상이 없음)

### Slide Manifest JSON 스키마
- **D-04:** shape metadata 최대 수준 포함: shape type + bounding box(위치/크기) + z-order + 폰트 정보
- **D-05:** 발표자 노트(speaker notes) 필드는 스키마에서 제외 (교수님이 사용하지 않음)
- **D-06:** 이미지 shape는 `has_image: true` 플래그만 포함 (이미지 내용은 VLM이 PNG에서 직접 처리)
- **D-07:** 텍스트 박스는 제목/본문/기타로 구분된 구조화된 배열로 분리

### 업로드 API 흐름
- **D-08:** 파일 + 메타데이터(강의명, 과목명, 수강 대상, 목표 시간, 설명 스타일) 단일 요청으로 전송
- **D-09:** 업로드 즉시 동기 파싱 후 Slide Manifest JSON 반환 (Phase 1은 동기; Phase 2에서 비동기 전환)
- **D-10:** 중복 파일 감지 시 경고 후 사용자 선택 ("같은 파일이 있습니다, 새로 만들까요?")
- **D-11:** 결과 확인은 포털 UI 상태 폴링 방식

### 한국어 폰트 검증
- **D-12:** 렌더링된 PNG에서 깨진 문자(□□□) 자동 감지
- **D-13:** 폰트 깨짐 발견 시 경고 로그만 남기고 파이프라인 계속 진행 (멈추지 않음)
- **D-14:** GPU 서버에 주요 한국어 폰트 신규 설치 필요 (나눔고딕, 맑은고딕 등)

### Claude's Discretion
- job_id 형식 (UUID v4)
- Supabase jobs 테이블 컬럼 구조 및 상태값 (pending/processing/done/failed)
- Pydantic 스키마 필드명 및 타입 상세
- LibreOffice → PDF → PNG 변환 DPI 설정
- 깨진 문자 감지 방법 (OCR vs. 텍스트 추출 비교)
- Python 패키지 구조 및 디렉토리 레이아웃

</decisions>

<specifics>
## Specific Ideas

- 동기 파싱은 Phase 1 한정 — Phase 2(VLM)부터 비동기 job 패턴으로 전환 예정
- 중복 파일 감지: 파일명 + 크기 또는 SHA 해시 비교

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Tech Stack & Constraints
- `CLAUDE.md` §Technology Stack — 전체 기술 스택, 라이브러리 버전, 선택 근거
- `CLAUDE.md` §What NOT to Use — 금지된 접근 방식 목록 (FastAPI BackgroundTasks for GPU, WebSocket 등)

### Requirements
- `.planning/REQUIREMENTS.md` §Input & Parsing — INPUT-01, INPUT-02, PARSE-01~03 상세 요구사항
- `.planning/REQUIREMENTS.md` §Rendering — RENDER-01~03 상세 요구사항
- `.planning/REQUIREMENTS.md` §Infrastructure — INFRA-01, INFRA-03~05 상세 요구사항

### Architecture & Decisions
- `.planning/PROJECT.md` §아키텍처 — GPU 서버 / Vercel 구조, server-to-server secret 패턴
- `.planning/PROJECT.md` §파일 저장 구조 — /data/work/{job_id}/ 디렉토리 레이아웃
- `.planning/PROJECT.md` §Key Decisions — FastAPI BackgroundTasks 선택 근거, 로컬 디스크 저장 근거

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- 없음 (신규 프로젝트, 기존 코드베이스 없음)

### Established Patterns
- 연구실 포털의 기존 패턴: Python 에이전트 → Supabase REST API → Next.js 프론트엔드
- 강의 자동화도 동일한 패턴으로 연동

### Integration Points
- Next.js 포털(Vercel) → GPU 서버 FastAPI: server-to-server secret 헤더 방식
- Supabase Auth: professor role JWT 검증
- 결과 저장: /data/work/{job_id}/ 로컬 디스크

</code_context>

<deferred>
## Deferred Ideas

- 파싱/렌더링 완료 시 알림 (이메일/포털 내 알림) — Phase 3 UI에서 검토
- 같은 PPTX 재실행 이력 관리 — 백로그 추가

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-03-23*
