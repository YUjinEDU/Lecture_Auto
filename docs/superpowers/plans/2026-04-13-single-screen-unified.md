# Single-Screen Unified Job View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 3-tab demo UI (진행상황 / 슬라이드검수 / 다운로드) with a single scrolling page that adapts automatically to job status.

**Architecture:** The job's `status` field (`running` / `completed` / `failed`) drives the entire layout — no `activeTab` state, no manual tab switching. The frontend polls `GET /demo/api/jobs/{id}` every 3 s and re-renders. A new `POST /demo/api/jobs/{id}/slides/{n}/approve` endpoint triggers per-slide TTS. Slide data (including `tts_status`) is embedded in the job response.

**Tech Stack:** Vanilla JS / HTML / CSS (no framework — follow existing demo_static patterns), FastAPI backend (Python).

**Spec:** `docs/superpowers/specs/2026-04-13-single-screen-unified-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `lecture_auto/api/routes/demo.py` | Modify | Add approve endpoint; expose tts_status per slide in job response |
| `lecture_auto/demo/state.py` | Modify | Add `tts_status` field to slide data; add `approve_slide()` helper |
| `lecture_auto/demo_static/index.html` | Rewrite | Remove tab bar; add single-scroll section skeleton |
| `lecture_auto/demo_static/styles.css` | Modify | Remove tab styles; add single-scroll + 2-panel + mobile strip layout |
| `lecture_auto/demo_static/app.js` | Refactor | Remove `activeTab`/`switchTab`; add state-driven `renderJobView()`; add approve/autosave/dirty |
| `tests/demo/test_approve_endpoint.py` | Create | Integration tests for approve endpoint |

---

## Task 1: Backend — tts_status per slide in state

**Files:**
- Modify: `lecture_auto/demo/state.py`
- Create: `tests/demo/test_approve_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/demo/test_approve_endpoint.py
from lecture_auto.demo.state import create_job, upsert_slide, get_job

def test_slide_tts_status_defaults_to_pending():
    create_job("test-001", "test.pdf", "Test", 8)
    upsert_slide("test-001", 1, {"script": "Hello world"})
    job = get_job("test-001")
    slide = next(s for s in job["slides"] if s["slide_number"] == 1)
    assert slide.get("tts_status") == "pending"

def test_upsert_slide_preserves_existing_fields():
    create_job("test-002", "test.pdf", "Test", 8)
    upsert_slide("test-002", 1, {"script": "Hello", "tts_status": "done"})
    upsert_slide("test-002", 1, {"script": "Updated"})
    job = get_job("test-002")
    slide = next(s for s in job["slides"] if s["slide_number"] == 1)
    assert slide["tts_status"] == "done"  # preserved
    assert slide["script"] == "Updated"   # updated
```

- [ ] **Step 2: Run to verify FAIL**

```bash
cd /home/sdlab08/projects/Lecture_Auto
python -m pytest tests/demo/test_approve_endpoint.py::test_slide_tts_status_defaults_to_pending -v
```
Expected: FAIL — `tts_status` not present yet

- [ ] **Step 3: Implement — update `upsert_slide` default**

In `lecture_auto/demo/state.py`, update `upsert_slide` to inject `tts_status: "pending"` as a default when creating a new slide entry:

```python
def upsert_slide(job_id: str, slide_number: int, data: dict) -> None:
    with _LOCK:
        job = _JOBS[job_id]
        existing = job.slides.get(slide_number, {"tts_status": "pending"})  # ← add default
        job.slides[slide_number] = {**existing, **copy.deepcopy(data), "slide_number": slide_number}
        job.updated_at = _now()
```

- [ ] **Step 4: Run to verify PASS**

```bash
python -m pytest tests/demo/test_approve_endpoint.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lecture_auto/demo/state.py tests/demo/test_approve_endpoint.py
git commit -m "feat(demo): add tts_status field to slide state"
```

---

## Task 2: Backend — approve endpoint

**Files:**
- Modify: `lecture_auto/api/routes/demo.py`
- Modify: `tests/demo/test_approve_endpoint.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/demo/test_approve_endpoint.py`:

```python
from fastapi.testclient import TestClient
from lecture_auto.api.main import app

client = TestClient(app)

def test_approve_endpoint_returns_ok(monkeypatch):
    # Stub out the heavy pipeline calls
    from lecture_auto.demo import state as demo_state
    demo_state._JOBS.clear()
    demo_state.create_job("job-approve-01", "test.pdf", "Test", 8)
    demo_state.upsert_slide("job-approve-01", 1, {"script": "Hello"})

    def fake_rerun_tts(job_id, slide_number=None):
        pass
    monkeypatch.setattr("lecture_auto.api.routes.demo.rerun_tts_only", fake_rerun_tts)

    resp = client.post("/demo/api/jobs/job-approve-01/slides/1/approve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["slide"] == 1
    assert body["tts"] == "queued"

def test_approve_sets_slide_tts_status_to_queued(monkeypatch):
    from lecture_auto.demo import state as demo_state
    demo_state._JOBS.clear()
    demo_state.create_job("job-approve-02", "test.pdf", "Test", 8)
    demo_state.upsert_slide("job-approve-02", 1, {"script": "Hello"})

    monkeypatch.setattr("lecture_auto.api.routes.demo.rerun_tts_only", lambda *a, **k: None)

    client.post("/demo/api/jobs/job-approve-02/slides/1/approve")
    job = demo_state.get_job("job-approve-02")
    slide = next(s for s in job["slides"] if s["slide_number"] == 1)
    assert slide["tts_status"] == "queued"
    assert slide.get("approved") is True
```

- [ ] **Step 2: Run to verify FAIL**

```bash
python -m pytest tests/demo/test_approve_endpoint.py::test_approve_endpoint_returns_ok -v
```
Expected: FAIL — 404/405 route not found

- [ ] **Step 3: Verify `rerun_tts_only` signature before implementing**

Check the actual signature:
```bash
grep -n "def rerun_tts_only" /home/sdlab08/projects/Lecture_Auto/lecture_auto/demo/*.py
```

Look at the existing call site in `demo.py` line ~159 to confirm argument style. The route must call it the same way.

- [ ] **Step 4: Implement — add approve route to `demo.py`**

First, add `upsert_slide` to the module-level imports from `lecture_auto.demo.state` (alongside the existing `get_job, list_job_summaries` import at top of file).

Then add the route after the `update_slide_script` route:

```python
@router.post("/demo/api/jobs/{job_id}/slides/{slide_number}/approve")
async def approve_slide(job_id: str, slide_number: int):
    _require_job(job_id)
    upsert_slide(job_id, slide_number, {"approved": True, "tts_status": "queued"})
    rerun_tts_only(job_id, slide_number)  # matches existing call style on line ~159
    return {"status": "ok", "slide": slide_number, "tts": "queued"}
```

Note: `upsert_slide` imported at module level — no inline imports.

- [ ] **Step 4: Run to verify PASS**

```bash
python -m pytest tests/demo/test_approve_endpoint.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add lecture_auto/api/routes/demo.py tests/demo/test_approve_endpoint.py
git commit -m "feat(demo): add POST /slides/{n}/approve endpoint"
```

---

## Task 3: Backend — expose tts_done_slides in job response

**Files:**
- Modify: `lecture_auto/demo/state.py` (`to_dict`)
- Modify: `tests/demo/test_approve_endpoint.py`

The frontend needs `tts_done_slides: [1, 3, 5]` to know which per-slide download buttons to enable. We derive this from slide data.

- [ ] **Step 1: Write failing test**

```python
def test_job_dict_includes_tts_done_slides():
    from lecture_auto.demo import state as demo_state
    demo_state._JOBS.clear()
    demo_state.create_job("job-tts-list", "test.pdf", "Test", 8)
    demo_state.upsert_slide("job-tts-list", 1, {"script": "a", "tts_status": "done"})
    demo_state.upsert_slide("job-tts-list", 2, {"script": "b", "tts_status": "pending"})
    demo_state.upsert_slide("job-tts-list", 3, {"script": "c", "tts_status": "done"})
    job = demo_state.get_job("job-tts-list")
    assert job["tts_done_slides"] == [1, 3]
```

- [ ] **Step 2: Run to verify FAIL**

```bash
python -m pytest tests/demo/test_approve_endpoint.py::test_job_dict_includes_tts_done_slides -v
```

- [ ] **Step 3: Implement — add `tts_done_slides` to `DemoJob.to_dict`**

In `lecture_auto/demo/state.py`, update `to_dict`:

```python
def to_dict(self) -> dict:
    payload = copy.deepcopy(self.__dict__)
    slides_list = [self.slides[key] for key in sorted(self.slides)]
    payload["slides"] = slides_list
    payload["tts_done_slides"] = [
        s["slide_number"] for s in slides_list if s.get("tts_status") == "done"
    ]
    return payload
```

Also update `lecture_auto/demo/synthesis.py` to call `upsert_slide(job_id, n, {"tts_status": "done"})` after TTS completes for a slide. Find the correct location:

```bash
grep -n "tts\|audio_\|wav" /home/sdlab08/projects/Lecture_Auto/lecture_auto/demo/synthesis.py | head -30
```

Add the upsert call immediately after the WAV file is written for each slide. Example pattern to find and augment:

```python
# existing: write WAV file
wav_path.write_bytes(audio_data)
# ADD after write:
from lecture_auto.demo.state import upsert_slide
upsert_slide(job_id, slide_number, {"tts_status": "done"})
```

Also confirm `stages` is serialized in `to_dict` — check `state.py` `to_dict` method. Since `DemoJob` uses `dataclasses` and `to_dict` calls `copy.deepcopy(self.__dict__)`, `stages` IS included automatically. No change needed.

- [ ] **Step 4: Run to verify PASS**

```bash
python -m pytest tests/demo/test_approve_endpoint.py -v
```

- [ ] **Step 5: Commit**

```bash
git add lecture_auto/demo/state.py lecture_auto/demo/synthesis.py
git commit -m "feat(demo): expose tts_done_slides; mark tts_status=done after synthesis"
```

---

## Task 4: HTML — remove tabs, add single-scroll skeleton

**Files:**
- Modify: `lecture_auto/demo_static/index.html`

Read `index.html` fully before editing (81–120 lines area has the tab structure).

- [ ] **Step 1: Remove the tab bar**

Find and delete the `<nav class="tab-bar">...</nav>` block (lines ~81–86 area).

- [ ] **Step 2: Replace the 3 hidden panels with single-scroll sections**

Replace:
```html
<div id="panel-pipeline" class="panel">...</div>
<div id="panel-review" class="panel hidden">...</div>
<div id="panel-export" class="panel hidden">...</div>
```

With:
```html
<!-- STATE: running — shown when job.status === 'running' -->
<section id="section-progress" class="job-section hidden">
  <div id="progress-steps"></div>
  <div id="progress-log-toggle"></div>
  <div id="progress-log" class="log-panel hidden"></div>
  <div id="review-placeholder" class="review-placeholder">
    <span>⏳ 파이프라인 완료 후 열립니다</span>
  </div>
</section>

<!-- STATE: completed — progress summary (collapsed) -->
<section id="section-summary" class="job-section hidden">
  <details id="progress-summary">
    <summary>진행 요약 보기</summary>
    <div id="summary-steps"></div>
  </details>
</section>

<!-- Slide review — shown when completed -->
<section id="section-review" class="job-section hidden">
  <div class="review-panel">
    <aside id="slide-list" class="slide-list"></aside>
    <div id="slide-view" class="slide-view">
      <div id="slide-image-wrap"></div>
      <div id="script-editor-wrap">
        <textarea id="script-editor"></textarea>
        <span id="save-indicator" class="save-indicator hidden">저장 중…</span>
      </div>
      <div class="slide-actions">
        <button id="btn-regenerate" class="btn-secondary">재생성</button>
        <button id="btn-approve" class="btn-primary">승인 → TTS 시작</button>
      </div>
    </div>
  </div>
</section>

<!-- Download — shown when completed -->
<section id="section-download" class="job-section hidden">
  <div id="download-content"></div>
</section>

<!-- STATE: failed -->
<section id="section-failed" class="job-section hidden">
  <div id="error-message"></div>
  <div id="error-log-toggle"></div>
  <div id="error-log" class="log-panel hidden"></div>
  <button id="btn-retry" class="btn-primary">재시도</button>
</section>
```

- [ ] **Step 3: Verify HTML is valid**

```bash
python3 -c "
from html.parser import HTMLParser
p = HTMLParser()
p.feed(open('lecture_auto/demo_static/index.html').read())
print('HTML parse OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add lecture_auto/demo_static/index.html
git commit -m "feat(demo): replace tab panels with single-scroll section skeleton"
```

---

## Task 5: CSS — remove tab styles, add new layout

**Files:**
- Modify: `lecture_auto/demo_static/styles.css`

- [ ] **Step 1: Remove tab-related CSS**

Find and delete selectors: `.tab-bar`, `.tab`, `.tab.active`, `.panel.hidden` (the tab-specific hidden logic — keep any other `.hidden` utilities).

- [ ] **Step 2: Add single-scroll layout styles**

Append to `styles.css`:

```css
/* ── Single-scroll layout ─────────────────────── */
.job-section { margin-bottom: 1.5rem; }

/* Review 2-panel */
.review-panel {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 1rem;
  min-height: 400px;
}

.slide-list {
  overflow-y: auto;
  max-height: 70vh;
  border-right: 1px solid #e5e7eb;
  padding-right: 0.5rem;
}

.slide-list-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  cursor: pointer;
  border-radius: 6px;
}
.slide-list-item.active { background: #ecfdf5; }
.slide-list-item img { width: 56px; height: 36px; object-fit: cover; border-radius: 3px; }

.slide-view { display: flex; flex-direction: column; gap: 0.75rem; }
#slide-image-wrap img { width: 100%; border-radius: 8px; border: 1px solid #e5e7eb; }

#script-editor {
  width: 100%;
  min-height: 140px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0.625rem;
  font-size: 0.875rem;
  resize: vertical;
}

.save-indicator { font-size: 0.75rem; color: #6b7280; }

.slide-actions { display: flex; gap: 0.5rem; }

/* Review placeholder (running state) */
.review-placeholder {
  display: flex; align-items: center; justify-content: center;
  height: 120px; border: 2px dashed #d1d5db; border-radius: 8px;
  color: #9ca3af; margin-top: 1rem;
}

/* Download section */
.download-table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
.download-table th, .download-table td { padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #f3f4f6; }
.download-table th { color: #6b7280; font-weight: 500; }
.download-row-disabled { opacity: 0.4; pointer-events: none; }

/* Mobile (< 768px) */
@media (max-width: 767px) {
  .review-panel { grid-template-columns: 1fr; }
  .slide-list {
    display: flex;
    flex-direction: row;
    overflow-x: auto;
    max-height: 80px;
    border-right: none;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 0.5rem;
    gap: 0.5rem;
  }
  .slide-list-item img { width: 80px; height: 52px; }
  .slide-list-item span { display: none; } /* hide label on mobile */
}

/* Tablet (768–1024px) */
@media (min-width: 768px) and (max-width: 1023px) {
  .review-panel { grid-template-columns: 120px 1fr; }
}
```

- [ ] **Step 3: Commit**

```bash
git add lecture_auto/demo_static/styles.css
git commit -m "feat(demo): add single-scroll + 2-panel CSS, remove tab styles"
```

---

## Task 6: JS — replace tab state machine with status-driven render

**Files:**
- Modify: `lecture_auto/demo_static/app.js`

This is the core refactor. Read the full `app.js` before editing.

- [ ] **Step 1: Remove activeTab state and switchTab**

In `app.js` state object, remove `activeTab: 'pipeline'`.

Delete the entire "Tab navigation" section (~lines 60–75):
```js
// ─── Tab navigation ──────────────────────────────────────────────
function switchTab(name) { ... }
document.querySelectorAll('[data-tab]').forEach(...);
```

- [ ] **Step 2: Add `renderJobView(job)` — the status-driven entry point**

Add near the top of the render functions section:

```js
// ─── Status-driven layout ─────────────────────────────────────────
const SECTIONS = ['progress', 'summary', 'review', 'download', 'failed'];

function showSections(...names) {
  SECTIONS.forEach(s => {
    document.getElementById(`section-${s}`)?.classList.toggle('hidden', !names.includes(s));
  });
}

function renderJobView(job) {
  const { status } = job;
  if (status === 'running' || status === 'queued') {
    showSections('progress');
    renderProgressSection(job);
  } else if (status === 'completed') {
    showSections('summary', 'review', 'download');
    renderSummarySection(job);
    renderReviewSection(job);
    renderDownloadSection(job);
  } else if (status === 'failed' || status === 'stopped') {
    showSections('failed');
    renderFailedSection(job);
  }
}
```

- [ ] **Step 3: Replace all `switchTab(...)` call sites**

Find all calls to `switchTab(...)` in `app.js` (check lines ~283, ~972) and remove them — `renderJobView` handles layout automatically.

- [ ] **Step 4: Wire `renderJobView` into the polling loop**

Find the existing polling / job-refresh logic (likely around the `refreshJob` or `loadJob` function). Replace any `renderProgress(job)` / tab-specific calls with `renderJobView(job)`.

- [ ] **Step 5: Commit**

```bash
git add lecture_auto/demo_static/app.js
git commit -m "refactor(demo): replace activeTab/switchTab with status-driven renderJobView"
```

---

## Task 7: JS — progress section renderer

**Files:**
- Modify: `lecture_auto/demo_static/app.js`

Replace (or rename) the existing `renderProgress` to `renderProgressSection`. It should target the new `#section-progress` DOM, not `#panel-pipeline`.

- [ ] **Step 1: Rename render target**

Find the function that renders pipeline steps (currently writes into `#panel-pipeline` or its children). Update to write into `#progress-steps` and `#progress-log`.

Keep the existing step rendering logic intact — only change the target element IDs.

- [ ] **Step 2: Add `renderSummarySection(job)`**

```js
function renderSummarySection(job) {
  const el = document.getElementById('summary-steps');
  if (!el) return;
  el.innerHTML = job.stages.map(s => `
    <div class="stage-row">
      <span class="stage-icon">${s.status === 'done' ? '✅' : s.status === 'failed' ? '❌' : '○'}</span>
      <span>${s.label}</span>
    </div>
  `).join('');
}
```

- [ ] **Step 3: Add `renderFailedSection(job)`**

```js
function renderFailedSection(job) {
  const msgEl = document.getElementById('error-message');
  if (msgEl) msgEl.textContent = job.error || '알 수 없는 오류가 발생했습니다.';
  // Use once: true so the listener doesn't stack on re-renders
  document.getElementById('btn-retry')?.addEventListener('click', () => retryJob(job.job_id), { once: true });
}

async function retryJob(jobId) {
  // Uses existing /rerun endpoint — performs full pipeline restart from upload.
  // Per spec, partial resume (from failed step) is a future enhancement;
  // the `recovery.can_resume_from` field in job state carries this info for later.
  await fetch(`/demo/api/jobs/${jobId}/rerun`, { method: 'POST' });
}
```

- [ ] **Step 4: Commit**

```bash
git add lecture_auto/demo_static/app.js
git commit -m "feat(demo): add renderSummarySection and renderFailedSection"
```

---

## Task 8: JS — slide review 2-panel with approve + dirty state

**Files:**
- Modify: `lecture_auto/demo_static/app.js`

- [ ] **Step 1: Add `renderReviewSection(job)`**

```js
let _currentSlide = 1;
let _scriptDirty = false;

function renderReviewSection(job) {
  const list = document.getElementById('slide-list');
  if (!list) return;
  list.innerHTML = job.slides.map(s => `
    <div class="slide-list-item ${s.slide_number === _currentSlide ? 'active' : ''}"
         data-slide="${s.slide_number}">
      <img src="/demo/api/jobs/${job.job_id}/slides/${s.slide_number}/png"
           alt="Slide ${s.slide_number}" loading="lazy">
      <span>S${s.slide_number}${s.approved ? ' ✅' : ''}</span>
    </div>
  `).join('');

  list.querySelectorAll('.slide-list-item').forEach(item => {
    item.addEventListener('click', () => {
      if (_scriptDirty) {
        if (!confirm('편집 내용이 저장되지 않았습니다. 다른 슬라이드로 이동할까요?')) return;
        _scriptDirty = false;
      }
      _currentSlide = parseInt(item.dataset.slide, 10);
      renderReviewSection(job);
    });
  });

  renderSlideView(job, _currentSlide);
}

function renderSlideView(job, slideNum) {
  const slide = job.slides.find(s => s.slide_number === slideNum);
  if (!slide) return;

  const imgWrap = document.getElementById('slide-image-wrap');
  if (imgWrap) imgWrap.innerHTML = `<img src="/demo/api/jobs/${job.job_id}/slides/${slideNum}/png" alt="Slide ${slideNum}">`;

  const editor = document.getElementById('script-editor');
  if (editor) {
    editor.value = slide.script || '';
    editor.oninput = () => {
      _scriptDirty = true;
      document.getElementById('save-indicator')?.classList.remove('hidden');
    };
    editor.onblur = () => autoSaveScript(job.job_id, slideNum, editor.value);
  }

  const btnApprove = document.getElementById('btn-approve');
  if (btnApprove) {
    btnApprove.disabled = slide.tts_status === 'queued' || slide.tts_status === 'done';
    btnApprove.textContent = slide.tts_status === 'queued' ? 'TTS 생성 중…'
      : slide.tts_status === 'done' ? '승인 완료 ✅' : '승인 → TTS 시작';
    btnApprove.onclick = () => approveSlide(job.job_id, slideNum);
  }

  const btnRegen = document.getElementById('btn-regenerate');
  if (btnRegen) {
    btnRegen.onclick = () => {
      if (_scriptDirty && !confirm('편집 내용이 사라집니다. 계속할까요?')) return;
      _scriptDirty = false;
      rerunTts(job.job_id, slideNum);
    };
  }
}
```

- [ ] **Step 2: Add auto-save helper**

```js
async function autoSaveScript(jobId, slideNum, text) {
  const indicator = document.getElementById('save-indicator');
  try {
    // Backend endpoint is PUT (not PATCH) — matches existing demo.py route
    await fetch(`/demo/api/jobs/${jobId}/slides/${slideNum}/script`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ script: text }),
    });
    _scriptDirty = false;
    if (indicator) indicator.classList.add('hidden');
  } catch {
    if (indicator) indicator.textContent = '저장 실패';
  }
}
```

- [ ] **Step 3: Add approve helper**

```js
async function approveSlide(jobId, slideNum) {
  await fetch(`/demo/api/jobs/${jobId}/slides/${slideNum}/approve`, { method: 'POST' });
  // polling will pick up tts_status change on next tick
}
```

- [ ] **Step 4: Commit**

```bash
git add lecture_auto/demo_static/app.js
git commit -m "feat(demo): add 2-panel slide review with approve + auto-save dirty state"
```

---

## Task 9: JS — download section with 3-tier activation

**Files:**
- Modify: `lecture_auto/demo_static/app.js`

- [ ] **Step 1: Add `renderDownloadSection(job)`**

```js
function renderDownloadSection(job) {
  const el = document.getElementById('download-content');
  if (!el) return;

  const totalSlides = job.slides.length;
  const doneSlides = (job.tts_done_slides || []).length;
  const allDone = doneSlides === totalSlides && totalSlides > 0;
  const noneDone = doneSlides === 0;

  const statusLabel = noneDone
    ? 'TTS 생성 대기 중'
    : allDone ? '' : `${doneSlides}/${totalSlides} 슬라이드 완료`;

  const wholeRowClass = (noneDone || !allDone) ? 'download-row-disabled' : '';

  el.innerHTML = `
    <table class="download-table">
      <thead><tr><th>파일</th><th>범위</th><th>상태</th><th></th></tr></thead>
      <tbody>
        <tr class="${wholeRowClass}">
          <td>음성 (WAV)</td><td>전체</td>
          <td>${statusLabel}</td>
          <td>${allDone ? `<a href="/demo/api/jobs/${job.job_id}/audio/merged" download>↓</a>` : ''}</td>
        </tr>
        <tr class="${wholeRowClass}">
          <td>음성 (MP3)</td><td>전체</td>
          <td>${allDone ? '' : statusLabel}</td>
          <td>${allDone ? `<a href="/demo/api/jobs/${job.job_id}/audio/merged" download="lecture_merged.mp3">↓</a>` : ''}</td>
        </tr>
        <tr class="${wholeRowClass}">
          <td>스크립트</td><td>전체</td>
          <td>${statusLabel}</td>
          <td>${allDone ? `<a href="/demo/api/jobs/${job.job_id}/package/download" download>↓ ZIP</a>` : ''}</td>
        </tr>
      </tbody>
    </table>
    <h4 style="margin-top:1rem">슬라이드별</h4>
    <table class="download-table">
      <tbody>
        ${job.slides.map(s => {
          const done = (job.tts_done_slides || []).includes(s.slide_number);
          return `<tr class="${done ? '' : 'download-row-disabled'}">
            <td>슬라이드 ${s.slide_number}</td>
            <td>${done ? `<a href="/demo/api/jobs/${job.job_id}/audio/${s.slide_number}/wav" download>음성↓</a>` : '생성 대기'}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
    ${allDone ? `<button class="btn-primary" style="margin-top:1rem"
      onclick="downloadZip('${job.job_id}', ${job.slides.some(s => !s.approved)})">
      선택 항목 ZIP 다운로드
    </button>` : ''}
  `;
}

function downloadZip(jobId, hasUnapproved) {
  if (hasUnapproved && !confirm('일부 슬라이드가 미승인 상태입니다. 그래도 다운로드할까요?')) return;
  window.location.href = `/demo/api/jobs/${jobId}/package/download`;
}
```

- [ ] **Step 2: Commit**

```bash
git add lecture_auto/demo_static/app.js
git commit -m "feat(demo): add download section with 3-tier activation model"
```

---

## Task 10: End-to-end smoke test

- [ ] **Step 1: Start the dev server**

```bash
cd /home/sdlab08/projects/Lecture_Auto
uv run uvicorn lecture_auto.api.main:app --reload --port 8000
```

- [ ] **Step 2: Manual flow check**

1. Open `http://localhost:8000/demo`
2. Create a new job (upload a PDF)
3. Verify: tab bar is gone, progress section shows
4. Wait for completion (or check with a pre-completed job_id)
5. Verify: progress section collapses to summary, slide review appears, download section shows "TTS 생성 대기 중"
6. Click a slide → verify PNG + script editor loads
7. Edit script → verify "저장 중…" indicator → verify saves on blur
8. Click 재생성 with unsaved edits → verify confirm dialog
9. Click 승인 → verify button changes to "TTS 생성 중…"
10. After TTS (or mock): verify download row for that slide activates
11. Visit `http://localhost:8000/demo` on mobile viewport (< 768px) → verify thumbnail strip layout

- [ ] **Step 3: Run all demo tests**

```bash
python -m pytest tests/demo/ -v
```

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -p
git commit -m "fix(demo): post-integration smoke test fixes"
```

---

## Rollback

If anything goes wrong, the tab-based UI is preserved in git history at commit `180b12c`. To revert:

```bash
git checkout 180b12c -- lecture_auto/demo_static/
```
