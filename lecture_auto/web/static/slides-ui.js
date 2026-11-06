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
  if (state.dirty[s.number] !== undefined && !busy) saveBtn.disabled = false;
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
