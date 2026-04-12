# Lecture Auto UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 교수님 사용 시나리오에 맞게 설정→실행→검수 흐름으로 재정비하고, Mobile-first 반응형 레이아웃 적용

**Architecture:** 기존 vanilla HTML/CSS/JS SPA 구조 유지. HTML 구조 변경 → JS 로직 업데이트 → CSS Mobile-first 재작성 순으로 진행. 백엔드 API 변경 없음.

**Tech Stack:** Vanilla HTML5, CSS3 (custom properties + media queries), JavaScript ES2020, Pretendard 폰트, FastAPI static serving

**Spec:** `docs/superpowers/specs/2026-04-12-lecture-auto-ux-redesign-design.md`

---

## File Map

| 파일 | 변경 유형 | 주요 변경 내용 |
|------|----------|--------------|
| `lecture_auto/demo_static/index.html` | Modify | 탭 라벨/구조, 모달 확장, 로그 토글 버튼 |
| `lecture_auto/demo_static/app.js` | Modify | TABS 배열, 폼 바인딩, 로그 토글, 자동 탭 전환, pendingVoiceBlob |
| `lecture_auto/demo_static/styles.css` | Rewrite | Mobile-first 미디어쿼리 구조로 전면 재작성 |

---

## Task 1: HTML — 탭 구조 정리

**Files:**
- Modify: `lecture_auto/demo_static/index.html:81-88` (tab-bar nav)
- Modify: `lecture_auto/demo_static/index.html:92-120` (panels)

- [ ] **Step 1: 탭 버튼 라벨 변경 및 설정 탭 제거**

`index.html`의 `<nav class="tab-bar">` 섹션을 아래와 같이 교체:

```html
<nav class="tab-bar">
  <div class="tab-list">
    <button class="tab active" data-tab="pipeline">진행상황</button>
    <button class="tab" data-tab="review">슬라이드 검수</button>
    <button class="tab" data-tab="export">다운로드</button>
  </div>
  <span id="uploadMessage" class="status-msg" role="status" aria-live="polite"></span>
</nav>
```

- [ ] **Step 2: 설정 패널 제거 + 로그 섹션 토글 버튼 추가 + 초기 숨김**

`#panel-settings` 전체 블록 제거.

`#panel-pipeline` 내 `.log-section`을 아래로 교체:

```html
<section class="log-section hidden" id="logSection">
  <div class="log-label-row">
    <span class="log-label">실행 로그</span>
  </div>
  <div id="eventList" class="event-list"></div>
</section>
```

파이프라인 패널 스테이지 그리드 아래, 로그 섹션 위에 토글 버튼 추가:

```html
<button class="log-toggle-btn" id="logToggleBtn" type="button">
  로그 보기 ▼
</button>
```

- [ ] **Step 3: 서버 실행 후 수동 확인**

```bash
cd /home/sdlab08/projects/Lecture_Auto
uvicorn lecture_auto.api.main:app --reload --port 8000
```

브라우저에서 `http://localhost:8000/demo` 열고:
- 탭이 "진행상황 / 슬라이드 검수 / 다운로드" 3개인지 확인
- "설정" 탭 없는지 확인
- 파이프라인 탭에 "로그 보기 ▼" 버튼 있고 로그 영역 숨겨져 있는지 확인

- [ ] **Step 4: Commit**

```bash
git add lecture_auto/demo_static/index.html
git commit -m "feat(demo): restructure tabs — remove settings, rename labels, add log toggle btn"
```

---

## Task 2: HTML — 생성 모달 확장

**Files:**
- Modify: `lecture_auto/demo_static/index.html:126-171` (create modal)

- [ ] **Step 1: 모달 폼을 5섹션 구조로 교체**

`<form id="uploadForm" class="create-form">` 내용을 아래로 교체:

```html
<form id="uploadForm" class="create-form">
  <!-- 섹션 1: 파일 업로드 -->
  <label class="dropzone" id="dropzone" for="pdfInput">
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
    </svg>
    <span class="dropzone-main">PDF 파일을 끌어다 놓거나 클릭하여 선택</span>
    <span class="dropzone-hint" id="dropzoneHint">최대 100MB · PDF 형식</span>
    <input type="file" id="pdfInput" name="pdf_file" accept=".pdf" class="sr-only" required />
  </label>

  <!-- 섹션 2: 기본 정보 -->
  <div class="form-grid">
    <label class="field">
      <span class="field-label">강의 제목 <span class="optional">(선택)</span></span>
      <input type="text" name="lecture_name" placeholder="예: 디자인씽킹 기반의 문제해결" class="field-input" />
    </label>
    <label class="field">
      <span class="field-label">목표 시간 (분)</span>
      <input type="number" name="target_minutes" value="8" min="1" max="120" class="field-input" />
    </label>
  </div>

  <!-- 섹션 3: 스크립트 설정 -->
  <div class="form-section">
    <p class="form-section-label">스크립트 설정</p>
    <label class="field">
      <span class="field-label">청중 대상 <span class="optional">(선택)</span></span>
      <input type="text" name="audience" placeholder="예: 학부 2학년 전공자" class="field-input" />
    </label>
    <div class="field">
      <span class="field-label">설명 스타일</span>
      <div class="style-toggle" id="styleToggle" role="group" aria-label="설명 스타일 선택">
        <button type="button" class="style-btn active" data-style="개념 중심">강의식</button>
        <button type="button" class="style-btn" data-style="입문 친화">대화식</button>
        <button type="button" class="style-btn" data-style="시험 대비">간결</button>
      </div>
      <input type="hidden" name="explanation_style" id="explanationStyleInput" value="개념 중심" />
    </div>
  </div>

  <!-- 섹션 4: 음성 설정 -->
  <div class="form-section">
    <p class="form-section-label">음성 설정 <span class="optional">(선택 — 생략 시 기본 음성)</span></p>
    <p class="form-section-hint">3초 이상 음성 샘플을 제공하면 교수님 목소리로 생성됩니다</p>
    <div class="voice-actions">
      <button class="btn-ghost" id="modalRecordButton" type="button">🎤 녹음하기</button>
      <button class="btn-ghost" id="modalStopButton" type="button" disabled>■ 녹음 종료</button>
      <label class="btn-ghost" for="modalVoiceFileInput" style="cursor:pointer;">📁 파일 선택</label>
      <input type="file" id="modalVoiceFileInput" accept="audio/*" class="sr-only" />
    </div>
    <p class="inline-msg" id="modalVoiceStatus"></p>
    <audio id="modalVoicePreview" controls hidden style="width:100%;margin-top:8px;"></audio>
  </div>

  <!-- 섹션 5: 고급 옵션 -->
  <label class="checkbox-row">
    <input type="checkbox" name="use_vlm" checked />
    <span class="checkbox-label">슬라이드 시각 분석 (VLM) — 이미지/다이어그램 포함 슬라이드에 권장</span>
  </label>

  <div class="modal-footer">
    <p id="createMessage" class="create-msg" role="status" aria-live="polite"></p>
    <button type="submit" class="btn-cta btn-cta--full" id="submitButton">
      파이프라인 시작
    </button>
  </div>
</form>
```

- [ ] **Step 2: 수동 확인**

브라우저에서 "새 강의 만들기" 버튼 클릭:
- 모달에 5개 섹션(파일/기본/스크립트/음성/옵션) 모두 표시되는지 확인
- 설명 스타일 토글 3개 버튼(강의식/대화식/간결) 보이는지 확인
- 음성 녹음 버튼과 파일 선택 버튼 보이는지 확인

- [ ] **Step 3: Commit**

```bash
git add lecture_auto/demo_static/index.html
git commit -m "feat(demo): expand create modal with audience, style toggle, voice, VLM sections"
```

---

## Task 3: app.js — 탭·폼·로직 업데이트

**Files:**
- Modify: `lecture_auto/demo_static/app.js`

- [ ] **Step 1: TABS 배열에서 'settings' 제거**

`app.js:60` 의 TABS 정의를 변경:

```js
// Before:
const TABS = ['pipeline', 'review', 'settings', 'export'];

// After:
const TABS = ['pipeline', 'review', 'export'];
```

- [ ] **Step 2: 로그 토글 이벤트 핸들러 추가**

`app.js`에서 tab navigation 섹션 아래에 추가:

```js
// ─── Log toggle ──────────────────────────────────────────────────
const logToggleBtn = document.querySelector('#logToggleBtn');
const logSection   = document.querySelector('#logSection');

logToggleBtn?.addEventListener('click', () => {
  const expanded = !logSection.classList.contains('hidden');
  logSection.classList.toggle('hidden', expanded);
  logToggleBtn.textContent = expanded ? '로그 보기 ▼' : '로그 숨기기 ▲';
});
```

- [ ] **Step 3: 파이프라인 완료 시 자동 탭 전환 추가**

`app.js`에서 폴링 후 job을 처리하는 함수(상태 업데이트 이후)를 찾아 완료 감지 로직 추가.

`renderPipelinePanel` 또는 폴링 콜백에서 이전 상태와 현재 상태를 비교하는 코드 추가:

```js
// 폴링 후 renderJob() 이 호출되는 곳에서:
function onJobUpdated(prevStatus, job) {
  if (prevStatus !== 'completed' && job.status === 'completed') {
    switchTab('review');
    showToast('파이프라인 완료! 슬라이드 검수로 이동합니다.');
  }
}
```

`fetchJob` / `startPolling` 함수에서 `prevStatus`를 추적해 `onJobUpdated` 호출.

`showToast` 함수 추가:

```js
function showToast(msg) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.classList.add('toast--visible'), 10);
  setTimeout(() => { el.classList.remove('toast--visible'); setTimeout(() => el.remove(), 300); }, 3000);
}
```

- [ ] **Step 4: 생성 폼에 audience / explanation_style 바인딩**

`app.js`에서 업로드 폼 submit 핸들러(`#uploadForm` submit)를 찾아, FormData에 이미 포함된 `audience`와 `explanation_style` hidden input이 정상 전송되는지 확인. 스타일 토글 버튼 클릭 핸들러 추가:

```js
// ─── Style toggle ──────────────────────────────────────────────
document.querySelectorAll('.style-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.style-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelector('#explanationStyleInput').value = btn.dataset.style;
  });
});
```

- [ ] **Step 5: pendingVoiceBlob — 모달 음성 업로드 2단계 로직**

`state` 객체에 `pendingVoiceBlob` 추가:

```js
const state = {
  // ... 기존 필드 ...
  pendingVoiceBlob: null,   // 모달에서 선택한 음성, job 생성 후 업로드
};
```

모달 음성 녹음/파일 선택 핸들러 추가 (기존 settings 탭의 녹음 로직 참고):

```js
// ─── Modal voice handlers ────────────────────────────────────
const modalRecordBtn   = document.querySelector('#modalRecordButton');
const modalStopBtn     = document.querySelector('#modalStopButton');
const modalVoiceFile   = document.querySelector('#modalVoiceFileInput');
const modalVoiceStatus = document.querySelector('#modalVoiceStatus');
const modalVoicePreview= document.querySelector('#modalVoicePreview');

modalVoiceFile?.addEventListener('change', e => {
  const file = e.target.files[0];
  if (!file) return;
  state.pendingVoiceBlob = file;
  modalVoicePreview.hidden = false;
  modalVoicePreview.src = URL.createObjectURL(file);
  modalVoiceStatus.textContent = `선택됨: ${file.name}`;
});

// 녹음 로직은 기존 recordButton 핸들러 패턴 그대로 복사, state.pendingVoiceBlob에 저장
```

폼 submit 핸들러에서 job 생성 후 pendingVoiceBlob 자동 업로드:

```js
// uploadForm submit 핸들러 내, job 생성 후:
const job = await api('/demo/api/jobs', { method: 'POST', body: formData });

if (state.pendingVoiceBlob) {
  const vfd = new FormData();
  vfd.append('audio_file', state.pendingVoiceBlob, 'voice_reference.webm');
  await fetch(`/demo/api/jobs/${job.job_id}/voice-reference`, { method: 'POST', body: vfd });
  state.pendingVoiceBlob = null;
}

closeCreateModal();
navigateToDetail(job.job_id);
```

- [ ] **Step 6: 모달 닫힐 때 pendingVoiceBlob 초기화**

`closeCreateModal()` 함수에 추가:

```js
function closeCreateModal() {
  modalCreate.classList.add('hidden');
  uploadForm.reset();
  state.pendingVoiceBlob = null;
  if (modalVoicePreview) { modalVoicePreview.hidden = true; modalVoicePreview.src = ''; }
  if (modalVoiceStatus) modalVoiceStatus.textContent = '';
  // 스타일 토글 초기화
  document.querySelectorAll('.style-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
  document.querySelector('#explanationStyleInput').value = '개념 중심';
}
```

- [ ] **Step 7: 수동 확인**

1. 새 강의 만들기 → 음성 파일 선택 → 파이프라인 시작
2. 브라우저 Network 탭에서 `POST /demo/api/jobs` 후 즉시 `POST /demo/api/jobs/{id}/voice-reference` 호출되는지 확인
3. 설명 스타일 토글 클릭 → `#explanationStyleInput` value가 바뀌는지 확인 (DevTools로 확인)
4. 파이프라인 job을 완료 상태로 만들면 검수 탭으로 자동 이동되는지 확인

- [ ] **Step 8: Commit**

```bash
git add lecture_auto/demo_static/app.js
git commit -m "feat(demo): update tab logic, log toggle, auto-switch on complete, modal voice upload"
```

---

## Task 4: styles.css — Mobile-first 전면 재작성

**Files:**
- Rewrite: `lecture_auto/demo_static/styles.css`

> **Note:** 기존 CSS 토큰(`:root` variables)과 컴포넌트 스타일은 유지하되, 레이아웃 관련 규칙을 mobile-first 구조로 재작성한다. 이 Task는 가장 크고 시각적 회귀가 발생할 수 있으므로 브라우저 확인을 꼼꼼히 한다.

- [ ] **Step 1: 홈 그리드 반응형 적용**

`.lecture-grid` 를 mobile-first로:

```css
/* Mobile: 1열 */
.lecture-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  padding: 16px;
}

/* Tablet+: 2열 */
@media (min-width: 768px) {
  .lecture-grid {
    grid-template-columns: repeat(2, 1fr);
    padding: 24px;
    gap: 16px;
  }
}

/* Desktop: 3열 */
@media (min-width: 1024px) {
  .lecture-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}
```

- [ ] **Step 2: 탭 바 반응형 (모바일 가로 스크롤)**

```css
.tab-list {
  display: flex;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  gap: 0;
}
.tab-list::-webkit-scrollbar { display: none; }

.tab {
  flex-shrink: 0;  /* 탭이 줄어들지 않도록 */
  /* 기존 탭 스타일 유지 */
}
```

- [ ] **Step 3: 생성 모달 — 모바일 풀스크린 + 데스크탑 다이얼로그**

```css
/* Mobile: 풀스크린 시트 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: flex-end;   /* 하단에서 올라오는 시트 */
  justify-content: center;
  z-index: 100;
}

.modal-box {
  width: 100%;
  max-height: 92vh;
  overflow-y: auto;
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  background: var(--surface);
  padding: 20px 16px;
}

/* Desktop: 중앙 다이얼로그 */
@media (min-width: 768px) {
  .modal-backdrop {
    align-items: center;
  }
  .modal-box {
    width: 100%;
    max-width: 560px;
    max-height: 90vh;
    border-radius: var(--radius-lg);
  }
}
```

- [ ] **Step 4: 검수 탭 레이아웃 반응형**

```css
/* Mobile: 세로 스택 */
.review-layout {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--topbar-h) - var(--tabbar-h));
}

.thumb-strip {
  display: flex;
  flex-direction: row;        /* 가로 스크롤 */
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  gap: 8px;
  padding: 8px 12px;
  min-height: 90px;
  max-height: 100px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}

.slide-detail {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

/* Desktop: 좌우 2열 */
@media (min-width: 768px) {
  .review-layout {
    flex-direction: row;
  }

  .thumb-strip {
    flex-direction: column;   /* 세로 스크롤로 전환 */
    overflow-x: hidden;
    overflow-y: auto;
    width: 160px;
    min-height: unset;
    max-height: unset;
    flex-shrink: 0;
    border-bottom: none;
    border-right: 1px solid var(--border);
    padding: 12px 8px;
  }
}
```

- [ ] **Step 5: 스테이지 카드 flex-wrap**

```css
.stage-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 16px;
}

.stage-card {
  flex: 1 1 calc(50% - 8px);  /* 모바일: 2열 */
  min-width: 120px;
}

@media (min-width: 768px) {
  .stage-card {
    flex: 1 1 auto;            /* 데스크탑: 1행에 맞춤 */
  }
}
```

- [ ] **Step 6: 새 컴포넌트 스타일 추가**

토스트, 로그 토글, 모달 폼 섹션, 스타일 토글 버튼 스타일:

```css
/* Toast */
.toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%) translateY(8px);
  background: var(--text);
  color: #fff;
  padding: 10px 20px;
  border-radius: var(--radius);
  font-size: 14px;
  opacity: 0;
  transition: opacity 0.2s, transform 0.2s;
  z-index: 200;
  pointer-events: none;
}
.toast--visible {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

/* Log toggle button */
.log-toggle-btn {
  display: block;
  margin: 8px 16px;
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 6px 14px;
  font-size: 13px;
  color: var(--muted);
  cursor: pointer;
  transition: border-color 0.15s;
}
.log-toggle-btn:hover { border-color: var(--accent); color: var(--accent); }

/* Form sections in modal */
.form-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.form-section-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--muted);
  margin-bottom: 10px;
}
.form-section-hint {
  font-size: 12px;
  color: var(--faint);
  margin-bottom: 10px;
}

/* Style toggle buttons */
.style-toggle {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}
.style-btn {
  flex: 1;
  padding: 7px 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.style-btn.active {
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
  background: var(--accent-dim);
}
.style-btn:hover:not(.active) {
  border-color: var(--border-2);
  color: var(--text);
}
```

- [ ] **Step 7: 수동 확인 (375px 모바일)**

브라우저 DevTools → 기기 에뮬레이션 → iPhone SE(375px):
- 홈 그리드: 1열로 표시
- "새 강의 만들기" 모달: 하단에서 올라오는 풀스크린 시트
- 진행상황 탭: 스테이지 카드가 2열로 줄 바꿈
- 슬라이드 검수 탭: 썸네일 상단 가로 스크롤, 스크립트 아래에 표시

- [ ] **Step 8: 수동 확인 (1280px 데스크탑)**

브라우저 기본 크기(1280px):
- 홈 그리드: 3열
- 모달: 중앙 다이얼로그 (max-width: 560px)
- 검수 탭: 좌측 썸네일 160px + 우측 스크립트 2열

- [ ] **Step 9: Commit**

```bash
git add lecture_auto/demo_static/styles.css
git commit -m "style(demo): mobile-first CSS rewrite — responsive grid, modal sheet, review layout"
```

---

## Task 5: 통합 확인 및 마무리

- [ ] **Step 1: 전체 흐름 E2E 수동 테스트**

시나리오 1 — 새 강의 생성:
1. 홈에서 "새 강의 만들기" 클릭
2. PDF 파일 선택
3. 강의 제목, 목표 시간 입력
4. 청중 대상 입력, 설명 스타일 "대화식" 선택
5. 음성 파일 업로드
6. VLM 체크박스 확인
7. "파이프라인 시작" 클릭
8. 상세 화면 진행상황 탭 자동 진입 확인
9. 로그 섹션 기본 숨김 확인 → "로그 보기 ▼" 클릭 → 로그 펼침 확인
10. 파이프라인 완료 → 검수 탭 자동 이동 + 토스트 확인

시나리오 2 — 기존 강의 재진입:
1. 홈에서 기존 강의 카드 클릭
2. 상세 화면 진입 확인
3. 3개 탭 정상 동작 확인

- [ ] **Step 2: 최종 커밋**

```bash
git add -A
git commit -m "chore(demo): ux redesign complete — settings-to-modal, 3-tab layout, mobile-first CSS"
```

---

## 성공 기준 체크리스트

- [ ] 새 강의 만들기 모달에서 모든 설정(청중/스타일/음성/VLM) 완료 후 파이프라인 시작
- [ ] 상세 화면 탭이 진행상황 / 슬라이드 검수 / 다운로드 3개로 구성됨
- [ ] 진행상황 탭에서 실행 로그가 기본 접힌 상태로 표시됨
- [ ] 파이프라인 완료 시 검수 탭으로 자동 이동 + 토스트 표시
- [ ] 모바일(375px)에서 모든 화면이 깨지지 않고 사용 가능
- [ ] 데스크탑(1280px)에서 검수 탭이 좌우 2열로 표시됨
