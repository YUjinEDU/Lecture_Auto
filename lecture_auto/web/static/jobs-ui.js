const fmtDuration = (s) => (s >= 60 ? `${Math.floor(s / 60)}분 ${Math.round(s % 60)}초` : `${Math.round(s)}초`);

function progressView(job) {
  const started = job.started_at;
  if (job.status !== "running" || !started) return [h("p", { class: "muted small" }, "차례를 기다리는 중입니다.")];
  const parts = [`경과 ${fmtDuration(Date.now() / 1000 - started)}`];
  const p = job.progress;
  if (!p) return [h("p", { class: "muted small" }, parts[0])];
  parts.unshift(p.done >= p.total ? "음성 완료 · 영상 조립·마무리 중" : `음성 ${p.done}/${p.total}장`);
  if (p.eta_seconds != null && p.done < p.total) parts.splice(1, 0, `약 ${fmtDuration(p.eta_seconds)} 남음`);
  return [
    h("div", { class: "progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": p.total, "aria-valuenow": p.done },
      h("span", { style: `width:${Math.round((100 * p.done) / p.total)}%` })),
    h("p", { class: "muted small" }, parts.join(" · ")),
  ];
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
    h("div", { id: "job-progress" }, progressView(job)),
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
  document.getElementById("job-progress")?.replaceChildren(...progressView(job));
  if (job.status === "queued" || job.status === "running") {
    state.pollTimer = setTimeout(() => guard(() => pollLog(lectureId)), 2000);
  } else {
    const [text, cls] = jobState(job);
    toast(`${job.label}: ${text}`, cls === "b-bad");
    state.logJob = null;
    renderLecture(lectureId);
  }
}

async function renderJobs() {
  stopPolling();
  const jobs = await api("jobs");
  const pre = h("pre", { class: "log", hidden: true });
  const show = (job) => guard(async () => {
    const { text } = await api(`jobs/${job.id}/log?offset=-200000`);
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
