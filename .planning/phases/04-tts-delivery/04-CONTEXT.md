# Phase 4: TTS + Delivery - Context

**Gathered:** 2026-03-31
**Status:** Ready for planning

<domain>
## Phase Boundary

교수님이 승인한 스크립트로 교수님 목소리 음성이 생성되고 최종 패키지를 다운로드할 수 있다. Phase 3의 스크립트 승인 엔드포인트를 TTS Celery 태스크에 연결하고, Voice Clone 등록, 음성 미리듣기, 최종 패키지 다운로드 UI를 구축한다.

**포함:** TTS Celery 태스크화, Voice Clone 등록 (브라우저 녹음 + 파일 업로드), 음성 미리듣기 플레이어, 최종 패키지 다운로드 (MP4 포함)
**제외:** Supabase Auth 연동 (별도 Phase), 실시간 편집기 (Out of Scope)

</domain>

<decisions>
## Implementation Decisions

### Voice Clone 등록
- **D-01:** 브라우저 녹음과 파일 업로드 둘 다 지원 — 교수님이 편한 방식 선택
- **D-02:** 한 번 등록하면 모든 강의에 적용 — 교수님 프로필에 voice_ref 저장, 강의별 등록 아님
- **D-03:** 3초 오디오 클립 (Qwen3-TTS Voice Clone 요구사항)

### 음성 미리듣기
- **D-04:** 슬라이드별 재생 버튼 — 각 슬라이드 옆에 WAV 재생 컨트롤
- **D-05:** TTS 결과가 마음에 안 들면 스크립트를 수정하고 해당 슬라이드만 재TTS 가능 (Phase 3의 재생성 패턴 재사용)

### 최종 패키지
- **D-06:** 최종 패키지에 MP4 비디오 포함 — 스크립트 JSON + 슬라이드별 WAV + 병합 WAV + 강의 MP4
- **D-07:** ZIP 형태로 한 번에 다운로드

### 승인 → TTS 연결
- **D-08:** Phase 3의 approve 엔드포인트가 TTS Celery 태스크를 트리거 (현재 "deferred to Phase 4" 주석 있음)

### Claude's Discretion
- TTS Celery task 내부 구현 (Phase 2 vlm_tasks.py 패턴 따름, gpu_queue 사용)
- Voice Clone 등록 API 엔드포인트 설계
- 브라우저 녹음 WebAudio API 구현 상세
- 패키지 ZIP 생성 방식
- MP4 비디오 생성 (기존 video.py의 assemble_video 재사용)
- 음성 미리듣기 UI 컴포넌트 세부 디자인

</decisions>

<specifics>
## Specific Ideas

- Voice Clone은 교수님 프로필 개념 — 한 번 등록하면 끝, 매번 업로드 불필요
- 브라우저 녹음은 MediaRecorder API 사용, 3초 카운트다운 후 자동 정지
- 미리듣기는 HTML5 `<audio>` 태그로 간단하게 — 별도 플레이어 라이브러리 불필요
- 최종 패키지는 교수님이 "다운로드" 버튼 하나로 받는 것

</specifics>

<canonical_refs>
## Canonical References

### 기술 스택 및 모델 사양
- `CLAUDE.md` §TTS Layer — Qwen3-TTS-12Hz-1.7B-CustomVoice, vLLM-Omni, soundfile
- `CLAUDE.md` §Pipeline Backend — FastAPI, Celery, Redis

### 기존 구현 (재사용)
- `lecture_auto/pipeline/tts.py` — `load_tts()`, `synthesize_slide()`, `synthesize_audio()`, voice clone via `voice_ref_path` (Phase 01.1 구현)
- `lecture_auto/pipeline/video.py` — `create_slide_clip()`, `concat_clips()`, `assemble_video()` (Phase 01.1 구현)
- `lecture_auto/tasks/vlm_tasks.py` — 재개 가능 Celery task 패턴 (Phase 2)
- `lecture_auto/tasks/progress.py` — Redis Pub/Sub 진행률 발행기
- `lecture_auto/api/routes/scripts.py` — approve 엔드포인트 (Phase 3, "TTS trigger deferred to Phase 4" 주석)
- `lecture_auto/tasks/celery_app.py` — `gpu_queue` + `cpu_queue` 라우팅 설정
- `lecture_auto/storage/jobs.py` — JobPaths with `audio/`, `artifacts/` 디렉토리

### 요구사항
- `.planning/REQUIREMENTS.md` §TTS Audio — TTS-01, TTS-02, TTS-03, TTS-04
- `.planning/REQUIREMENTS.md` §Portal UI — UI-04

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tts.py`: 완전한 TTS 구현 — Celery로 감싸기만 하면 됨 (Phase 2/3 패턴 동일)
- `video.py`: MP4 비디오 조립 — `assemble_video(png_dir, wav_dir, output_path)` 그대로 사용
- `vlm_tasks.py`: 재개 가능 Celery 태스크 패턴 → `tts_tasks.py`에 복제
- `progress.py`: 진행률 발행 → TTS 진행률에도 재사용
- `scripts.py` routes: CRUD + SSE 패턴 → TTS 라우트에 복제

### Established Patterns
- 파일 기반 체크포인트: `audio_{NNN}.wav` 존재 여부로 재개
- Redis Pub/Sub + SSE: Late-joiner 지원
- Celery `gpu_queue`: TTS 모델은 GPU 필요 → `gpu_queue` 사용 (VLM과 순차 실행)

### Integration Points
- `approve_scripts` → TTS Celery task 트리거 (Phase 4에서 연결)
- TTS 완료 → `artifacts/` 에 ZIP 패키지 생성
- Next.js 포털 → FastAPI TTS/download 라우트 호출

</code_context>

<deferred>
## Deferred Ideas

- Supabase Auth 연동 — 별도 Phase (INFRA-03)
- TTS 속도/톤 조절 파라미터 — v2 feature
- 여러 교수님 Voice Clone 프로필 관리 — v2 feature
- 실시간 TTS 스트리밍 재생 — Out of Scope

</deferred>

---

*Phase: 04-tts-delivery*
*Context gathered: 2026-03-31*
