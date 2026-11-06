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

async function uploadDialog() {
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
  form.insertBefore(await ttsFields(), form.lastElementChild);
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
      h("button", { class: "primary", onclick: () => guard(uploadDialog) }, "+ 새 강의 등록")),
    lectures.length ? grid : h("div", { class: "card empty" }, "등록된 강의가 없습니다."));
  if (lectures.some((l) => l.job)) state.pollTimer = setTimeout(() => guard(renderDashboard), 10000);
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
    h("div", { class: "actions" }, h("button", { disabled: busy, onclick: () => guard(() => lectureSettingsDialog(lec)) }, "음성 설정"), h("a", { class: "btn", href: `static/manage.html?lecture=${enc(lec.id)}` }, "학생 공유·복습 자료"), h("button", { onclick: () => reportDialog("lecture", lec.id) }, "신고")),
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
