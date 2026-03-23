# Roadmap: Lecture Auto

## Overview

PPTX 파일을 입력받아 교수님 스타일의 강의 스크립트와 음성을 자동 생성하는 파이프라인. 4개 페이즈로 순차 구축: 파싱/렌더링 기반 → VLM 비동기 처리 → 스크립트 생성 + 검수 UI → TTS + 다운로드 전달. 각 페이즈는 다음 페이즈를 언블록하는 검증 가능한 산출물을 생성한다.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - FastAPI 스켈레톤 + PPTX 파싱 + 슬라이드 렌더링 인프라
- [ ] **Phase 2: VLM Pipeline** - 비동기 작업 시스템 + Qwen3-VL 시각 노트 생성
- [ ] **Phase 3: Script + UI** - Claude Code 스크립트 생성 + 교수님 검수 편집 UI
- [ ] **Phase 4: TTS + Delivery** - Qwen3-TTS 음성 합성 + Voice Clone + 최종 패키지 다운로드

## Phase Details

### Phase 1: Foundation
**Goal**: 검증된 슬라이드 JSON과 PNG 아티팩트를 생성할 수 있는 인프라가 구동된다
**Depends on**: Nothing (first phase)
**Requirements**: INPUT-01, INPUT-02, PARSE-01, PARSE-02, PARSE-03, RENDER-01, RENDER-02, RENDER-03, INFRA-01, INFRA-03, INFRA-04, INFRA-05
**Success Criteria** (what must be TRUE):
  1. PPTX 파일을 업로드하면 슬라이드별 텍스트/노트/shape metadata가 담긴 Slide Manifest JSON이 생성된다
  2. 각 슬라이드가 한국어 폰트가 정상인 PNG 이미지로 렌더링되며, 슬라이드 번호와 파일명이 1:1 매칭된다
  3. SmartArt/차트 등 python-pptx가 누락하는 shape-type이 감지되어 content_source 필드에 플래그된다
  4. Pydantic 스키마 검증을 통과한 JSON만 /data/work/{job_id}/ 디렉토리에 저장된다
  5. FastAPI 서버가 기동되고 professor role 인증이 적용된 헬스체크 엔드포인트에 응답한다
**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md — Project skeleton, Pydantic v2 schemas, storage helper
- [x] 01-02-PLAN.md — PPTX parsing with python-pptx shape classification
- [x] 01-03-PLAN.md — LibreOffice slide rendering + Korean tofu detection
- [ ] 01-04-PLAN.md — FastAPI app, JWT auth, /upload endpoint integration

### Phase 2: VLM Pipeline
**Goal**: 재시작 가능한 비동기 작업이 슬라이드별 VLM 시각 노트 JSON을 생성한다
**Depends on**: Phase 1
**Requirements**: VLM-01, VLM-02, VLM-03, INFRA-02
**Success Criteria** (what must be TRUE):
  1. PPTX 업로드 후 작업이 큐에 등록되고 UI에서 단계별 진행률(%)을 실시간 확인할 수 있다
  2. 파이프라인이 중단 후 재시작되어도 이미 완료된 슬라이드는 건너뛰고 미완료 슬라이드부터 재개된다
  3. 각 슬라이드에 대해 visual summary, key elements, teaching points를 포함한 VLM 노트 JSON이 생성된다
  4. VLM이 파싱 텍스트와 30% 미만 토큰 겹침을 보이는 슬라이드에 needs_review 플래그가 표시된다
**Plans**: TBD

### Phase 3: Script + UI
**Goal**: 교수님이 검토하고 편집할 수 있는 강의 스크립트가 생성되며 UI에서 승인 가능하다
**Depends on**: Phase 2
**Requirements**: SCRIPT-01, SCRIPT-02, SCRIPT-03, SCRIPT-04, UI-01, UI-02, UI-03, UI-05
**Success Criteria** (what must be TRUE):
  1. 슬라이드별로 앞뒤 문맥이 반영된 강의 스크립트가 생성되며 목표 강의 시간에 맞는 길이로 조절된다
  2. 스크립트 출력에 slide_id, target_seconds, script, keywords, transition_to_next 필드가 포함된다
  3. 교수님이 포털 UI에서 슬라이드 썸네일과 나란히 스크립트를 확인하고 인라인 편집 후 저장할 수 있다
  4. 특정 슬라이드만 선택해 스크립트를 재생성할 수 있으며 교수님이 편집한 내용은 재생성 시 덮어쓰이지 않는다
**Plans**: TBD

### Phase 4: TTS + Delivery
**Goal**: 교수님이 승인한 스크립트로 교수님 목소리 음성이 생성되고 최종 패키지를 다운로드할 수 있다
**Depends on**: Phase 3
**Requirements**: TTS-01, TTS-02, TTS-03, TTS-04, UI-04
**Success Criteria** (what must be TRUE):
  1. 교수님 3초 오디오 샘플로 Voice Clone을 등록하면 이후 TTS가 교수님 목소리로 생성된다
  2. 각 슬라이드 음성 파일을 개별 미리듣기로 확인한 후 전체 병합 음성을 생성할 수 있다
  3. 최종 패키지(스크립트 JSON + 슬라이드별 WAV + 병합 WAV)를 포털에서 다운로드할 수 있다
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/4 | In Progress|  |
| 2. VLM Pipeline | 0/TBD | Not started | - |
| 3. Script + UI | 0/TBD | Not started | - |
| 4. TTS + Delivery | 0/TBD | Not started | - |
