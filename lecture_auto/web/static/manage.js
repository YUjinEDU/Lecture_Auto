"use strict";

(() => {
  const id = new URLSearchParams(location.search).get("lecture") || "";
  const base = location.pathname.replace(/static\/manage\.html$/, "");
  const lec = `${base}api/lectures/${encodeURIComponent(id)}`;
  const $ = (x) => document.getElementById(x);
  let study = { glossary: [], quiz: [] };

  async function call(url, opts = {}) {
    const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
    if (res.status === 401) { location.href = base; throw new Error("로그인이 필요합니다"); }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "요청이 실패했습니다");
    return body;
  }
  const fail = (e) => { $("m-error").textContent = e.message; $("m-error").hidden = false; };
  const el = (tag, props = {}, ...kids) => {
    const n = Object.assign(document.createElement(tag), props);
    kids.forEach((k) => n.append(k));
    return n;
  };

  async function loadShares() {
    const list = $("share-list");
    list.replaceChildren();
    for (const s of await call(`${lec}/shares`)) {
      const url = new URL(`${base}${s.path}`, location.origin).href;
      const input = el("input", { value: url, readOnly: true, onclick: (e) => e.target.select() });
      const li = el("li", { className: s.revoked ? "m-revoked" : "" }, input);
      if (!s.revoked) {
        li.append(
          el("button", { textContent: "복사", onclick: async () => { await navigator.clipboard.writeText(url).catch(() => input.select()); } }),
          el("button", { textContent: "열기", onclick: () => window.open(url, "_blank") }),
          el("button", { textContent: "회수", onclick: async () => {
            if (!confirm("이 링크로는 더 이상 볼 수 없게 됩니다. 회수할까요?")) return;
            await call(`${lec}/shares/${encodeURIComponent(s.token)}`, { method: "DELETE" }).catch(fail);
            loadShares();
          } }),
        );
      } else {
        li.append(el("span", { className: "m-muted", textContent: "회수됨" }));
      }
      list.append(li);
    }
  }

  function field(obj, key, multiline = false) {
    const input = el(multiline ? "textarea" : "input", { value: obj[key] ?? "", rows: 2 });
    if (!multiline) input.type = "text";
    input.addEventListener("input", () => { obj[key] = input.value; });
    return input;
  }
  function head(obj, list, i, render) {
    const box = el("input", { type: "checkbox", checked: !!obj.approved });
    const slide = el("input", { type: "number", min: 1, value: obj.slide ?? "" });
    slide.addEventListener("input", () => { obj.slide = slide.value ? Number(slide.value) : null; });
    const wrap = el("div", { className: "m-head" },
      el("label", {}, box, " 공개"), el("label", {}, "슬라이드 ", slide),
      el("button", { className: "m-small", textContent: "삭제", onclick: () => { list.splice(i, 1); render(); } }));
    box.addEventListener("change", () => { obj.approved = box.checked; render(); });
    return wrap;
  }

  function renderStudy() {
    const g = $("glossary"), q = $("quiz");
    g.replaceChildren();
    q.replaceChildren();
    study.glossary.forEach((item, i) => g.append(el("div", { className: `m-item${item.approved ? " m-on" : ""}` },
      head(item, study.glossary, i, renderStudy), field(item, "term"), field(item, "definition", true))));
    study.quiz.forEach((item, i) => {
      const choices = el("div", { className: "m-choices" });
      item.choices.forEach((c, ci) => {
        const radio = el("input", { type: "radio", name: `q${i}`, checked: item.answer === ci, title: "정답" });
        radio.addEventListener("change", () => { item.answer = ci; });
        const text = el("input", { type: "text", value: c });
        text.addEventListener("input", () => { item.choices[ci] = text.value; });
        choices.append(el("label", {}, radio, text));
      });
      q.append(el("div", { className: `m-item${item.approved ? " m-on" : ""}` },
        head(item, study.quiz, i, renderStudy), field(item, "question", true), choices,
        el("label", { className: "m-muted" }, "해설"), field(item, "explanation", true)));
    });
    if (!study.glossary.length) g.append(el("p", { className: "m-muted", textContent: "아직 용어가 없습니다." }));
    if (!study.quiz.length) q.append(el("p", { className: "m-muted", textContent: "아직 퀴즈가 없습니다." }));
  }

  async function loadStudy() {
    const data = await call(`${lec}/study`);
    study = { glossary: data.glossary, quiz: data.quiz };
    renderStudy();
  }

  async function waitJob(job) {
    for (;;) {
      const j = await call(`${base}api/jobs/${encodeURIComponent(job.id)}`);
      $("study-job").textContent = j.status === "running" ? "초안 만드는 중…" : j.status === "queued" ? "대기 중…" : "";
      if (!["queued", "running"].includes(j.status)) return j;
      await new Promise((r) => setTimeout(r, 2000));
    }
  }

  $("share-new").addEventListener("click", async () => {
    await call(`${lec}/shares`, { method: "POST" }).catch(fail);
    loadShares().catch(fail);
  });
  $("g-add").addEventListener("click", () => { study.glossary.push({ term: "", definition: "", slide: null, approved: false }); renderStudy(); });
  $("q-add").addEventListener("click", () => {
    study.quiz.push({ question: "", choices: ["", "", "", ""], answer: 0, explanation: "", slide: null, approved: false });
    renderStudy();
  });
  $("study-save").addEventListener("click", async () => {
    try {
      await call(`${lec}/study`, { method: "PUT", body: JSON.stringify(study) });
      $("study-msg").textContent = "저장했습니다.";
      await loadStudy();
    } catch (e) {
      $("study-msg").textContent = `저장하지 못했습니다: ${e.message} (퀴즈는 보기 4개가 모두 있어야 합니다)`;
    }
  });
  $("study-draft").addEventListener("click", async () => {
    if (!confirm("저장하지 않은 수정은 사라집니다. 공개한 항목은 남고 나머지는 새 초안으로 바뀝니다. 진행할까요?")) return;
    $("study-draft").disabled = true;
    try {
      const job = await waitJob(await call(`${lec}/jobs`, { method: "POST", body: JSON.stringify({ kind: "study" }) }));
      $("study-msg").textContent = job.status === "succeeded" ? "초안을 만들었습니다." : "초안을 만들지 못했습니다. 작업 기록의 로그를 확인하세요.";
      await loadStudy();
    } catch (e) { fail(e); } finally { $("study-draft").disabled = false; }
  });

  call(lec).then((l) => {
    $("m-title").textContent = `${l.name} — 공유·복습 자료`;
    document.title = `${l.name} - 공유·복습 자료`;
    return Promise.all([loadShares(), loadStudy()]);
  }).catch(fail);
})();
