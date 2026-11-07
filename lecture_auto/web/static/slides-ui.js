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

function replaceSlide(lec, view, busy) {
  const i = lec.slide_list.findIndex((s) => s.number === view.number);
  if (i >= 0) lec.slide_list[i] = view;
  document.getElementById(`slide-${view.number}`)?.replaceWith(slideRow(lec, view, busy));
  updateDirtyUI();
}

function slideRow(lec, s, busy) {
  const base = `lectures/${enc(lec.id)}/slides/${s.number}`;
  const original = s.script ?? "";
  const textarea = h("textarea", { "aria-label": `슬라이드 ${s.number} 대본`, disabled: busy || s.script === null, spellcheck: "false" },
    state.dirty[s.number] ?? original);
  const info = h("span", { class: "small muted" });
  const saveScript = async () => {
    const view = await api(`${base}/script`, { method: "PUT", json: { script: textarea.value } });
    delete state.dirty[s.number];
    return view;
  };
  const saveBtn = h("button", { class: "primary", disabled: true, onclick: () => guard(async () => {
    const view = await saveScript();
    toast(`슬라이드 ${s.number} 대본을 저장했습니다.`);
    replaceSlide(lec, view, busy);
  }) }, "저장");
  const undo = h("button", { class: "link", disabled: true, onclick: () => { textarea.value = original; sync(); } }, "수정 취소");
  const regen = h("button", { disabled: busy || s.script === null, onclick: () => guard(async () => {
    const changed = textarea.value !== original;
    if (!confirm(`슬라이드 ${s.number}${changed ? "의 대본을 저장하고" : ""} 음성을 새로 만들까요? 새 음성은 '후보'로 저장되어 들어보고 채택할 수 있습니다.`)) return;
    if (changed) await saveScript();
    await api(`lectures/${enc(lec.id)}/jobs`, { json: { kind: "regen", slides: [s.number] } });
    toast(`슬라이드 ${s.number} 음성 다시 만들기를 시작했습니다.`);
    window.scrollTo({ top: 0, behavior: "smooth" });
    renderLecture(lec.id);
  }) }, textarea.value !== original ? "저장하고 음성 다시 만들기" : "이 슬라이드 음성 다시 만들기");
  const article = h("article", { class: "card slide", id: `slide-${s.number}` });
  const sync = () => {
    const value = textarea.value;
    const changed = value !== original;
    if (changed) state.dirty[s.number] = value; else delete state.dirty[s.number];
    saveBtn.disabled = busy || !changed || !value.trim();
    undo.disabled = !changed;
    regen.textContent = changed ? "저장하고 음성 다시 만들기" : "이 슬라이드 음성 다시 만들기";
    const seconds = value.length / 7.0;
    const target = s.target_seconds;
    const off = target && (seconds > target * 1.35 || seconds < target * 0.78);
    info.textContent = `${value.length.toLocaleString()}자 · 읽는 시간 약 ${fmtDur(seconds)}${target ? ` (계획 ${fmtDur(target)})` : ""}${changed ? " · 저장 안 됨" : ""}`;
    info.className = `small ${off ? "warn-text" : "muted"}`;
    article.classList.toggle("dirty", changed);
    updateDirtyUI();
  };
  textarea.addEventListener("input", sync);

  const check = h("input", { type: "checkbox", checked: state.selected.has(s.number), onchange: (ev) => {
    if (ev.target.checked) state.selected.add(s.number); else state.selected.delete(s.number);
    const count = document.getElementById("regen-count");
    if (count) count.textContent = state.selected.size;
  } });
  const player = (label, kind) => h("div", { class: "player" },
    h("div", { class: "row spread" }, h("span", {}, label),
      h("a", { class: "small", href: `api/${base}/audio/${kind}?download=1` }, "내려받기")),
    h("audio", { controls: true, preload: "none", src: `api/${base}/audio/${kind}` }));
  const players = [];
  if (s.audio) players.push(player("현재 음성", "main"));
  if (s.candidate) players.push(player("새로 만든 후보 음성", "cand"));
  if (s.previous) players.push(player("이전 음성 (후보 채택 전)", "prev"));
  const act = (label, cls, fn) => h("button", { class: cls, disabled: busy, onclick: () => guard(fn) }, label);
  const buttons = [];
  if (s.candidate) {
    buttons.push(act(s.candidate_ok ? "후보 채택" : "후보 강제 채택", "primary", async () => {
      const allow = !s.candidate_ok;
      if (allow && !confirm("이 후보는 자동 검사를 통과하지 못했습니다. 직접 들어보셨고 그래도 채택하시겠습니까?")) return;
      await api(`${base}/promote`, { json: { allow_failed: allow } });
      toast(`슬라이드 ${s.number}: 후보를 채택하고 승인했습니다.`);
      renderLecture(lec.id);
    }));
  }
  if (s.audio && s.state !== "approved") {
    buttons.push(act("현재 음성 승인", null, async () => {
      if (s.state === "held" && !confirm("이 음성은 자동 검사를 통과하지 못했습니다. 직접 들어보고 괜찮으면 승인하세요. 승인할까요?")) return;
      await api(`${base}/approve`, { method: "POST" });
      toast(`슬라이드 ${s.number}: 현재 음성을 승인했습니다.`);
      renderLecture(lec.id);
    }));
  }
  if (s.state === "approved") {
    buttons.push(act("승인 취소", null, async () => {
      if (!confirm("이 슬라이드의 승인을 취소할까요? 음성 파일은 그대로 남습니다.")) return;
      await api(`${base}/unapprove`, { method: "POST" });
      toast(`슬라이드 ${s.number}: 승인을 취소했습니다.`);
      renderLecture(lec.id);
    }));
  }
  if (s.previous) {
    buttons.push(act("이전 음성으로 되돌리기", null, async () => {
      if (!confirm("현재 음성과 이전 음성을 맞바꿉니다. 승인은 취소되며, 한 번 더 누르면 원래대로 돌아옵니다. 진행할까요?")) return;
      await api(`${base}/restore-prev`, { method: "POST" });
      toast(`슬라이드 ${s.number}: 이전 음성으로 되돌렸습니다.`);
      renderLecture(lec.id);
    }));
  }
  const revert = s.original ? h("button", { class: "link", disabled: busy, onclick: () => guard(async () => {
    if (!confirm("직접 고친 내용을 버리고 처음 생성된 대본으로 되돌릴까요?")) return;
    const view = await api(`${base}/script/revert`, { method: "POST" });
    delete state.dirty[s.number];
    toast(`슬라이드 ${s.number}: 처음 생성된 대본으로 되돌렸습니다.`);
    replaceSlide(lec, view, busy);
  }) }, "처음 생성된 대본으로") : null;

  article.append(
    h("div", { class: "slide-media" },
      s.image ? h("img", { src: `api/${base}/image`, alt: `슬라이드 ${s.number}`, loading: "lazy" }) : h("div", { class: "empty" }, "이미지 없음"),
      players),
    h("div", { class: "slide-edit" },
      h("div", { class: "slide-head" }, h("span", { class: "num" }, `슬라이드 ${s.number}`), badge(SLIDE_STATE[s.state]),
        s.candidate ? badge(["후보 있음", "b-info"]) : null, s.hand_edited ? badge(["직접 수정함", "b-warn"]) : null,
        h("label", { class: "select-box" }, check, "다시 만들기 선택")),
      textarea,
      h("div", { class: "row spread" }, info, h("div", { class: "row" }, revert, undo, saveBtn)),
      h("div", { class: "actions" }, regen, buttons),
      qcBlock(s.qc, "현재 음성 검사"), qcBlock(s.candidate_qc, "후보 검사")));
  sync();
  return article;
}
