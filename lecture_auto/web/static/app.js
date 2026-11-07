"use strict";

const app = document.getElementById("app");
const nav = document.getElementById("nav");
const toastEl = document.getElementById("toast");
const state = { dirty: {}, pollTimer: null, logOffset: 0, logJob: null, filter: "all", selected: new Set(), query: "", dashQuery: "", lec: null, paint: () => {} };

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
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const badge = ([text, cls]) => h("span", { class: `badge ${cls}` }, text);
const enc = encodeURIComponent;
const fmtTime = (t) => (t ? new Date(t * 1000).toLocaleString("ko-KR", { hour12: false }) : "-");
const fmtSize = (b) => (b >= 2 ** 30 ? `${(b / 2 ** 30).toFixed(1)}GB` : b >= 2 ** 20 ? `${(b / 2 ** 20).toFixed(0)}MB` : `${Math.ceil(b / 1024)}KB`);

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

const STEPS = ["대본 생성", "대본 검토", "음성 제작", "확인·승인", "영상 완성"];
const fmtDur = (sec) => {
  const t = Math.round(sec), m = Math.floor(t / 60), s = t % 60;
  return m ? `${m}분 ${s}초` : `${s}초`;
};

// Index of the step the lecture is on (5 = finished).
function progressOf(lec) {
  if (!lec.scripts) return 0;
  if (lec.audio < lec.scripts) return lec.audio ? 2 : 1;
  if (lec.held_back.length || lec.video_state !== "final") return 3;
  return 5;
}

function stepper(lec) {
  const at = progressOf(lec);
  return h("ol", { class: "stepper", "aria-label": "제작 단계" }, STEPS.map((label, i) =>
    h("li", { class: i < at ? "done" : i === at ? "current" : null, "aria-current": i === at ? "step" : null }, label)));
}

function bestVideo(lec) {
  const mp4s = lec.files.filter((f) => f.name.endsWith(".mp4"));
  return mp4s.find((f) => f.name === `${lec.id}.mp4`) || mp4s.find((f) => !f.name.includes("_DRAFT")) || mp4s[0] || null;
}

function lectureCard(lec) {
  const step = progressOf(lec);
  const held = lec.held_back.length;
  const noThumb = () => h("div", { class: "thumb empty-thumb" }, "미리보기 없음");
  const thumb = lec.slides
    ? h("img", { class: "thumb", src: `api/lectures/${enc(lec.id)}/slides/1/image`, alt: "", loading: "lazy",
      onerror: (ev) => ev.target.replaceWith(noThumb()) })
    : noThumb();
  return h("a", { class: "card lecture-card", href: `#/lecture/${enc(lec.id)}` }, thumb,
    h("div", { class: "lecture-body" },
      h("div", { class: "row spread" }, badge(VIDEO[lec.video_state]),
        lec.job ? badge([`${lec.job.label} ${jobState(lec.job)[0]}`, "b-info"]) : null),
      h("div", { class: "title" }, lec.name),
      h("div", { class: "muted small" }, `${lec.subject} · 슬라이드 ${lec.slides}장${lec.script_chars ? ` · 약 ${Math.round(lec.script_chars / 7 / 60)}분` : ""}`),
      h("div", { class: "progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 5, "aria-valuenow": step },
        h("span", { style: `width:${step * 20}%` })),
      h("div", { class: "small" }, step >= 5 ? h("span", { class: "ok-text" }, "완성") : h("span", { class: "muted" }, `다음: ${STEPS[step]}`),
        held ? h("span", { class: "warn-text" }, ` · 확인 필요 ${held}장`) : null)));
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
  const lectures = (await api("lectures")).slice().reverse();
  const search = h("input", { type: "search", placeholder: "강의 제목·과목으로 찾기", "aria-label": "강의 찾기", value: state.dashQuery || "" });
  const grid = h("div", { class: "grid" });
  const paint = () => {
    state.dashQuery = search.value;
    const term = search.value.trim().toLowerCase();
    const show = lectures.filter((l) => !term || `${l.name} ${l.subject} ${l.id}`.toLowerCase().includes(term));
    grid.replaceChildren(...(show.length ? show.map(lectureCard) : [h("div", { class: "card empty" },
      lectures.length ? "찾는 강의가 없습니다." : "아직 강의가 없습니다. '+ 새 강의 등록'으로 슬라이드(PPTX·PDF)를 올려 주세요.")]));
  };
  search.addEventListener("input", paint);
  const finished = lectures.filter((l) => l.video_state === "final").length;
  const working = lectures.filter((l) => l.job).length;
  app.replaceChildren(
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "내 강의"),
        h("p", { class: "muted" }, `강의 ${lectures.length}개 · 완성 ${finished}개${working ? ` · 작업 중 ${working}개` : ""}`)),
      h("button", { class: "primary", onclick: () => guard(uploadDialog) }, "+ 새 강의 등록")),
    lectures.length > 3 ? h("div", { class: "toolbar" }, search) : null,
    grid);
  paint();
  const refresh = () => {
    if (document.activeElement === search) state.pollTimer = setTimeout(refresh, 10000);
    else guard(renderDashboard);
  };
  if (working) state.pollTimer = setTimeout(refresh, 10000);
}

function runJob(lec, kind, slides) {
  return guard(async () => {
    const label = ACTIONS.find((a) => a[0] === kind)?.[1] ?? "선택 슬라이드 다시 만들기";
    if (!confirm(`'${label}' 작업을 시작할까요?`)) return;
    await api(`lectures/${enc(lec.id)}/jobs`, { json: { kind, slides } });
    toast("작업을 시작했습니다. 진행 상황이 위에 표시됩니다.");
    window.scrollTo({ top: 0, behavior: "smooth" });
    renderLecture(lec.id);
  });
}

function nextAction(lec, busy) {
  if (busy) return null;
  if (lec.tts_engine !== "gemini" && state.me?.raon_enabled === false && (lec.audio < lec.scripts || lec.held_back.length)) {
    return [h("button", { class: "primary", onclick: () => guard(() => lectureSettingsDialog(lec)) }, "음성 설정 바꾸기"),
      "이 강의는 GPU 음성(Raon)으로 설정돼 있는데, 이 서버에는 GPU가 없습니다. 음성 설정에서 Gemini 음성을 고르면 제작할 수 있습니다."];
  }
  if (!lec.scripts) return [h("button", { class: "primary", onclick: () => runJob(lec, "scripts") }, "대본 생성 시작"),
    "슬라이드를 읽고 강의 대본을 만듭니다. 몇 분 걸립니다."];
  if (lec.audio < lec.scripts) return [h("button", { class: "primary", onclick: () => runJob(lec, "produce") }, "음성·영상 제작"),
    "대본을 검토·수정한 뒤 눌러 주세요. 모든 슬라이드 음성을 만들고 영상을 조립합니다."];
  if (lec.held_back.length) return [h("button", { class: "primary", onclick: () => {
    state.filter = "todo";
    state.paint?.();
    document.getElementById("workspace")?.scrollIntoView({ behavior: "smooth" });
  } }, `확인 필요 ${lec.held_back.length}장 보기`), "자동 검사에 걸린 슬라이드를 듣고 승인하거나, 대본을 고쳐 다시 만드세요."];
  if (lec.video_state !== "final") return [h("button", { class: "primary", onclick: () => runJob(lec, "assemble") }, "영상 다시 조립"),
    "승인·채택한 음성으로 최종 영상을 만듭니다."];
  return null;
}

function hero(lec, busy) {
  const video = bestVideo(lec);
  const next = nextAction(lec, busy);
  const engine = lec.tts_engine === "gemini" ? `Gemini 음성 · ${lec.tts_voice || "Charon"}` : "내 목소리 복제 (Raon)";
  const minutes = lec.script_chars ? `대본 ${lec.script_chars.toLocaleString()}자 · 약 ${Math.round(lec.script_chars / 7.0 / 60)}분` : "대본 없음";
  return h("section", { class: "card hero" },
    h("a", { href: "#/", class: "small back" }, "← 내 강의"),
    h("div", { class: "hero-main" },
      h("div", { class: "hero-title" },
        h("h1", {}, lec.name),
        h("p", { class: "muted" }, `${lec.subject} · 슬라이드 ${lec.slides}장 · ${minutes}${lec.target_minutes ? ` · 목표 ${lec.target_minutes}분` : ""}`),
        h("div", { class: "row" }, badge(VIDEO[lec.video_state]), badge([engine, "b-none"]))),
      h("div", { class: "hero-actions" },
        video ? h("a", { class: "btn primary", href: `api/lectures/${enc(lec.id)}/files/${enc(video.name)}`, download: video.name },
          video.name.includes("_DRAFT") ? "검토용 영상 받기" : "영상 받기") : null,
        next && !video ? next[0] : null,
        h("button", { disabled: busy, onclick: () => guard(() => lectureSettingsDialog(lec)) }, "음성 설정"),
        h("a", { class: "btn", href: `static/manage.html?lecture=${enc(lec.id)}` }, "학생 공유·복습 자료"))),
    stepper(lec),
    next ? h("div", { class: "next-step" }, h("b", {}, "다음 할 일 "), next[1], video ? h("span", {}, " ", next[0]) : null) : null,
    lec.no_audio.length && lec.audio ? h("p", { class: "small muted" },
      `아직 음성이 없는 슬라이드: ${lec.no_audio.join(", ")} — '음성·영상 제작'을 실행하면 만들어집니다.`) : null);
}

function lectureActions(lec, busy) {
  const item = ([kind, label, help]) => h("div", { class: "action-item" },
    h("button", { disabled: busy, class: kind === "produce" ? "primary" : null, onclick: () => runJob(lec, kind) }, label),
    h("span", { class: "muted small" }, help));
  const main = ACTIONS.filter((a) => a[0] === "scripts" || a[0] === "produce");
  const extra = ACTIONS.filter((a) => a[0] !== "scripts" && a[0] !== "produce");
  return h("section", { class: "card" },
    h("h2", {}, "제작 작업"),
    h("div", { class: "action-list" }, main.map(item),
      h("div", { class: "action-item" },
        h("button", { disabled: busy, onclick: () => {
          if (!state.selected.size) return toast("아래 슬라이드에서 '다시 만들기 선택'을 먼저 체크하세요.", true);
          runJob(lec, "regen", [...state.selected]);
        } }, "선택 슬라이드 다시 만들기 (", h("span", { id: "regen-count" }, state.selected.size), ")"),
        h("span", { class: "muted small" }, "체크한 슬라이드만 새 음성을 만듭니다. 새 음성은 '후보'로 저장되어 들어보고 채택할 수 있습니다."))),
    h("details", { class: "more" }, h("summary", {}, "다른 작업 (자동 복구 · 영상 다시 조립 · 발음 점검)"),
      h("div", { class: "action-list" }, extra.map(item))),
    h("p", { class: "muted small" }, "작업은 한 번에 하나씩 순서대로 실행됩니다. 작업 중에는 이 강의의 대본 수정·승인이 잠깁니다."));
}

function downloadsSection(lec) {
  const base = `api/lectures/${enc(lec.id)}`;
  const link = (href, label, extra, primary = false) => h("a", { class: primary ? "btn primary" : "btn", href, download: "" },
    label, extra ? h("span", { class: "size" }, extra) : null);
  const file = (f, label, primary) => link(`${base}/files/${enc(f.name)}`, label, fmtSize(f.bytes), primary);
  const best = bestVideo(lec);
  const mp4s = lec.files.filter((f) => f.name.endsWith(".mp4"));
  const timeline = lec.files.some((f) => f.name.endsWith(".timeline.json"));
  const reports = lec.files.filter((f) => f.name.endsWith(".report.md"));
  const others = lec.files.filter((f) => !f.name.endsWith(".mp4") && !f.name.endsWith(".report.md"));
  const label = (f) => (f.name === `${lec.id}.mp4` ? "최종 영상 (MP4)" : f.name.includes("_DRAFT") ? "검토용 영상 (DRAFT)" : f.name);
  const none = (text) => h("p", { class: "muted small" }, text);
  const group = (title, ...items) => h("div", { class: "dl-group" }, h("h3", {}, title), h("div", { class: "dl-items" }, ...items));
  return h("section", { class: "card downloads" },
    h("h2", {}, "내려받기"),
    h("div", { class: "dl-grid" },
      group("영상", mp4s.length ? mp4s.map((f) => file(f, label(f), f === best))
        : none("아직 영상이 없습니다. 음성을 만든 뒤 '영상 다시 조립'을 실행하면 생깁니다.")),
      group("자막", timeline ? [link(`${base}/export/subtitles.srt`, "자막 SRT"), link(`${base}/export/subtitles.vtt`, "자막 VTT")]
        : none("영상을 만들면 받을 수 있습니다.")),
      group("대본", lec.scripts ? link(`${base}/export/scripts.txt`, "전체 대본 (TXT)", `${lec.scripts}장`) : none("대본을 만들면 받을 수 있습니다.")),
      group("음성", lec.audio ? link(`${base}/export/audio.zip`, "슬라이드별 음성 (ZIP)", `${lec.audio}개`) : none("음성을 만들면 받을 수 있습니다."))),
    mp4s.some((f) => f.name.includes("_DRAFT")) ? h("p", { class: "muted small" },
      "검토용 영상도 그대로 쓸 수 있습니다. '확인 필요' 슬라이드를 모두 승인하고 다시 조립하면 최종 영상이 됩니다.") : null,
    reports.length || others.length ? h("details", { class: "more" }, h("summary", {}, "검수 보고서·기타 파일"),
      h("div", { class: "dl-items" }, reports.map((f) => file(f, "검수 보고서", false)), others.map((f) => file(f, f.name, false)))) : null);
}

function updateDirtyUI() {
  const n = Object.keys(state.dirty).length;
  const count = document.getElementById("dirty-count");
  if (count) count.textContent = n ? `저장 안 한 슬라이드 ${n}개` : "모든 변경이 저장됨";
  const save = document.getElementById("save-all");
  if (save) save.disabled = !n || Boolean(state.lec?.job);
  const discard = document.getElementById("discard-all");
  if (discard) discard.disabled = !n;
}

async function saveAllScripts(lec) {
  const scripts = { ...state.dirty };
  const n = Object.keys(scripts).length;
  if (!n) return;
  if (Object.values(scripts).some((t) => !t.trim())) throw new Error("빈 대본은 저장할 수 없습니다. 내용을 입력해 주세요.");
  await api(`lectures/${enc(lec.id)}/scripts`, { method: "PUT", json: { scripts } });
  state.dirty = {};
  toast(`슬라이드 ${n}개의 대본을 저장했습니다. 음성은 해당 슬라이드를 '다시 만들기'로 새로 만드세요.`);
  await renderLecture(lec.id);
}

function slideWorkspace(lec, busy, list, tabs) {
  const search = h("input", { type: "search", placeholder: "대본에서 찾기", value: state.query, "aria-label": "대본에서 찾기" });
  search.addEventListener("input", () => { state.query = search.value; state.paint(); });
  const jump = h("select", { "aria-label": "슬라이드로 이동" }, h("option", { value: "" }, "슬라이드로 이동…"),
    lec.slide_list.map((s) => h("option", { value: s.number }, `${s.number}번 · ${SLIDE_STATE[s.state][0]}`)));
  jump.addEventListener("change", () => {
    const n = jump.value;
    jump.value = "";
    if (!n) return;
    if (!document.getElementById(`slide-${n}`)) {
      state.filter = "all"; state.query = ""; search.value = "";
      state.paint();
    }
    document.getElementById(`slide-${n}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  const findI = h("input", { placeholder: "찾을 말", "aria-label": "찾을 말" });
  const repI = h("input", { placeholder: "바꿀 말", "aria-label": "바꿀 말" });
  const replaceAll = h("button", { disabled: busy, onclick: () => {
    const find = findI.value;
    if (!find) return toast("찾을 말을 입력하세요.", true);
    let slides = 0, hits = 0;
    for (const s of lec.slide_list) {
      if (s.script === null) continue;
      const text = state.dirty[s.number] ?? s.script;
      const count = text.split(find).length - 1;
      if (!count) continue;
      const next = text.split(find).join(repI.value);
      slides += 1; hits += count;
      if (next === s.script) delete state.dirty[s.number]; else state.dirty[s.number] = next;
    }
    state.paint();
    updateDirtyUI();
    toast(hits ? `슬라이드 ${slides}개에서 ${hits}곳을 바꿨습니다. '변경 모두 저장'을 눌러야 반영됩니다.` : "찾는 말이 없습니다.", !hits);
  } }, "모두 바꾸기");
  return h("section", { class: "workspace", id: "workspace" },
    h("div", { class: "workspace-bar" },
      h("div", { class: "row spread" },
        h("h2", { style: "margin:0" }, "슬라이드별 대본·음성"),
        h("div", { class: "row" }, h("span", { id: "dirty-count", class: "muted small" }),
          h("button", { id: "discard-all", disabled: true, onclick: () => {
            if (!confirm("저장하지 않은 수정을 모두 버릴까요?")) return;
            state.dirty = {};
            state.paint();
            updateDirtyUI();
          } }, "변경 버리기"),
          h("button", { id: "save-all", class: "primary", disabled: true, title: "Ctrl+S",
            onclick: () => guard(() => saveAllScripts(lec)) }, "변경 모두 저장"))),
      tabs,
      h("div", { class: "row tools" }, search, jump,
        h("details", { class: "replace" }, h("summary", {}, "찾아 바꾸기"), h("div", { class: "row" }, findI, repI, replaceAll)))),
    h("p", { class: "muted small" }, "Ctrl+S(맥은 ⌘+S)로 고친 대본을 한꺼번에 저장합니다. 고친 뒤 '저장하고 음성 다시 만들기'를 누르면 그 슬라이드만 새로 만듭니다."),
    list);
}

async function renderLecture(id) {
  stopPolling();
  const lec = await api(`lectures/${enc(id)}`);
  const same = state.lectureId === id;
  const scrollY = same ? window.scrollY : 0;
  if (!same) {
    state.lectureId = id; state.dirty = {}; state.selected = new Set(); state.filter = "all"; state.query = "";
  }
  state.lec = lec;
  const busy = Boolean(lec.job);
  const isTodo = (s) => s.state === "held" || s.candidate;
  const counts = {
    all: lec.slide_list.length,
    todo: lec.slide_list.filter(isTodo).length,
    edited: lec.slide_list.filter((s) => s.hand_edited).length,
    approved: lec.slide_list.filter((s) => s.state === "approved").length,
  };
  const list = h("div", { class: "stack", id: "slides" });
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const paintTabs = () => tabs.replaceChildren(...[["all", "전체"], ["todo", "확인 필요"], ["edited", "직접 수정함"], ["approved", "승인됨"]]
    .map(([key, label]) => h("button", { role: "tab", "aria-selected": String(state.filter === key), onclick: () => {
      state.filter = key;
      state.paint();
    } }, `${label} (${counts[key]})`)));
  state.paint = () => {
    paintTabs();
    const term = (state.query || "").trim();
    const show = lec.slide_list.filter((s) => (state.filter === "all"
      || (state.filter === "todo" && isTodo(s))
      || (state.filter === "edited" && s.hand_edited)
      || (state.filter === "approved" && s.state === "approved"))
      && (!term || (state.dirty[s.number] ?? s.script ?? "").includes(term)));
    list.replaceChildren(...(show.length ? show.map((s) => slideRow(lec, s, busy)) : [h("div", { class: "card empty" }, "해당하는 슬라이드가 없습니다.")]));
    updateDirtyUI();
  };
  app.replaceChildren(h("div", { class: "stack" },
    hero(lec, busy), jobPanel(lec), downloadsSection(lec), lectureActions(lec, busy),
    lec.slide_list.length ? slideWorkspace(lec, busy, list, tabs) : h("section", { class: "card empty" },
      "아직 슬라이드가 없습니다. '대본 생성 시작'을 누르면 슬라이드를 읽어 옵니다."),
    h("div", { class: "row spread small" },
      h("button", { class: "link", onclick: () => reportDialog("lecture", lec.id) }, "문제 신고"),
      lec.web && !busy ? h("button", { class: "link danger", onclick: () => guard(async () => {
        if (!confirm("이 강의를 목록에서 지울까요? (만들어진 파일은 서버에 남습니다)")) return;
        await api(`lectures/${enc(lec.id)}`, { method: "DELETE" });
        location.hash = "#/";
      }) }, "이 강의를 목록에서 삭제") : null)));
  state.paint();
  if (same) window.scrollTo(0, scrollY);
  if (busy) {
    state.logJob = lec.job.id;
    await pollLog(id);
  }
}

document.addEventListener("keydown", (ev) => {
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s" && location.hash.startsWith("#/lecture/") && state.lec) {
    ev.preventDefault();
    if (Object.keys(state.dirty).length) guard(() => saveAllScripts(state.lec));
  }
});
