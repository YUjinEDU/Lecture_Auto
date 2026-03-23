# Requirements: Lecture Auto

**Defined:** 2026-03-23
**Core Value:** PPT 한 장을 넣으면 교수님 스타일의 강의 스크립트와 음성이 나온다

## v1 Requirements

### Input & Parsing

- [x] **INPUT-01**: 사용자는 PPTX 파일 1개를 업로드할 수 있어야 한다
- [x] **INPUT-02**: 사용자는 강의 생성 시 강의명, 과목명, 수강 대상, 목표 강의 시간, 설명 스타일을 입력할 수 있어야 한다
- [x] **PARSE-01**: 시스템은 PPTX에서 제목, 본문, 발표자 노트, shape metadata를 추출해야 한다
- [x] **PARSE-02**: 시스템은 SmartArt, 차트, OLE 객체 등 python-pptx가 누락하는 shape-type을 감지하고 플래그해야 한다
- [x] **PARSE-03**: 시스템은 파싱 결과를 Slide Manifest JSON으로 저장하고 Pydantic 스키마로 검증해야 한다

### Rendering

- [x] **RENDER-01**: 시스템은 각 슬라이드를 PNG 이미지로 렌더링해야 한다 (LibreOffice CLI)
- [x] **RENDER-02**: 시스템은 한국어 폰트가 정상 렌더링되는지 검증해야 한다
- [x] **RENDER-03**: 시스템은 슬라이드 번호와 매칭되는 렌더링 파일명을 보장해야 한다

### VLM Visual Notes

- [x] **VLM-01**: 시스템은 모든 슬라이드 이미지를 Qwen3-VL에 입력해 visual summary, key elements, layout relations, teaching points, possible confusions를 생성해야 한다
- [x] **VLM-02**: 시스템은 VLM 입력 시 파싱된 텍스트를 함께 제공해 환각을 방지해야 한다 (text-grounded prompting)
- [x] **VLM-03**: 시스템은 VLM 출력을 JSON 스키마로 검증해야 한다

### Script Generation

- [x] **SCRIPT-01**: 시스템은 슬라이드별 구조 정보와 VLM 노트를 결합해 Claude Code로 강의 스크립트를 생성해야 한다
- [x] **SCRIPT-02**: 시스템은 앞뒤 슬라이드 문맥을 반영한 lecture_context를 스크립트 생성에 활용해야 한다
- [x] **SCRIPT-03**: 시스템은 목표 강의 시간에 맞춰 슬라이드별 설명 길이를 조절해야 한다
- [x] **SCRIPT-04**: 시스템은 스크립트 출력에 slide_id, target_seconds, script, keywords, transition_to_next를 포함해야 한다

### TTS Audio

- [ ] **TTS-01**: 시스템은 확정된 스크립트를 Qwen3-TTS로 슬라이드별 음성 파일을 생성해야 한다
- [ ] **TTS-02**: 시스템은 교수님 목소리 Voice Clone을 지원해야 한다 (3초 오디오 등록)
- [ ] **TTS-03**: 시스템은 TTS 생성 전 슬라이드별 음성 미리듣기를 제공해야 한다
- [ ] **TTS-04**: 시스템은 전체 슬라이드 음성을 하나의 강의 음성으로 병합해야 한다

### Portal UI

- [ ] **UI-01**: 시스템은 연구실 포털(Next.js) 내에 강의 자동화 페이지를 제공해야 한다
- [ ] **UI-02**: 시스템은 슬라이드별 스크립트 검수 및 텍스트 편집 UI를 제공해야 한다
- [ ] **UI-03**: 시스템은 파이프라인 진행률과 단계별 상태를 실시간 표시해야 한다
- [ ] **UI-04**: 시스템은 최종 패키지(스크립트 JSON + 음성 파일)를 다운로드할 수 있어야 한다
- [ ] **UI-05**: 시스템은 특정 슬라이드만 선택하여 스크립트/음성을 재생성할 수 있어야 한다

### Infrastructure

- [ ] **INFRA-01**: 시스템은 FastAPI 기반 REST API로 파이프라인을 제공해야 한다
- [ ] **INFRA-02**: 시스템은 비동기 작업 패턴(제출 → 상태 폴링 → 결과 반환)을 지원해야 한다
- [ ] **INFRA-03**: 시스템은 Supabase Auth professor role로 접근을 제한해야 한다
- [x] **INFRA-04**: 시스템은 모든 중간 산출물을 GPU 서버 로컬 디스크에 저장해야 한다
- [ ] **INFRA-05**: 시스템은 각 단계 실행 로그를 저장해야 한다

## v2 Requirements

### Advanced Features

- **ADV-01**: 기존 강의 영상 STT로 교수님 스타일 학습 데이터 생성
- **ADV-02**: 자막 싱크 및 타임라인 생성
- **ADV-03**: Remotion 연동 강의 영상 자동 렌더링
- **ADV-04**: 강의 이력 관리 및 버전 비교
- **ADV-05**: 다중 교수 지원 (여러 교수님 Voice Clone)
- **ADV-06**: 배치 처리 (여러 PPT 동시 처리)

## Out of Scope

| Feature | Reason |
|---------|--------|
| 영상 렌더링 (Remotion 등) | 후속 프로젝트로 분리, 현재 스크립트+음성에 집중 |
| LMS 업로드 자동화 | 수동 업로드로 충분, LMS 연동 복잡도 높음 |
| 실시간 웹 편집기 (WYSIWYG) | 슬라이드별 텍스트 편집이면 충분 |
| 기존 강의 영상 STT | 별도 프로세스로 진행, 파이프라인 범위 외 |
| 모바일 앱 | 웹 포털로 충분, 교수님이 데스크톱 환경 사용 |
| 자동 게시 (교수님 승인 없이) | 교수님 검수 루프 필수, 학술적 정확성 보장 |
| OAuth/외부 인증 | Supabase Auth로 충분 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INPUT-01 | Phase 1 | Complete |
| INPUT-02 | Phase 1 | Complete |
| PARSE-01 | Phase 1 | Complete |
| PARSE-02 | Phase 1 | Complete |
| PARSE-03 | Phase 1 | Complete |
| RENDER-01 | Phase 1 | Complete |
| RENDER-02 | Phase 1 | Complete |
| RENDER-03 | Phase 1 | Complete |
| INFRA-01 | Phase 1 | Pending |
| INFRA-03 | Phase 1 | Pending |
| INFRA-04 | Phase 1 | Complete |
| INFRA-05 | Phase 1 | Pending |
| VLM-01 | Phase 2 | Complete |
| VLM-02 | Phase 2 | Complete |
| VLM-03 | Phase 2 | Complete |
| INFRA-02 | Phase 2 | Pending |
| SCRIPT-01 | Phase 3 | Complete |
| SCRIPT-02 | Phase 3 | Complete |
| SCRIPT-03 | Phase 3 | Complete |
| SCRIPT-04 | Phase 3 | Complete |
| UI-01 | Phase 3 | Pending |
| UI-02 | Phase 3 | Pending |
| UI-03 | Phase 3 | Pending |
| UI-05 | Phase 3 | Pending |
| TTS-01 | Phase 4 | Pending |
| TTS-02 | Phase 4 | Pending |
| TTS-03 | Phase 4 | Pending |
| TTS-04 | Phase 4 | Pending |
| UI-04 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 29 total
- Mapped to phases: 29
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-23*
*Last updated: 2026-03-23 after roadmap creation — all 29 requirements mapped*
