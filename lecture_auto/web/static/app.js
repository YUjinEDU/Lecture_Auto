"use strict";

const app = document.getElementById("app");
const nav = document.getElementById("nav");
const toastEl = document.getElementById("toast");
const state = { dirty: {}, pollTimer: null, logOffset: 0, logJob: null, filter: "all", selected: new Set() };

const VIDEO = {
  final: ["최종 영상 있음", "b-ok"],
  draft: ["DRAFT (확인 필요)", "b-warn"],
  none: ["영상 없음", "b-none"],
};
const SLIDE_STATE = {
  approved: ["승인됨", "b-ok"],
  pass: ["검사 통과", "b-ok"],
  held: ["확인 필요", "b-bad"],
  no_audio: ["음성 없음", "b-none"],
};
const JOB_STATE = {
  queued: ["대기 중", "b-info"],
  running: ["실행 중", "b-info"],
  succeeded: ["완료", "b-ok"],
  failed: ["실패", "b-bad"],
  cancelled: ["취소됨", "b-none"],
  interrupted: ["중단됨", "b-warn"],
};

// produce.py exits non-zero both when it crashed and when it only left slides held
// back, so the exit code alone cannot say which happened -- runner records what the
// lecture looks like on disk afterwards and that decides the wording.
function jobState(job) {
  const base = JOB_STATE[job.status] || [job.status, "b-none"];
  const o = job.kind === "produce" ? job.outcome : null;
  if (job.status === "failed" && o && !o.error && o.held_back > 0 && o.no_audio === 0) {
    return [`확인 필요 ${o.held_back}장`, "b-warn"];
  }
  if (job.status === "succeeded" && o && !o.error && o.held_back > 0) {
    return [`완료 (확인 필요 ${o.held_back}장)`, "b-warn"];
  }
  return base;
}
const ACTIONS = [
  ["scripts", "1. 대본 생성", "슬라이드를 읽고 강의 대본을 만듭니다 (GPU 사용 안 함, 수 분)."],
  ["produce", "2. 음성·영상 제작", "모든 슬라이드 음성을 만들고 영상을 조립합니다 (GPU, 강의 길이의 약 5배 시간)."],
  ["heal", "보류 슬라이드 자동 복구", "검사에 실패한 슬라이드만 다시 만들어 통과하면 채택합니다 (GPU)."],
  ["assemble", "영상 다시 조립", "현재 음성으로 영상을 다시 만듭니다 (승인·채택 후 사용, 수 분)."],
  ["check", "발음 점검", "사전에 없는 영어 단어를 찾아 작업 로그에 보여줍니다."],
];

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const badge = ([text, cls]) => h("span", { class: `badge ${cls}` }, text);
const enc = encodeURIComponent;
const fmtTime = (t) => (t ? new Date(t * 1000).toLocaleString("ko-KR", { hour12: false }) : "-");
const fmtSize = (b) => (b > 1e9 ? `${(b / 1e9).toFixed(1)}GB` : b > 1e6 ? `${(b / 1e6).toFixed(0)}MB` : `${Math.ceil(b / 1e3)}KB`);

function toast(msg, error = false) {
  toastEl.textContent = msg;
  toastEl.className = error ? "error" : "";
  toastEl.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { toastEl.hidden = true; }, error ? 7000 : 3500);
}

class Unauthorized extends Error {}

async function api(path, opts = {}) {
  const init = { credentials: "same-origin", ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  }
  const res = await fetch(`api/${path}`, init);
  if (res.status === 401 && path !== "login") throw new Unauthorized();
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw new Error((data && data.detail && (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))) || `오류 ${res.status}`);
  return data;
}

function stopPolling() {
  clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

async function guard(fn) {
  try {
    await fn();
  } catch (e) {
    if (e instanceof Unauthorized) return renderLogin();
    toast(e.message, true);
  }
}

function renderLogin() {
  stopPolling();
  nav.hidden = true;
  const input = h("input", { type: "password", id: "pw", autocomplete: "current-password", required: true });
  const form = h("form", { class: "card login stack", onsubmit: (ev) => {
    ev.preventDefault();
    guard(async () => {
      try {
        await api("login", { json: { password: input.value } });
      } catch (e) {
        input.select();
        throw e;
      }
      route();
    });
  } },
    h("h1", {}, "로그인"),
    h("p", { class: "muted" }, "강의 제작 스튜디오에 들어가려면 비밀번호를 입력하세요."),
    h("div", { class: "field" }, h("label", { for: "pw" }, "비밀번호"), input),
    h("button", { class: "primary", type: "submit" }, "들어가기"));
  app.replaceChildren(form);
  input.focus();
}

function lectureCard(lec) {
  const held = lec.held_back.length;
  return h("a", { class: "card lecture-card", href: `#/lecture/${enc(lec.id)}` },
    h("div", { class: "row spread" }, badge(VIDEO[lec.video_state]),
      lec.job ? badge([`${lec.job.label} ${jobState(lec.job)[0]}`, "b-info"]) : null),
    h("div", { class: "title" }, lec.name),
    h("div", { class: "muted small" }, `${lec.subject} · ${lec.id}`),
    h("div", { class: "chips" },
      h("span", { class: "chip" }, "슬라이드 ", h("b", {}, lec.slides)),
      h("span", { class: "chip" }, "대본 ", h("b", {}, lec.scripts)),
      h("span", { class: "chip" }, "음성 ", h("b", {}, lec.audio)),
      h("span", { class: "chip" }, "확인 필요 ", h("b", {}, held)),
      h("span", { class: "chip" }, "후보 ", h("b", {}, lec.candidates)),
      h("span", { class: "chip" }, "승인 ", h("b", {}, lec.approved))));
}

function uploadDialog() {
  const dlg = h("dialog", {});
  const form = h("form", { method: "dialog", onsubmit: (ev) => {
    ev.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    btn.textContent = "올리는 중…";
    guard(async () => {
      try {
        const lec = await api("lectures", { method: "POST", body: new FormData(form) });
        dlg.close();
        toast("강의를 등록했습니다. 이제 '대본 생성'을 눌러 주세요.");
        location.hash = `#/lecture/${enc(lec.id)}`;
      } finally {
        btn.disabled = false;
        btn.textContent = "등록";
      }
    });
  } },
    h("h2", {}, "새 강의 등록"),
    h("div", { class: "field" }, h("label", { for: "f-file" }, "슬라이드 파일 ", h("span", { class: "hint" }, "(PPTX 또는 PDF)")),
      h("input", { id: "f-file", name: "file", type: "file", accept: ".pptx,.pdf", required: true })),
    h("div", { class: "field" }, h("label", { for: "f-name" }, "강의 제목"),
      h("input", { id: "f-name", name: "name", required: true, maxlength: 100, placeholder: "예: 08_요구사항 분석" })),
    h("div", { class: "field" }, h("label", { for: "f-subject" }, "과목"),
      h("input", { id: "f-subject", name: "subject", maxlength: 100, value: "종합설계" })),
    h("div", { class: "row" },
      h("div", { class: "field", style: "flex:1" }, h("label", { for: "f-target" }, "목표 길이(분)"),
        h("input", { id: "f-target", name: "target_minutes", type: "number", min: 5, max: 120, step: 1, value: 30, required: true })),
      h("div", { class: "field", style: "flex:1" }, h("label", { for: "f-min" }, "최소 길이(분) ", h("span", { class: "hint" }, "선택")),
        h("input", { id: "f-min", name: "min_minutes", type: "number", min: 1, max: 120, step: 1 }))),
    h("div", { class: "row spread" },
      h("button", { type: "button", onclick: () => dlg.close() }, "취소"),
      h("button", { type: "submit", class: "primary" }, "등록")));
  dlg.append(form);
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

async function renderDashboard() {
  stopPolling();
  const lectures = await api("lectures");
  const grid = h("div", { class: "grid" }, lectures.slice().reverse().map(lectureCard));
  app.replaceChildren(
    h("div", { class: "row spread", style: "margin-bottom:1rem" },
      h("div", {}, h("h1", {}, "강의 목록"),
        h("p", { class: "muted" }, "강의를 눌러 대본·음성을 검토하고 제작을 진행하세요.")),
      h("button", { class: "primary", onclick: uploadDialog }, "+ 새 강의 등록")),
    lectures.length ? grid : h("div", { class: "card empty" }, "등록된 강의가 없습니다."));
  if (lectures.some((l) => l.job)) state.pollTimer = setTimeout(() => guard(renderDashboard), 10000);
}

function qcBlock(qc, title) {
  if (!qc) return null;
  const items = [];
  if (qc.cer !== null && qc.cer !== undefined) items.push(`받아쓰기 오차율 ${(qc.cer * 100).toFixed(1)}%`);
  if (qc.gate_reasons?.length) items.push(`검사 사유: ${qc.gate_reasons.join(", ")}`);
  return h("div", { class: "qc" },
    h("div", {}, h("b", {}, title), " ", qc.ok ? badge(["통과", "b-ok"]) : badge(["실패", "b-bad"]), " ", items.join(" · ")),
    qc.failing_segments?.length
      ? h("ul", {}, qc.failing_segments.map((s) => h("li", {}, `문장 ${s.index + 1}: ${s.text}`)))
      : null);
}

function slideRow(lec, s, busy) {
  const base = `lectures/${enc(lec.id)}/slides/${s.number}`;
  const textarea = h("textarea", { "aria-label": `슬라이드 ${s.number} 대본`, disabled: busy || s.script === null }, state.dirty[s.number] ?? s.script ?? "");
  const saveBtn = h("button", { disabled: true, onclick: () => guard(async () => {
    await api(`${base}/script`, { method: "PUT", json: { script: textarea.value } });
    delete state.dirty[s.number];
    toast(`슬라이드 ${s.number} 대본을 저장했습니다. 음성은 '선택 슬라이드 다시 만들기'로 새로 만드세요.`);
    renderLecture(lec.id);
  }) }, "대본 저장");
  textarea.addEventListener("input", () => {
    state.dirty[s.number] = textarea.value;
    saveBtn.disabled = textarea.value === s.script;
  });
  if (state.dirty[s.number] !== undefined) saveBtn.disabled = false;
  const check = h("input", { type: "checkbox", checked: state.selected.has(s.number), onchange: (ev) => {
    if (ev.target.checked) state.selected.add(s.number); else state.selected.delete(s.number);
    document.getElementById("regen-count").textContent = state.selected.size;
  } });
  const players = [];
  if (s.audio) players.push(h("div", { class: "player" }, h("span", {}, "현재 음성"),
    h("audio", { controls: true, preload: "none", src: `api/${base}/audio/main` })));
  if (s.previous) players.push(h("div", { class: "player" }, h("span", {}, "이전 음성 (후보 채택 전)"),
    h("audio", { controls: true, preload: "none", src: `api/${base}/audio/prev` })));
  if (s.candidate) players.push(h("div", { class: "player" }, h("span", {}, "새로 만든 후보 음성"),
    h("audio", { controls: true, preload: "none", src: `api/${base}/audio/cand` })));
  const buttons = [];
  if (s.candidate) {
    buttons.push(h("button", { class: "primary", disabled: busy, onclick: () => guard(async () => {
      const allow = !s.candidate_ok;
      if (allow && !confirm("이 후보는 자동 검사를 통과하지 못했습니다. 직접 들어보셨고 그래도 채택하시겠습니까?")) return;
      await api(`${base}/promote`, { json: { allow_failed: allow } });
      toast(`슬라이드 ${s.number}: 후보를 채택하고 승인했습니다.`);
      renderLecture(lec.id);
    }) }, s.candidate_ok ? "후보 채택" : "후보 강제 채택"));
  }
  if (s.audio && s.state !== "approved") {
    buttons.push(h("button", { disabled: busy, onclick: () => guard(async () => {
      if (s.state === "held" && !confirm("이 음성은 자동 검사를 통과하지 못했습니다. 직접 들어보고 괜찮으면 승인하세요. 승인할까요?")) return;
      await api(`${base}/approve`, { method: "POST" });
      toast(`슬라이드 ${s.number}: 현재 음성을 승인했습니다.`);
      renderLecture(lec.id);
    }) }, "현재 음성 승인"));
  }
  if (s.state === "approved") {
    buttons.push(h("button", { disabled: busy, onclick: () => guard(async () => {
      if (!confirm("이 슬라이드의 승인을 취소할까요? 음성 파일은 그대로 남습니다.")) return;
      await api(`${base}/unapprove`, { method: "POST" });
      toast(`슬라이드 ${s.number}: 승인을 취소했습니다.`);
      renderLecture(lec.id);
    }) }, "승인 취소"));
  }
  if (s.previous) {
    buttons.push(h("button", { disabled: busy, onclick: () => guard(async () => {
      if (!confirm("현재 음성과 이전 음성을 맞바꿉니다. 승인은 취소되며, 한 번 더 누르면 원래대로 돌아옵니다. 진행할까요?")) return;
      await api(`${base}/restore-prev`, { method: "POST" });
      toast(`슬라이드 ${s.number}: 이전 음성으로 되돌렸습니다.`);
      renderLecture(lec.id);
    }) }, "이전 음성으로 되돌리기"));
  }
  return h("article", { class: "card slide", id: `slide-${s.number}` },
    s.image ? h("img", { src: `api/${base}/image`, alt: `슬라이드 ${s.number}`, loading: "lazy" }) : h("div", { class: "empty" }, "이미지 없음"),
    h("div", { class: "stack" },
      h("div", { class: "slide-head" }, h("span", { class: "num" }, `슬라이드 ${s.number}`), badge(SLIDE_STATE[s.state]),
        s.candidate ? badge(["후보 있음", "b-info"]) : null, s.hand_edited ? badge(["대본 직접 수정됨", "b-warn"]) : null,
        h("label", { class: "select-box" }, check, "다시 만들기 선택")),
      textarea,
      h("div", { class: "row spread" }, h("span", { class: "muted small" }, `${(state.dirty[s.number] ?? s.script ?? "").length}자`), saveBtn),
      players, qcBlock(s.qc, "현재 음성 검사"), qcBlock(s.candidate_qc, "후보 검사"),
      buttons.length ? h("div", { class: "actions" }, buttons) : null));
}

function jobPanel(lec) {
  const job = lec.job;
  if (!job) return null;
  const pre = h("pre", { class: "log", id: "job-log" });
  if (state.logJob !== job.id) { state.logJob = job.id; state.logOffset = 0; }
  return h("section", { class: "card" },
    h("div", { class: "row spread" },
      h("div", {}, h("h2", { style: "margin:0" }, `${job.label} `, badge(jobState(job))),
        h("p", { class: "muted small" }, `시작 ${fmtTime(job.started_at || job.created_at)}${job.slides ? ` · 슬라이드 ${job.slides.join(", ")}` : ""}`)),
      h("button", { class: "danger", onclick: () => guard(async () => {
        if (!confirm("작업을 중단할까요? 이미 만들어진 음성은 그대로 남습니다.")) return;
        await api(`jobs/${job.id}/cancel`, { method: "POST" });
        toast("중단을 요청했습니다.");
      }) }, "작업 중단")),
    pre);
}

async function pollLog(lectureId) {
  const pre = document.getElementById("job-log");
  if (!pre || !state.logJob) return;
  const jobId = state.logJob;
  const { text, offset } = await api(`jobs/${jobId}/log?offset=${state.logOffset}`);
  state.logOffset = offset;
  if (text) {
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
    pre.textContent = (pre.textContent + text).slice(-60000);
    if (atBottom) pre.scrollTop = pre.scrollHeight;
  }
  const job = await api(`jobs/${jobId}`);
  if (job.status === "queued" || job.status === "running") {
    state.pollTimer = setTimeout(() => guard(() => pollLog(lectureId)), 2000);
  } else {
    const [text, cls] = jobState(job);
    toast(`${job.label}: ${text}`, cls === "b-bad");
    state.logJob = null;
    renderLecture(lectureId);
  }
}

function lectureActions(lec, busy) {
  const run = (kind, slides) => guard(async () => {
    const label = ACTIONS.find((a) => a[0] === kind)?.[1] ?? "선택 슬라이드 다시 만들기";
    if (!confirm(`'${label}' 작업을 시작할까요?`)) return;
    await api(`lectures/${enc(lec.id)}/jobs`, { json: { kind, slides } });
    toast("작업을 시작했습니다. 아래에서 진행 상황을 볼 수 있습니다.");
    renderLecture(lec.id);
  });
  return h("section", { class: "card" },
    h("h2", {}, "제작 작업"),
    h("div", { class: "actions" },
      ACTIONS.map(([kind, label, help]) => h("button", { title: help, disabled: busy, class: kind === "produce" ? "primary" : null, onclick: () => run(kind) }, label)),
      h("button", { disabled: busy, onclick: () => {
        if (!state.selected.size) return toast("아래 슬라이드에서 '다시 만들기 선택'을 먼저 체크하세요.", true);
        run("regen", [...state.selected]);
      } }, "선택 슬라이드 다시 만들기 (", h("span", { id: "regen-count" }, state.selected.size), ")")),
    h("ol", { class: "steps" },
      h("li", {}, "대본 생성"), h("li", {}, "대본 검토·수정"), h("li", {}, "음성·영상 제작"),
      h("li", {}, "'확인 필요' 슬라이드 듣고 승인/채택/다시 만들기"), h("li", {}, "영상 다시 조립 후 다운로드")),
    h("p", { class: "muted small" }, "GPU 작업은 한 번에 하나만 실행되고, 나머지는 순서대로 기다립니다. 작업 중에는 이 강의의 대본 수정·승인이 잠깁니다."));
}

function filesSection(lec) {
  if (!lec.files.length) return null;
  return h("section", { class: "card files" }, h("h2", {}, "결과물 내려받기"),
    lec.files.map((f) => h("a", { class: "btn", href: `api/lectures/${enc(lec.id)}/files/${enc(f.name)}`, download: f.name },
      `${f.name} (${fmtSize(f.bytes)})`)));
}

async function renderLecture(id) {
  stopPolling();
  const lec = await api(`lectures/${enc(id)}`);
  if (state.lectureId !== id) { state.lectureId = id; state.dirty = {}; state.selected = new Set(); state.filter = "all"; }
  const busy = Boolean(lec.job);
  const counts = {
    all: lec.slide_list.length,
    todo: lec.slide_list.filter((s) => s.state === "held" || s.candidate).length,
    approved: lec.slide_list.filter((s) => s.state === "approved").length,
  };
  const list = h("div", { class: "stack", id: "slides" });
  const paint = () => {
    const show = lec.slide_list.filter((s) => state.filter === "all"
      || (state.filter === "todo" && (s.state === "held" || s.candidate))
      || (state.filter === "approved" && s.state === "approved"));
    list.replaceChildren(...(show.length ? show.map((s) => slideRow(lec, s, busy)) : [h("div", { class: "card empty" }, "해당하는 슬라이드가 없습니다.")]));
  };
  const tab = (key, label) => h("button", { role: "tab", "aria-selected": String(state.filter === key), onclick: (ev) => {
    state.filter = key;
    ev.target.parentElement.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b === ev.target)));
    paint();
  } }, `${label} (${counts[key]})`);
  const minutes = lec.script_chars ? `대본 ${lec.script_chars.toLocaleString()}자 · 예상 약 ${Math.round(lec.script_chars / 7.0 / 60)}분` : "대본 없음";
  app.replaceChildren(h("div", { class: "stack" },
    h("div", {},
      h("a", { href: "#/", class: "small" }, "← 강의 목록"),
      h("h1", {}, lec.name),
      h("div", { class: "row" }, badge(VIDEO[lec.video_state]), h("span", { class: "muted small" },
        `${lec.subject} · 슬라이드 ${lec.slides}장 · ${minutes}${lec.target_minutes ? ` · 목표 ${lec.target_minutes}분` : ""}`)),
      lec.held_back.length ? h("p", { class: "small", style: "color:var(--bad)" },
        `확인이 필요한 슬라이드: ${lec.held_back.join(", ")} — 듣고 승인하거나, 대본을 고친 뒤 다시 만드세요.`) : null,
      lec.no_audio.length ? h("p", { class: "small muted" },
        `아직 음성이 없는 슬라이드: ${lec.no_audio.join(", ")} — "2. 음성·영상 제작"을 실행하면 만들어집니다.`) : null),
    jobPanel(lec), lectureActions(lec, busy), filesSection(lec),
    h("section", {}, h("div", { class: "tabs", role: "tablist" }, tab("all", "전체"), tab("todo", "확인 필요"), tab("approved", "승인됨")), list),
    lec.web && !busy ? h("p", { class: "small" }, h("button", { class: "link danger", onclick: () => guard(async () => {
      if (!confirm("이 강의를 목록에서 지울까요? (만들어진 파일은 서버에 남습니다)")) return;
      await api(`lectures/${enc(lec.id)}`, { method: "DELETE" });
      location.hash = "#/";
    }) }, "이 강의를 목록에서 삭제")) : null));
  paint();
  if (busy) {
    state.logJob = lec.job.id;
    await pollLog(id);
  }
}

async function renderJobs() {
  stopPolling();
  const jobs = await api("jobs");
  const pre = h("pre", { class: "log", hidden: true });
  const show = (job) => guard(async () => {
    const { text } = await api(`jobs/${job.id}/log?offset=0`);
    pre.hidden = false;
    pre.textContent = text.slice(-60000) || "(로그 없음)";
    pre.scrollIntoView({ behavior: "smooth" });
  });
  app.replaceChildren(h("div", { class: "stack" },
    h("h1", {}, "작업 기록"),
    h("div", { class: "card", style: "overflow-x:auto" }, jobs.length ? h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "작업"), h("th", {}, "강의"), h("th", {}, "상태"), h("th", {}, "시작"), h("th", {}, ""))),
      h("tbody", {}, jobs.map((j) => h("tr", {},
        h("td", {}, j.label, j.slides ? ` (${j.slides.join(",")})` : ""),
        h("td", {}, h("a", { href: `#/lecture/${enc(j.lecture_id)}` }, j.lecture_id)),
        h("td", {}, badge(jobState(j))),
        h("td", {}, fmtTime(j.started_at || j.created_at)),
        h("td", {}, h("button", { onclick: () => show(j) }, "로그")))))) : h("div", { class: "empty" }, "아직 작업이 없습니다.")),
    pre));
}

function route() {
  const hash = decodeURIComponent(location.hash.slice(1) || "/");
  guard(async () => {
    await api("me");
    nav.hidden = false;
    if (hash.startsWith("/lecture/")) return renderLecture(hash.slice("/lecture/".length));
    if (hash === "/jobs") return renderJobs();
    return renderDashboard();
  });
}

document.getElementById("logout").addEventListener("click", () => guard(async () => {
  await api("logout", { method: "POST" });
  renderLogin();
}));
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (ev) => {
  if (Object.keys(state.dirty).length) ev.preventDefault();
});
route();
