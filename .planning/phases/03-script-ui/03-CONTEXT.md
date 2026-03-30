# Phase 3: Script + UI - Context

**Gathered:** 2026-03-30
**Status:** Ready for planning

<domain>
## Phase Boundary

교수님이 검토하고 편집할 수 있는 강의 스크립트가 생성되며 UI에서 승인 가능하다. 스크립트 생성을 Celery 비동기 태스크로 통합하고, Next.js 포털에 검수/편집 UI를 구축한다. 승인 시 TTS(Phase 4)가 자동 시작된다.

**포함:** 스크립트 Celery 태스크화, FastAPI 스크립트 라우트, Next.js 포털 UI, PDF 파서 전환
**제외:** TTS 실행 자체 (Phase 4), Supabase Auth 연동 (별도 Phase)

</domain>

<decisions>
## Implementation Decisions

### UI 레이아웃
- **D-01:** 2-패널 분할 화면 — 왼쪽 슬라이드 목록(썸네일), 오른쪽 선택된 슬라이드 PNG + 스크립트 편집 영역
- **D-02:** 슬라이드 목록에서 클릭하면 오른쪽 패널이 해당 슬라이드로 전환됨

### 재생성 UX
- **D-03:** 슬라이드마다 개별 "재생성" 버튼 (체크박스 일괄선택 아님)
- **D-04:** 교수님이 편집한 스크립트는 재생성 시 덮어쓰이지 않음 — 편집 여부를 추적하고, 편집된 슬라이드는 재생성 전 확인 프롬프트 표시

### 승인 흐름
- **D-05:** 승인 = TTS 자동 시작. "스크립트 승인" 버튼 클릭 → 바로 Phase 4 TTS 파이프라인 시작
- **D-06:** 전체 슬라이드 스크립트가 확인된 상태에서만 승인 버튼 활성화 (빈 스크립트가 있으면 비활성)

### PDF 파서 전환
- **D-07:** python-pptx 텍스트 추출을 PyMuPDF(fitz) 기반으로 교체
- **D-08:** PyMuPDF span-level 정보 활용 — y좌표 상단 + font size 큼 + bold flags → 제목 자동 감지
- **D-09:** pdfplumber를 표(table) 슬라이드 및 파싱 이상 시 폴백으로 사용
- **D-10:** PPTX 또는 PDF 둘 다 입력으로 허용 (PPTX는 LibreOffice → PDF 변환)
- **D-11:** 발표자 노트(speaker notes) 사용하지 않음 (D-05 from Phase 1)

### Claude's Discretion
- 스크립트 편집기 UI 세부 디자인 (textarea vs rich editor)
- 슬라이드 목록 썸네일 크기와 레이아웃
- 진행률 표시 방식 (기존 SSE 패턴 재사용)
- 스크립트 Celery task 내부 구현 (Phase 2의 vlm_tasks.py 패턴 따름)
- PyMuPDF → SlideRecord 변환 로직 상세

</decisions>

<specifics>
## Specific Ideas

- 2-패널 분할은 코드 에디터(VS Code 스타일)처럼 왼쪽에 파일 목록, 오른쪽에 편집 영역 느낌
- 교수님이 한 슬라이드씩 집중 검수하는 흐름 — 카드 리스트보다 분할 화면이 적합
- 재생성은 "이 슬라이드만 다시" 버튼으로 직관적 동작
- 승인하면 바로 TTS 시작 — 별도 단계 없이 "확인했으니 진행해" 느낌

</specifics>

<canonical_refs>
## Canonical References

### 기술 스택 및 모델 사양
- `CLAUDE.md` §Pipeline Backend — FastAPI, Celery, Redis 스택 명세
- `CLAUDE.md` §PPT Parsing Layer — PyMuPDF로 전환 예정 명시

### 기존 구현 (재사용)
- `lecture_auto/pipeline/script_gen.py` — Claude `claude -p` 기반 스크립트 생성 (Phase 01.1 구현)
- `lecture_auto/tasks/vlm_tasks.py` — Celery 태스크 패턴 (재개 가능, 진행률 발행)
- `lecture_auto/tasks/progress.py` — Redis Pub/Sub 진행률 발행기
- `lecture_auto/api/routes/jobs.py` — FastAPI 작업 라우트 패턴 (submit → status → SSE)
- `lecture_auto/pipeline/parser.py` — 현재 python-pptx 기반 (Phase 3에서 PyMuPDF로 교체)
- `lecture_auto/schemas/manifest.py` — SlideManifest, SlideRecord, ShapeRecord 스키마

### 요구사항
- `.planning/REQUIREMENTS.md` §Script Generation — SCRIPT-01~04
- `.planning/REQUIREMENTS.md` §Portal UI — UI-01, UI-02, UI-03, UI-05

### 이전 결정
- `.planning/phases/01-foundation/1-CONTEXT.md` — D-05: 발표자 노트 제외
- `.planning/phases/02-vlm-pipeline/02-RESEARCH.md` — Celery + Redis + SSE 패턴 확립

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `script_gen.py`: `generate_scripts()`, `call_claude()`, `build_script_prompt()` — 이미 완성, Celery로 감싸기만 하면 됨
- `vlm_tasks.py`: 재개 가능 Celery 태스크 패턴 — `script_tasks.py`에 그대로 복제
- `progress.py`: `publish_progress()`, `get_last_progress()` — 스크립트 진행률에도 재사용
- `api/routes/jobs.py`: submit → status → SSE 패턴 — `routes/scripts.py`에 복제

### Established Patterns
- 파일 기반 체크포인트: `vlm_note_{NNN}.json` 존재 여부로 재개 → 스크립트도 `script_{NNN}.json`으로 동일 패턴
- Redis Pub/Sub + SSE: Late-joiner 지원 포함 → 그대로 재사용
- Celery `concurrency=1`: GPU 워커 단일 프로세스 → 스크립트는 `claude -p` subprocess이므로 CPU 큐 별도 가능

### Integration Points
- `vlm_tasks.py` 완료 후 → `script_tasks.py` 시작 (VLM 노트 JSON 필요)
- `script_tasks.py` 완료 → UI에서 검수 → 승인 → TTS task 시작 (Phase 4)
- Next.js 포털 → FastAPI REST API 호출 (기존 아키텍처 패턴)
- PyMuPDF 파서 → `SlideRecord` 스키마로 변환 (기존 manifest.py 인터페이스 유지)

</code_context>

<deferred>
## Deferred Ideas

- Supabase Auth professor role 연동 — 별도 Phase (INFRA-03)
- 스크립트 히스토리/버전 관리 — v2 feature
- 실시간 협업 편집 — Out of Scope
- PyMuPDF 한국어 벤치 테스트 — 교수님 실제 슬라이드 3~5개로 실시 필요 (구현 전 검증)

</deferred>

---

*Phase: 03-script-ui*
*Context gathered: 2026-03-30*
