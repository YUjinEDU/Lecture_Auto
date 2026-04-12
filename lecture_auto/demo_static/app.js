// ─── State ───────────────────────────────────────────────────────
const state = {
  jobs: [],
  job: null,
  selectedSlide: null,
  pollTimer: null,
  mediaRecorder: null,
  mediaStream: null,
  audioChunks: [],
  voiceBlob: null,
  activeTab: 'pipeline',
  currentView: 'home',
  pendingVoiceBlob: null,   // voice file from modal, uploaded after job creation
};

// ─── DOM refs ────────────────────────────────────────────────────
const uploadForm        = document.querySelector('#uploadForm');
const submitButton      = document.querySelector('#submitButton');
const createMessage     = document.querySelector('#createMessage');
const uploadMessage     = document.querySelector('#uploadMessage');
const lectureGrid       = document.querySelector('#lectureGrid');
const emptyState        = document.querySelector('#emptyState');
const jobCountBadge     = document.querySelector('#jobCountBadge');
const detailLectureName = document.querySelector('#detailLectureName');
const stageGrid         = document.querySelector('#stageGrid');
const eventList         = document.querySelector('#eventList');
const jobControls       = document.querySelector('#jobControls');
const slideThumbStrip   = document.querySelector('#slideThumbStrip');
const slideDetail       = document.querySelector('#slideDetail');
const outputsArea       = document.querySelector('#outputsArea');
const lastUpdated       = document.querySelector('#lastUpdated');
const evidenceModal     = document.querySelector('#evidenceModal');
const evidenceModalBody = document.querySelector('#evidenceModalBody');
const closeEvidenceModal = document.querySelector('#closeEvidenceModal');
const modalCreate       = document.querySelector('#modalCreate');

// ─── View routing ─────────────────────────────────────────────────
function showView(name) {
  state.currentView = name;
  document.querySelector('#view-home')?.classList.toggle('view--hidden', name !== 'home');
  document.querySelector('#view-detail')?.classList.toggle('view--hidden', name !== 'detail');
}

function navigateToDetail(jobId) {
  window.location.hash = jobId;
  showView('detail');
  switchTab('pipeline');
  startPolling(jobId);
}

function navigateHome() {
  window.location.hash = '';
  showView('home');
  stopPolling();
  state.job = null;
  state.selectedSlide = null;
  renderHome();
}

// ─── Tab navigation ──────────────────────────────────────────────
const TABS = ['pipeline', 'review', 'export'];

function switchTab(name) {
  // Single-screen mode: all panels always visible, no hidden toggling.
  // Function kept as no-op so existing call sites don't break.
  if (!TABS.includes(name)) return;
  state.activeTab = name;
}

document.querySelectorAll('[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// ─── Log toggle ──────────────────────────────────────────────────
const logToggleBtn = document.querySelector('#logToggleBtn');
const logSection   = document.querySelector('#logSection');

logToggleBtn?.addEventListener('click', () => {
  const isHidden = logSection.classList.contains('hidden');
  logSection.classList.toggle('hidden', !isHidden);
  logToggleBtn.textContent = isHidden ? '로그 숨기기 ▲' : '로그 보기 ▼';
});

// ─── Style toggle ────────────────────────────────────────────────
document.querySelectorAll('.style-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.style-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const input = document.querySelector('#explanationStyleInput');
    if (input) input.value = btn.dataset.style;
  });
});

// ─── Modal voice handlers ────────────────────────────────────────
(function setupModalVoice() {
  const modalRecordBtn    = document.querySelector('#modalRecordButton');
  const modalStopBtn      = document.querySelector('#modalStopButton');
  const modalVoiceFile    = document.querySelector('#modalVoiceFileInput');
  const modalVoiceStatus  = document.querySelector('#modalVoiceStatus');
  const modalVoicePreview = document.querySelector('#modalVoicePreview');

  if (!modalRecordBtn) return;

  // File upload
  modalVoiceFile?.addEventListener('change', e => {
    const file = e.target.files[0];
    if (!file) return;
    state.pendingVoiceBlob = file;
    if (modalVoicePreview) {
      modalVoicePreview.hidden = false;
      modalVoicePreview.src = URL.createObjectURL(file);
    }
    if (modalVoiceStatus) modalVoiceStatus.textContent = `선택됨: ${file.name}`;
  });

  // Recording
  let mediaRecorder = null;
  let audioChunks = [];

  modalRecordBtn.addEventListener('click', async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      if (modalVoiceStatus) modalVoiceStatus.textContent = '마이크를 지원하지 않는 브라우저입니다.';
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunks = [];
      mediaRecorder = new MediaRecorder(stream);
      mediaRecorder.ondataavailable = e => { if (e.data.size) audioChunks.push(e.data); };
      mediaRecorder.onstop = () => {
        state.pendingVoiceBlob = new Blob(audioChunks, { type: 'audio/webm' });
        if (modalVoicePreview) {
          modalVoicePreview.hidden = false;
          modalVoicePreview.src = URL.createObjectURL(state.pendingVoiceBlob);
        }
        if (modalVoiceStatus) modalVoiceStatus.textContent = '녹음 완료';
        stream.getTracks().forEach(t => t.stop());
        modalRecordBtn.disabled = false;
        if (modalStopBtn) modalStopBtn.disabled = true;
      };
      mediaRecorder.start();
      if (modalVoiceStatus) modalVoiceStatus.textContent = '녹음 중…';
      modalRecordBtn.disabled = true;
      if (modalStopBtn) modalStopBtn.disabled = false;
    } catch (err) {
      if (modalVoiceStatus) modalVoiceStatus.textContent = err.message || '마이크 접근 실패';
    }
  });

  modalStopBtn?.addEventListener('click', () => {
    mediaRecorder?.stop();
  });
})();

// ─── Helpers ─────────────────────────────────────────────────────
function statusLabel(status) {
  return {
    queued:    '대기',
    running:   '진행 중',
    stopping:  '중지 중',
    stopped:   '중지됨',
    completed: '완료',
    failed:    '실패',
    done:      '완료',
    pending:   '대기',
  }[status] ?? status;
}

function prettyTime(value) {
  if (!value) return '';
  return `${new Date(value).toLocaleTimeString()} 업데이트`;
}

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function parseGlossaryInput(value) {
  const glossary = {};
  value.split('\n').map(l => l.trim()).filter(Boolean).forEach(line => {
    const [source, target] = line.includes('=>') ? line.split('=>') : line.split('=');
    if (source?.trim() && target?.trim()) glossary[source.trim()] = target.trim();
  });
  return glossary;
}

function formatGlossary(glossary = {}) {
  return Object.entries(glossary).map(([k, v]) => `${k} => ${v}`).join('\n');
}

function buildDiffHtml(previous = '', current = '') {
  if (!previous && !current) return { before: '<p>이전 버전이 없습니다.</p>', after: '<p>현재 버전이 없습니다.</p>' };
  if (previous === current) return {
    before: `<p>${escapeHtml(previous || '이전 버전 없음')}</p>`,
    after:  `<p>${escapeHtml(current  || '현재 버전 없음')}</p>`,
  };
  const oldS = previous.split(/(?<=[.!?])\s+/).filter(Boolean);
  const newS = current.split(/(?<=[.!?])\s+/).filter(Boolean);
  return {
    before: oldS.map(s => `<p class="diff-removed">${escapeHtml(s)}</p>`).join(''),
    after:  newS.map(s => `<p class="diff-added">${escapeHtml(s)}</p>`).join(''),
  };
}

function showToast(msg) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.classList.add('toast--visible'), 10);
  setTimeout(() => {
    el.classList.remove('toast--visible');
    setTimeout(() => el.remove(), 300);
  }, 3000);
}

// ─── API ──────────────────────────────────────────────────────────
async function api(path, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10000);
  let response;
  try {
    response = await fetch(path, { ...options, signal: controller.signal });
    clearTimeout(timeoutId);
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      console.warn('Request timed out:', path);
      return null;
    }
    throw err;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? response.statusText);
  }
  const ct = response.headers.get('content-type') || '';
  return ct.includes('application/json') ? response.json() : response.text();
}

// ─── Data fetching ────────────────────────────────────────────────
async function fetchJobs() {
  state.jobs = await api('/demo/api/jobs');
  renderHome();
}

async function fetchJob(jobId) {
  state.job = await api(`/demo/api/jobs/${jobId}`);
  const slides = state.job.slides ?? [];
  if (!slides.find(s => s.slide_number === state.selectedSlide)) {
    state.selectedSlide = slides[0]?.slide_number ?? null;
  }
  render();
}

function stopPolling() {
  if (state.pollTimer) { window.clearInterval(state.pollTimer); state.pollTimer = null; }
}

function startPolling(jobId) {
  stopPolling();

  const POLL_ACTIVE_MS = 4000;
  const POLL_IDLE_MS   = 15000;

  const tick = async () => {
    try {
      await fetchJob(jobId);
      await fetchJobs();
      const status = state.job?.status;
      if (['completed', 'failed', 'stopped', 'error'].includes(status)) {
        stopPolling();
        submitButton.disabled = false;
        if (status === 'completed' && state.job?.slides?.length) {
          switchTab('review');
          showToast('파이프라인 완료! 슬라이드 검수로 이동합니다.');
        }
        return;
      }
      const targetMs = jobId ? POLL_ACTIVE_MS : POLL_IDLE_MS;
      if (!state.pollTimer) {
        state.pollTimer = window.setInterval(tick, targetMs);
      }
    } catch (error) {
      if (uploadMessage) uploadMessage.textContent = error.message;
      stopPolling();
      submitButton.disabled = false;
    }
  };
  tick();
  state.pollTimer = window.setInterval(tick, POLL_ACTIVE_MS);
}

// ─── Home view ────────────────────────────────────────────────────
function renderHome() {
  if (!jobCountBadge || !lectureGrid || !emptyState) return;

  jobCountBadge.textContent = state.jobs.length;

  if (!state.jobs.length) {
    lectureGrid.innerHTML = '';
    emptyState.classList.remove('hidden');
    return;
  }

  emptyState.classList.add('hidden');
  lectureGrid.innerHTML = state.jobs.map(job => {
    const name = escapeHtml(job.lecture_name ?? job.filename);
    const file = escapeHtml(job.filename);
    const st   = job.status ?? 'queued';
    const mins = job.target_minutes ?? 8;
    const updatedAt = job.updated_at ? new Date(job.updated_at).toLocaleString() : '';
    return `
      <div class="lecture-card" data-status="${st}" data-job="${job.job_id}">
        <div class="card-status-row">
          <span class="card-status-dot"></span>
          <span class="card-status-label">${statusLabel(st)}</span>
          <div class="card-actions">
            <button class="card-action-btn card-rename-btn" data-job="${job.job_id}" data-name="${name}" title="이름 수정" aria-label="이름 수정">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
            <button class="card-action-btn card-delete-btn" data-job="${job.job_id}" title="삭제" aria-label="삭제">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
          </div>
        </div>
        <span class="card-title">${name}</span>
        <span class="card-filename">${file}</span>
        <div class="card-meta">
          <div class="card-meta-left">
            <span class="card-meta-item">${mins}분 목표</span>
            ${updatedAt ? `<span class="card-meta-item">${updatedAt}</span>` : ''}
          </div>
          <svg class="card-arrow" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M6 3l5 5-5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>
    `;
  }).join('');

  // Card click → navigate to detail
  lectureGrid.querySelectorAll('.lecture-card').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('.card-action-btn')) return; // don't navigate on action btn click
      navigateToDetail(card.dataset.job);
    });
  });

  // Delete buttons
  lectureGrid.querySelectorAll('.card-delete-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm('이 강의를 삭제할까요?')) return;
      await api(`/demo/api/jobs/${btn.dataset.job}`, { method: 'DELETE' });
      await fetchJobs();
      renderHome();
    });
  });

  // Rename buttons
  lectureGrid.querySelectorAll('.card-rename-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const newName = prompt('새 강의 이름:', btn.dataset.name);
      if (!newName || !newName.trim()) return;
      (async () => {
        await api(`/demo/api/jobs/${btn.dataset.job}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ lecture_name: newName.trim() }),
        });
        await fetchJobs();
        renderHome();
      })();
    });
  });
}

// ─── Metrics (detail topbar) ──────────────────────────────────────
function setDetailTopbar() {
  if (!state.job) return;
  if (detailLectureName) detailLectureName.textContent = state.job.lecture_name ?? state.job.filename ?? '';

  const statusPill = document.querySelector('#metricStatus');
  if (statusPill) {
    statusPill.textContent = statusLabel(state.job.status ?? '');
    statusPill.dataset.status = state.job.status ?? '';
  }

  if (lastUpdated) lastUpdated.textContent = prettyTime(state.job.updated_at);
}

// ─── Stage stepper ────────────────────────────────────────────────
function renderStages() {
  if (!state.job?.stages?.length) {
    stageGrid.innerHTML = `<p class="empty-hint-sm" style="padding:20px 0">작업을 선택하면 진행 상태가 표시됩니다.</p>`;
    return;
  }

  stageGrid.innerHTML = state.job.stages.map((stage, i) => {
    const isLast = i === state.job.stages.length - 1;
    const dotContent = stage.status === 'completed'
      ? `<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2.5 7l3.5 3.5 5.5-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
      : stage.status === 'running'
        ? `<div class="step-spinner"></div>`
        : stage.status === 'failed'
          ? `<svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 2l8 8M10 2 2 10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`
          : String(i + 1);

    const progress = stage.status === 'running' && stage.progress != null
      ? `<span class="step-progress">${stage.progress}%</span>`
      : '';

    return `
      <div class="step ${isLast ? 'last' : ''} ${stage.status}">
        <div class="step-dot">${dotContent}</div>
        <span class="step-label">${escapeHtml(stage.label)}</span>
        ${progress}
      </div>
    `;
  }).join('');
}

// ─── Events ───────────────────────────────────────────────────────
function renderEvents() {
  if (!state.job?.events?.length) {
    eventList.innerHTML = `<p class="empty-hint-sm">로그가 아직 없습니다.</p>`;
    return;
  }
  eventList.innerHTML = [...state.job.events].slice(-20).reverse().map(ev => `
    <article class="event-item">
      <span class="event-time">${new Date(ev.time).toLocaleTimeString()} · ${escapeHtml(ev.stage)}</span>
      <div>${escapeHtml(ev.message)}</div>
    </article>
  `).join('');
}

// ─── Job Controls (Settings tab) ──────────────────────────────────
function renderJobControls() {
  if (!jobControls) return;  // panel removed — settings moved to modal
  if (!state.job) {
    jobControls.innerHTML = `<p class="empty-hint-sm">강의를 선택하면 설정 패널이 열립니다.</p>`;
    return;
  }

  const s = state.job?.settings ?? {};
  jobControls.innerHTML = `
    <div class="control-card">
      <div class="control-top">
        <div>
          <p class="control-name">${escapeHtml(state.job.lecture_name)}</p>
          <p class="control-file">${escapeHtml(state.job.filename)}</p>
        </div>
        <span class="status-pill" data-status="${state.job.status}">${statusLabel(state.job.status)}</span>
      </div>

      <div class="compact-grid">
        <label class="inline-field">
          <span>목표 시간 (분)</span>
          <input id="targetMinutesInput" type="number" min="1" value="${Number(state.job.target_minutes || 8)}" />
        </label>
        <label class="inline-field">
          <span>수강 대상</span>
          <select id="audienceInput">
            ${['학부 전공','학부 1학년','비전공자','대학원','실무자']
              .map(o => `<option ${s.audience === o ? 'selected' : ''}>${o}</option>`)
              .join('')}
          </select>
        </label>
      </div>

      <div class="control-actions">
        <button class="btn-primary" id="rerunAllButton" type="button">변경사항 반영</button>
        ${['running', 'queued'].includes(state.job.status)
          ? `<button class="btn-danger" id="stopJobButton" type="button">■ 중지</button>`
          : state.job.status === 'stopping'
          ? `<button class="btn-danger" id="stopJobButton" type="button" disabled>중지 중…</button>`
          : ''}
      </div>

      <details class="ctrl-details">
        <summary>고급 생성 옵션</summary>
        <div class="ctrl-split">
          <label class="inline-field">
            <span>설명 스타일</span>
            <select id="styleInput">
              ${['개념 중심','입문 친화','시험 대비','실무 예시']
                .map(o => `<option ${s.explanation_style === o ? 'selected' : ''}>${o}</option>`)
                .join('')}
            </select>
          </label>
          <label class="inline-field">
            <span>강의 밀도</span>
            <select id="densityInput">
              ${['표준형','요약형','자세형']
                .map(o => `<option ${s.lecture_density === o ? 'selected' : ''}>${o}</option>`)
                .join('')}
            </select>
          </label>
        </div>
        <div class="ctrl-split">
          <label class="field">
            <span>학생 특성</span>
            <textarea id="learnerProfileInput" rows="3">${escapeHtml(s.learner_profile ?? '')}</textarea>
          </label>
          <label class="field">
            <span>전달 메모</span>
            <textarea id="deliveryNotesInput" rows="3">${escapeHtml(s.delivery_notes ?? '')}</textarea>
          </label>
        </div>
        <div class="control-actions">
          <button class="btn-ghost" id="rerunTtsButton" type="button">음성만 다시 생성</button>
          <button class="btn-ghost" id="rerunVideoButton" type="button">영상만 다시 만들기</button>
        </div>
      </details>

      <details class="ctrl-details">
        <summary>음성 및 발음 사전</summary>
        <div class="ctrl-split">
          <div>
            <p class="detail-copy">짧은 문서는 보이스 클론, 장수가 많으면 속도 우선 모드가 적용됩니다.</p>
            <div class="voice-actions">
              <button class="btn-ghost" id="recordButton" type="button">녹음 시작</button>
              <button class="btn-ghost" id="stopButton" type="button" disabled>녹음 종료</button>
              <button class="btn-ghost" id="uploadVoiceButton" type="button" disabled>음성 업로드</button>
            </div>
            <p class="inline-msg" id="voiceStatus">${state.job.voice_reference_name ? `저장된 음성: ${state.job.voice_reference_name}` : '저장된 음성 레퍼런스가 없습니다.'}</p>
            <audio id="voicePreview" controls ${state.voiceBlob || state.job.voice_reference_name ? '' : 'hidden'} style="width:100%;margin-top:8px;"></audio>
          </div>
          <div>
            <p class="detail-copy">형식: 원문 =&gt; 읽기 방식</p>
            <textarea id="glossaryEditor" class="glossary-editor" rows="7" placeholder="SQL => 에스큐엘&#10;DBMS => 디비엠에스">${escapeHtml(formatGlossary(state.job.glossary ?? {}))}</textarea>
            <div class="control-actions" style="margin-top:8px;">
              <button class="btn-ghost" id="saveGlossaryButton" type="button">발음 사전 저장</button>
            </div>
          </div>
        </div>
      </details>
    </div>
  `;

  document.querySelector('#stopJobButton')?.addEventListener('click', async () => {
    if (!confirm('파이프라인을 중지할까요? 현재 단계가 완료된 후 멈춥니다.')) return;
    await api(`/demo/api/jobs/${state.job.job_id}/stop`, { method: 'POST' });
    if (uploadMessage) uploadMessage.textContent = '중지 요청이 전송되었습니다.';
  });

  document.querySelector('#rerunAllButton').addEventListener('click', async () => {
    if (uploadMessage) uploadMessage.textContent = '전체 파이프라인을 다시 생성하고 있습니다.';
    await api(`/demo/api/jobs/${state.job.job_id}/rerun`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_minutes:    Number(document.querySelector('#targetMinutesInput').value || 8),
        audience:          document.querySelector('#audienceInput').value,
        explanation_style: document.querySelector('#styleInput').value,
        lecture_density:   document.querySelector('#densityInput').value,
        learner_profile:   document.querySelector('#learnerProfileInput').value.trim(),
        delivery_notes:    document.querySelector('#deliveryNotesInput').value.trim(),
      }),
    });
    startPolling(state.job.job_id);
  });

  document.querySelector('#rerunTtsButton').addEventListener('click', async () => {
    if (uploadMessage) uploadMessage.textContent = '전체 TTS를 다시 생성하고 있습니다.';
    await api(`/demo/api/jobs/${state.job.job_id}/actions/rerun-tts`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
    });
    await fetchJob(state.job.job_id);
    if (uploadMessage) uploadMessage.textContent = 'TTS 재실행이 완료되었습니다.';
  });

  document.querySelector('#rerunVideoButton').addEventListener('click', async () => {
    if (uploadMessage) uploadMessage.textContent = '영상을 다시 조립하고 있습니다.';
    await api(`/demo/api/jobs/${state.job.job_id}/actions/rerun-video`, { method: 'POST' });
    await fetchJob(state.job.job_id);
    if (uploadMessage) uploadMessage.textContent = '영상 재조립이 완료되었습니다.';
  });

  bindVoiceAndGlossary();
}

function bindVoiceAndGlossary() {
  const recordButton      = document.querySelector('#recordButton');
  const stopButton        = document.querySelector('#stopButton');
  const uploadVoiceButton = document.querySelector('#uploadVoiceButton');
  const voiceStatus       = document.querySelector('#voiceStatus');
  const voicePreview      = document.querySelector('#voicePreview');

  if (!navigator.mediaDevices?.getUserMedia) {
    voiceStatus.textContent = '현재 브라우저는 마이크 녹음을 지원하지 않습니다.';
    recordButton.disabled = true;
  } else {
    if (state.voiceBlob) {
      voicePreview.hidden = false;
      voicePreview.src = URL.createObjectURL(state.voiceBlob);
      uploadVoiceButton.disabled = false;
    } else if (state.job?.voice_reference_name) {
      voicePreview.hidden = false;
      voicePreview.src = `/demo/api/jobs/${state.job.job_id}/voice-reference`;
    }

    recordButton.addEventListener('click', async () => {
      try {
        state.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        state.audioChunks = [];
        state.mediaRecorder = new MediaRecorder(state.mediaStream);
        state.mediaRecorder.ondataavailable = e => { if (e.data.size) state.audioChunks.push(e.data); };
        state.mediaRecorder.onstop = () => {
          state.voiceBlob = new Blob(state.audioChunks, { type: 'audio/webm' });
          voicePreview.hidden = false;
          voicePreview.src = URL.createObjectURL(state.voiceBlob);
          uploadVoiceButton.disabled = false;
          voiceStatus.textContent = '녹음이 완료되었습니다. 업로드하면 현재 작업에 연결됩니다.';
          state.mediaStream?.getTracks().forEach(t => t.stop());
        };
        state.mediaRecorder.start();
        voiceStatus.textContent = '녹음 중입니다.';
        recordButton.disabled = true;
        stopButton.disabled = false;
      } catch (err) {
        voiceStatus.textContent = err.message || '마이크 접근에 실패했습니다.';
      }
    });

    stopButton.addEventListener('click', () => {
      state.mediaRecorder?.stop();
      recordButton.disabled = false;
      stopButton.disabled = true;
    });

    uploadVoiceButton.addEventListener('click', async () => {
      if (!state.voiceBlob) return;
      const formData = new FormData();
      formData.append('audio_file', state.voiceBlob, 'voice_reference.webm');
      uploadVoiceButton.disabled = true;
      voiceStatus.textContent = '음성 레퍼런스를 업로드 중입니다.';
      await fetch(`/demo/api/jobs/${state.job.job_id}/voice-reference`, { method: 'POST', body: formData });
      await fetchJob(state.job.job_id);
      voiceStatus.textContent = '음성 레퍼런스가 저장되었습니다.';
    });
  }

  document.querySelector('#saveGlossaryButton').addEventListener('click', async () => {
    const glossary = parseGlossaryInput(document.querySelector('#glossaryEditor').value);
    if (uploadMessage) uploadMessage.textContent = '발음 사전을 저장하고 있습니다.';
    await api(`/demo/api/jobs/${state.job.job_id}/glossary`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ glossary }),
    });
    await fetchJob(state.job.job_id);
    if (uploadMessage) uploadMessage.textContent = '발음 사전이 저장되었습니다.';
  });
}

// ─── Slide strip ──────────────────────────────────────────────────
function renderSlideStrip() {
  if (!state.job?.slides?.length) {
    slideThumbStrip.innerHTML = '';
    return;
  }
  slideThumbStrip.innerHTML = state.job.slides.map(slide => `
    <button class="thumb-card ${slide.slide_number === state.selectedSlide ? 'active' : ''}" data-slide="${slide.slide_number}">
      <img src="${slide.png_url}" alt="Slide ${slide.slide_number}" loading="lazy" />
      <span class="thumb-num">${slide.slide_number}</span>
    </button>
  `).join('');

  slideThumbStrip.querySelectorAll('.thumb-card').forEach(btn => {
    btn.addEventListener('click', () => {
      state.selectedSlide = Number(btn.dataset.slide);
      renderSlideStrip();
      renderSlideDetail();
    });
  });
}

// ─── Evidence modal ───────────────────────────────────────────────
function buildMetaMarkup() {
  const meta     = state.job?.pipeline_meta ?? {};
  const recovery = state.job?.recovery ?? {};
  return `
    <div class="meta-list">
      <dl>
        <div><dt>LLM 모델</dt><dd>${escapeHtml(meta.llm_model ?? '-')}</dd></div>
        <div><dt>VLM 모델</dt><dd>${escapeHtml(meta.vlm_model ?? '-')}</dd></div>
        <div><dt>TTS 모드</dt><dd>${escapeHtml(meta.tts_mode ?? '-')}</dd></div>
        <div><dt>프롬프트 버전</dt><dd>${escapeHtml(meta.prompt_version ?? '-')}</dd></div>
        <div><dt>재현성 모드</dt><dd>${escapeHtml(meta.seed_mode ?? '-')}</dd></div>
        <div><dt>복구 지점</dt><dd>${escapeHtml(recovery.can_resume_from ?? '-')}</dd></div>
      </dl>
    </div>
  `;
}

function openEvidenceModal(slide) {
  if (!slide || !state.job) return;
  const note     = slide.vlm_note ?? {};
  const script   = slide.script ?? {};
  const evidence = slide.evidence ?? {};
  evidenceModalBody.innerHTML = `
    <div class="modal-section">
      <h4>슬라이드 ${slide.slide_number} 근거</h4>
      <div class="evidence-grid">
        <div class="evidence-box">
          <h5>PDF 추출 텍스트</h5>
          <p>${(evidence.pdf_text ?? []).length ? evidence.pdf_text.map(t => escapeHtml(t)).join('<br />') : '추출 텍스트가 없습니다.'}</p>
        </div>
        <div class="evidence-box">
          <h5>VLM 요약</h5>
          <p>${escapeHtml(evidence.vlm_summary ?? note.visual_summary ?? 'VLM 요약이 없습니다.')}</p>
        </div>
        <div class="evidence-box">
          <h5>최종 스크립트</h5>
          <p>${escapeHtml(evidence.final_script ?? script.script ?? '스크립트가 없습니다.')}</p>
        </div>
      </div>
    </div>
    <div class="modal-section">
      <h4>파이프라인 메타데이터</h4>
      ${buildMetaMarkup()}
    </div>
  `;
  evidenceModal.classList.remove('hidden');
  evidenceModal.setAttribute('aria-hidden', 'false');
}

// ─── Slide detail ─────────────────────────────────────────────────
function renderSlideDetail() {
  const slide = state.job?.slides?.find(s => s.slide_number === state.selectedSlide);
  if (!slide) {
    slideDetail.className = 'empty-state-center';
    slideDetail.innerHTML = `
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" aria-hidden="true" style="opacity:.3;margin-bottom:12px;">
        <rect x="2" y="3" width="20" height="14" rx="2" stroke="currentColor" stroke-width="1.5"/>
        <path d="M8 21h8M12 17v4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
      <p>왼쪽에서 슬라이드를 선택하세요</p>
    `;
    return;
  }

  const note     = slide.vlm_note ?? {};
  const script   = slide.script ?? {};
  const history  = (state.job.version_history ?? []).filter(e => e.slide_number === slide.slide_number);
  const lastEdit = [...history].reverse().find(e => e.kind === 'script_edit');
  const prevScript = lastEdit?.payload?.previous_script ?? '';
  const diffHtml   = buildDiffHtml(prevScript, script.script ?? '');

  slideDetail.className = 'slide-detail';
  slideDetail.innerHTML = `
    <div class="slide-image-row">
      <div class="slide-preview">
        <img src="${slide.png_url}" alt="Slide ${slide.slide_number}" />
      </div>
    </div>

    <article class="detail-card">
      <div class="card-header-row">
        <h3>슬라이드 ${slide.slide_number} 스크립트</h3>
        <button class="btn-icon" id="openEvidenceButton" type="button">근거 보기</button>
      </div>
      <textarea id="scriptEditor" class="script-editor">${escapeHtml(script.script ?? '')}</textarea>
      <div class="slide-actions">
        <button class="btn-primary" id="saveScriptButton" type="button">저장 및 반영</button>
        <button class="btn-ghost" id="slideTtsButton" type="button">이 슬라이드 음성 재생성</button>
        ${script.target_seconds ? `<span class="slide-target">목표 ${script.target_seconds}초</span>` : ''}
      </div>
    </article>

    <article class="detail-card">
      <h3>슬라이드 음성</h3>
      ${slide.audio_url
        ? `<audio controls preload="metadata" src="${slide.audio_url}" style="width:100%;margin-top:8px;"></audio>
           <p style="margin-top:8px;font-size:.82rem;color:var(--muted);">${escapeHtml(slide.tts_preview ?? '현재 슬라이드 음성 결과입니다.')}</p>`
        : `<p style="color:var(--faint);font-size:.84rem;">음성 생성 전입니다.</p>`
      }
    </article>

    <div class="slide-bottom-grid">
      <article class="detail-card">
        <h3>핵심 포인트</h3>
        <ul>${(note.teaching_points ?? []).map(p => `<li>${escapeHtml(p)}</li>`).join('') || '<li style="color:var(--faint)">VLM 포인트가 아직 없습니다.</li>'}</ul>
      </article>
      <details class="detail-card detail-disclosure">
        <summary>변경 diff 보기</summary>
        <div class="diff-grid">
          <div class="diff-box"><h4>이전 버전</h4>${diffHtml.before}</div>
          <div class="diff-box"><h4>현재 버전</h4>${diffHtml.after}</div>
        </div>
      </details>
      <details class="detail-card detail-disclosure">
        <summary>수정 이력 보기</summary>
        ${history.length
          ? history.slice(-6).reverse().map(e => `<p style="font-size:.82rem;color:var(--muted);">${new Date(e.time).toLocaleString()} · ${escapeHtml(e.summary ?? e.kind)}</p>`).join('')
          : '<p style="font-size:.82rem;color:var(--faint);">아직 수정 이력이 없습니다.</p>'
        }
      </details>
    </div>
  `;

  document.querySelector('#openEvidenceButton').addEventListener('click', () => openEvidenceModal(slide));

  document.querySelector('#saveScriptButton').addEventListener('click', async () => {
    const newScript = document.querySelector('#scriptEditor').value.trim();
    if (!newScript) { if (uploadMessage) uploadMessage.textContent = '스크립트를 비울 수는 없습니다.'; return; }
    if (uploadMessage) uploadMessage.textContent = `슬라이드 ${slide.slide_number} 스크립트를 저장하고 미디어를 재생성하고 있습니다.`;
    await api(`/demo/api/jobs/${state.job.job_id}/slides/${slide.slide_number}/script`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ script: newScript }),
    });
    await fetchJob(state.job.job_id);
    if (uploadMessage) uploadMessage.textContent = `슬라이드 ${slide.slide_number} 반영이 완료되었습니다.`;
  });

  document.querySelector('#slideTtsButton').addEventListener('click', async () => {
    if (uploadMessage) uploadMessage.textContent = `슬라이드 ${slide.slide_number} 음성을 다시 생성하고 있습니다.`;
    await api(`/demo/api/jobs/${state.job.job_id}/actions/rerun-tts`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slide_number: slide.slide_number }),
    });
    await fetchJob(state.job.job_id);
    if (uploadMessage) uploadMessage.textContent = `슬라이드 ${slide.slide_number} 음성 갱신이 완료되었습니다.`;
  });
}

// ─── Outputs ──────────────────────────────────────────────────────
function renderOutputs() {
  if (!state.job?.artifacts?.video_url) {
    outputsArea.innerHTML = `
      <div class="empty-state-center" style="min-height:200px;">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" aria-hidden="true" style="opacity:.3;margin-bottom:12px;">
          <path d="M12 16V3m0 13-4-4m4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M3 18v1a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        <p>작업이 완료되면 여기에 산출물이 표시됩니다.</p>
      </div>
    `;
    return;
  }

  outputsArea.innerHTML = `
    <article class="video-card">
      <h3>최종 강의 영상</h3>
      <video controls preload="metadata" src="${state.job.artifacts.video_url}"></video>
    </article>
    <article class="downloads-card">
      <h3>다운로드</h3>
      <div class="downloads-row">
        <a class="btn-ghost" href="${state.job.artifacts.video_url}" target="_blank" rel="noreferrer">MP4 열기</a>
        <a class="btn-ghost" href="${state.job.artifacts.merged_audio_url ?? '#'}" target="_blank" rel="noreferrer">병합 오디오</a>
        <a class="btn-ghost" href="${state.job.artifacts.package_url ?? '#'}">ZIP 다운로드</a>
      </div>
    </article>
  `;
}

// ─── Render (detail view) ─────────────────────────────────────────
function render() {
  setDetailTopbar();
  renderStages();
  renderEvents();
  renderJobControls();
  renderSlideStrip();
  renderSlideDetail();
  renderOutputs();
}

// ─── Create modal ─────────────────────────────────────────────────
function openCreateModal() {
  modalCreate.classList.remove('hidden');
  modalCreate.setAttribute('aria-hidden', 'false');
  if (createMessage) createMessage.textContent = '';
}

function closeCreateModal() {
  modalCreate.classList.add('hidden');
  modalCreate.setAttribute('aria-hidden', 'true');
  uploadForm?.reset();
  state.pendingVoiceBlob = null;
  const modalVoicePreview = document.querySelector('#modalVoicePreview');
  if (modalVoicePreview) { modalVoicePreview.hidden = true; modalVoicePreview.src = ''; }
  const modalVoiceStatus = document.querySelector('#modalVoiceStatus');
  if (modalVoiceStatus) modalVoiceStatus.textContent = '';
  document.querySelectorAll('.style-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
  const styleInput = document.querySelector('#explanationStyleInput');
  if (styleInput) styleInput.value = '개념 중심';
}

document.querySelector('#btnNewLecture')?.addEventListener('click', openCreateModal);
document.querySelector('#btnNewLectureEmpty')?.addEventListener('click', openCreateModal);
document.querySelector('#btnCloseCreate')?.addEventListener('click', closeCreateModal);

modalCreate?.addEventListener('click', event => {
  if (event.target === modalCreate) closeCreateModal();
});

// ─── Form submit ──────────────────────────────────────────────────
uploadForm.addEventListener('submit', async event => {
  event.preventDefault();
  submitButton.disabled = true;
  if (createMessage) createMessage.textContent = '강의 생성 파이프라인을 시작하고 있습니다.';
  try {
    const formData = new FormData(uploadForm);
    formData.set('use_vlm', formData.get('use_vlm') ? 'true' : 'false');
    const job = await api('/demo/api/jobs', { method: 'POST', body: formData });
    if (state.pendingVoiceBlob) {
      try {
        const vfd = new FormData();
        vfd.append('audio_file', state.pendingVoiceBlob, 'voice_reference.webm');
        await fetch(`/demo/api/jobs/${job.job_id}/voice-reference`, { method: 'POST', body: vfd });
      } finally {
        state.pendingVoiceBlob = null;
      }
    }
    closeCreateModal();
    state.job = job;
    state.selectedSlide = null;
    await fetchJobs();
    navigateToDetail(job.job_id);
  } catch (error) {
    if (createMessage) createMessage.textContent = error.message;
    submitButton.disabled = false;
  }
});

// ─── Back button ──────────────────────────────────────────────────
document.querySelector('#btnBack')?.addEventListener('click', navigateHome);

// ─── Evidence modal close ─────────────────────────────────────────
closeEvidenceModal?.addEventListener('click', () => {
  evidenceModal.classList.add('hidden');
  evidenceModal.setAttribute('aria-hidden', 'true');
});

evidenceModal?.addEventListener('click', event => {
  if (event.target === evidenceModal) {
    evidenceModal.classList.add('hidden');
    evidenceModal.setAttribute('aria-hidden', 'true');
  }
});

// ─── Dropzone ─────────────────────────────────────────────────────
(function setupDropzone() {
  const dropzone    = document.querySelector('#dropzone');
  const pdfInput    = document.querySelector('#pdfInput');
  const hintEl      = document.querySelector('#dropzoneHint');
  const originalHint = hintEl?.textContent ?? '';

  function applyFile(file) {
    if (!file) return;
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      if (hintEl) hintEl.textContent = 'PDF 파일만 업로드 가능합니다';
      dropzone?.classList.remove('has-file');
      return;
    }
    if (hintEl) hintEl.textContent = `${file.name}  (${(file.size / 1024).toFixed(0)} KB)`;
    dropzone?.classList.add('has-file');
  }

  pdfInput?.addEventListener('change', () => {
    applyFile(pdfInput.files[0] ?? null);
    if (!pdfInput.files[0] && hintEl) hintEl.textContent = originalHint;
  });

  dropzone?.addEventListener('dragover', e => {
    e.preventDefault();
    dropzone.classList.add('drag-over');
  });

  dropzone?.addEventListener('dragleave', e => {
    if (!dropzone.contains(e.relatedTarget)) dropzone.classList.remove('drag-over');
  });

  dropzone?.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (!file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    pdfInput.files = dt.files;
    applyFile(file);
  });
})();

// ─── Hash routing ─────────────────────────────────────────────────
window.addEventListener('hashchange', () => {
  const jobId = window.location.hash.replace('#', '').trim();
  if (jobId) {
    if (state.currentView !== 'detail') showView('detail');
    if (!state.pollTimer) startPolling(jobId);
  } else {
    navigateHome();
  }
});

// ─── Boot ─────────────────────────────────────────────────────────
async function boot() {
  await fetchJobs();
  const jobId = window.location.hash.replace('#', '').trim();
  if (jobId) {
    showView('detail');
    switchTab('pipeline');
    startPolling(jobId);
  } else {
    showView('home');
  }
}

boot();
