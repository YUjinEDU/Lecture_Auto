"use strict";

(() => {
  const token = decodeURIComponent(location.pathname.replace(/\/+$/, "").split("/").pop());
  const root = location.pathname.replace(/\/w\/[^/]+\/?$/, "/");
  const api = (p) => `${root}api/public/${encodeURIComponent(token)}${p}`;
  const $ = (id) => document.getElementById(id);
  const video = $("video"), mark = $("mark"), caption = $("caption");
  let sentences = [], cues = [], chapters = [], current = { s: -1, c: -1, ch: -1 };

  const fmt = (t) => {
    t = Math.max(0, Math.floor(t));
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(s).padStart(2, "0")}`;
  };
  const el = (tag, { dataset, ...props } = {}, ...kids) => {
    const n = Object.assign(document.createElement(tag), props);
    if (dataset) Object.assign(n.dataset, dataset);
    kids.forEach((k) => n.append(k));
    return n;
  };
  const seek = (t) => { video.currentTime = t + 0.01; video.play().catch(() => {}); };
  const indexAt = (list, t) => {
    let lo = 0, hi = list.length - 1, found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (list[mid].start <= t) { found = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return found >= 0 && t <= list[found].end + 0.25 ? found : -1;
  };

  function contentRect() {
    const w = video.clientWidth, h = video.clientHeight;
    const a = video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : w / h;
    if (w / h > a) { const cw = h * a; return { x: (w - cw) / 2, y: 0, w: cw, h }; }
    const ch = w / a; return { x: 0, y: (h - ch) / 2, w, h: ch };
  }

  function placeMark(box) {
    if (!box || !$("opt-mark").checked) { mark.hidden = true; return; }
    const r = contentRect(), pad = 6;
    Object.assign(mark.style, {
      left: `${r.x + box[0] * r.w - pad}px`, top: `${r.y + box[1] * r.h - pad}px`,
      width: `${(box[2] - box[0]) * r.w + 2 * pad}px`, height: `${(box[3] - box[1]) * r.h + 2 * pad}px`,
    });
    mark.hidden = false;
  }

  function setCurrent(kind, idx, container) {
    if (current[kind] === idx) return false;
    const old = container.querySelector(".w-current");
    if (old) old.classList.remove("w-current");
    current[kind] = idx;
    const node = idx >= 0 ? container.querySelector(`[data-i="${idx}"]`) : null;
    if (node) {
      node.classList.add("w-current");
      if (!container.hidden) node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    return true;
  }

  function tick() {
    const t = video.currentTime;
    const si = indexAt(sentences, t);
    setCurrent("s", si, $("transcript"));
    placeMark(si >= 0 ? sentences[si].box : null);
    const ci = indexAt(cues, t);
    if (setCurrent("c", ci, document.createElement("div")) || !$("opt-subs").checked) {
      caption.textContent = $("opt-subs").checked && ci >= 0 ? cues[ci].text : "";
    }
    let ch = -1;
    for (let i = 0; i < chapters.length; i++) if (chapters[i].start <= t) ch = i;
    setCurrent("ch", ch, $("chapters"));
  }

  function render(data) {
    const v = data.viewer;
    document.title = `${data.title} - 강의 보기`;
    $("title").textContent = data.title;
    $("subject").textContent = data.subject || "";
    video.src = api("/video");
    v.slides.forEach((s) => {
      chapters.push({ start: s.start, end: s.start + s.duration });
      s.sentences.forEach((x) => sentences.push({ ...x, slide: s.number }));
      s.cues.forEach((x) => cues.push(x));
    });
    sentences.sort((a, b) => a.start - b.start);
    cues.sort((a, b) => a.start - b.start);

    const chapterList = $("chapters");
    v.slides.forEach((s, i) => chapterList.append(el("li", {},
      el("button", { type: "button", onclick: () => seek(s.start), dataset: { i } },
        el("span", { className: "w-time", textContent: fmt(s.start) }),
        `${s.number}. ${s.title || `슬라이드 ${s.number}`}`))));

    const transcript = $("transcript");
    let lastSlide = null;
    sentences.forEach((x, i) => {
      if (x.slide !== lastSlide) {
        const slide = v.slides.find((s) => s.number === x.slide);
        transcript.append(el("h3", { textContent: `${x.slide}. ${(slide && slide.title) || ""}` }));
        lastSlide = x.slide;
      }
      transcript.append(el("button", { type: "button", onclick: () => seek(x.start), dataset: { i } },
        el("span", { className: "w-time", textContent: fmt(x.start) }), x.text));
    });

    const startOf = (n) => (v.slides.find((s) => s.number === n) || {}).start;
    if (data.study.glossary.length) {
      $("tab-glossary").hidden = false;
      data.study.glossary.forEach((g) => {
        const dt = el("dt", { textContent: g.term });
        if (g.slide && startOf(g.slide) !== undefined) {
          dt.append(" ", el("button", { className: "w-time", type: "button", textContent: `▶ ${g.slide}번 슬라이드`,
            onclick: () => seek(startOf(g.slide)) }));
        }
        $("glossary").append(dt, el("dd", { textContent: g.definition }));
      });
    }
    if (data.study.quiz.length) {
      $("tab-quiz").hidden = false;
      data.study.quiz.forEach((q, qi) => {
        const box = el("div", { className: "w-q" }, el("p", { textContent: `${qi + 1}. ${q.question}` }));
        const why = el("p", { className: "w-why", hidden: true,
          textContent: `${q.explanation || ""}${q.slide ? ` (${q.slide}번 슬라이드)` : ""}` });
        const buttons = q.choices.map((c, ci) => el("button", { type: "button", textContent: c, onclick: () => {
          buttons.forEach((b, bi) => { b.disabled = true; if (bi === q.answer) b.classList.add("w-right"); });
          if (ci !== q.answer) buttons[ci].classList.add("w-wrong");
          why.hidden = false;
        } }));
        buttons.forEach((b) => box.append(b));
        box.append(why);
        $("quiz").append(box);
      });
    }
    $("app").hidden = false;
  }

  document.querySelectorAll(".w-tabs button").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll(".w-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
    document.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== btn.dataset.tab; });
    const cur = document.querySelector(`[data-panel="${btn.dataset.tab}"] .w-current`);
    if (cur) cur.scrollIntoView({ block: "nearest" });
  }));
  $("opt-rate").addEventListener("change", (e) => { video.playbackRate = Number(e.target.value); });
  $("opt-mark").addEventListener("change", tick);
  $("opt-subs").addEventListener("change", () => { current.c = -2; tick(); });
  video.addEventListener("timeupdate", tick);
  video.addEventListener("seeked", tick);
  window.addEventListener("resize", tick);
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
    if (e.key === " ") { e.preventDefault(); video.paused ? video.play() : video.pause(); }
    if (e.key === "ArrowRight") video.currentTime += 5;
    if (e.key === "ArrowLeft") video.currentTime -= 5;
  });

  $("report-open").addEventListener("click", () => { $("report-msg").textContent = ""; $("report").showModal(); });
  $("report-send").addEventListener("click", async (e) => {
    e.preventDefault();
    const res = await fetch(api("/report"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: $("report-kind").value, text: $("report-text").value, at_seconds: video.currentTime }),
    }).catch(() => null);
    $("report-msg").textContent = res && res.ok ? "신고가 접수되었습니다. 감사합니다." : "보내지 못했습니다. 잠시 뒤 다시 시도해 주세요.";
    if (res && res.ok) setTimeout(() => $("report").close(), 1200);
  });

  fetch(api("")).then(async (res) => {
    if (!res.ok) throw new Error(res.status === 404 ? "링크가 없거나 공유가 중지된 강의입니다." : "강의를 불러오지 못했습니다.");
    render(await res.json());
  }).catch((err) => {
    $("title").textContent = "강의 보기";
    $("error").textContent = err.message;
    $("error").hidden = false;
  });
})();
