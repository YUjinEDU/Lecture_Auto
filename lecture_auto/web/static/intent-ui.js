"use strict";

const INTENT_ROLES = ["도입", "개념", "예시", "비교", "과정", "정리", "전환", "기타"];

function hasUnsavedIntent() {
  return Boolean(state.intentDraft?.dirty);
}

async function intentEditor(lec, busy) {
  const base = `lectures/${enc(lec.id)}`;
  const saved = lec.has_intent ? await api(`${base}/intent`) : null;
  if (state.intentDraft?.id !== lec.id || !state.intentDraft?.dirty) {
    state.intentDraft = { id: lec.id, sheet: saved ? structuredClone(saved) : null, dirty: false };
  }
  const draft = state.intentDraft;
  const section = h("section", { class: "card intent-editor", id: "intent-editor" });
  const error = h("p", { class: "bad-text", role: "alert", hidden: true });
  const reportError = async (fn) => {
    error.hidden = true;
    try { await fn(); } catch (e) {
      if (e instanceof Unauthorized) throw e;
      error.textContent = e instanceof Error ? e.message : String(e);
      error.hidden = false;
    }
  };
  const draftButton = h("button", { disabled: busy, onclick: () => guard(() => reportError(async () => {
    if ((saved?.edited || draft.dirty) && !confirm("수정한 의도 시트를 새 초안으로 바꿀까요? 지금 작성한 내용은 사라집니다.")) return;
    await api(`${base}/jobs`, { json: { kind: "intent", force: Boolean(saved?.edited) } });
    draft.dirty = false;
    await renderLecture(lec.id);
  })) }, saved ? "초안 다시 만들기" : "슬라이드 의도 초안 만들기");
  section.append(h("div", { class: "row spread" }, h("h2", {}, "슬라이드 의도 정리"), draftButton));
  section.append(h("p", { class: "muted" },
    "각 장에서 전할 한 문장과 설명 시간을 먼저 정합니다. 선택 단계이며, 건너뛰고 대본을 만들 수도 있습니다."));
  if (!draft.sheet) {
    section.append(error);
    return section;
  }
  const form = h("form", { class: "intent-form", onsubmit: (ev) => ev.preventDefault() });
  const total = h("output", { class: "intent-total", "aria-live": "polite" });
  const status = h("span", { class: "muted small" });
  const saveButton = h("button", { type: "button", disabled: busy || !draft.dirty,
    onclick: () => guard(() => reportError(async () => {
      await save();
      await renderLecture(lec.id);
    })) }, "의도 시트 저장");
  const sync = () => {
    const seconds = draft.sheet.slides.reduce((sum, s) => sum + (Number(s.seconds) || 0), 0);
    const target = lec.target_minutes || 40;
    total.textContent = `배분 합계 ${(seconds / 60).toFixed(1)}분 (${seconds}초) / 목표 ${target}분`;
    total.classList.toggle("warn-text", Math.abs(seconds - target * 60) > target * 3);
    status.textContent = draft.dirty ? "저장하지 않은 수정이 있습니다" : saved?.edited ? "교수자 수정본" : "자동 생성 초안";
    saveButton.disabled = busy || !draft.dirty;
  };
  const save = async () => {
    if (!form.reportValidity()) throw new Error("핵심 문장과 중요도, 시간 범위를 확인해 주세요.");
    if (!draft.dirty) return;
    draft.sheet = await api(`${base}/intent`, { method: "PUT", json: draft.sheet });
    draft.dirty = false;
    sync();
  };
  const field = (slide, key, label, input) => {
    const id = `intent-${slide.slide}-${key}`;
    input.id = id;
    input.disabled = busy;
    input.addEventListener("input", () => {
      slide[key] = ["importance", "seconds"].includes(key) ? Number(input.value) : input.value;
      draft.dirty = true;
      sync();
    });
    return h("div", { class: `field intent-${key}` }, h("label", { for: id }, label), input);
  };
  const rows = draft.sheet.slides.map((slide) => h("fieldset", { class: "intent-row", disabled: busy },
    h("legend", {}, `슬라이드 ${slide.slide}`),
    field(slide, "thesis", "반드시 전할 한 문장", h("textarea", { rows: 2, required: true, maxlength: 2000 }, slide.thesis)),
    h("div", { class: "intent-pacing" },
      field(slide, "role", "역할", h("select", {}, INTENT_ROLES.map((role) =>
        h("option", { value: role, selected: slide.role === role }, role)))),
      field(slide, "importance", "중요도", h("select", {}, [1, 2, 3].map((n) =>
        h("option", { value: n, selected: slide.importance === n }, `${n}${n === 3 ? " (핵심)" : ""}`)))),
      field(slide, "seconds", "설명 시간 (초)", h("input", { type: "number", min: 10, max: 600, step: 1, required: true, value: slide.seconds }))),
    h("div", { class: "intent-notes" },
      field(slide, "pitfall", "학생이 막히는 지점", h("textarea", { rows: 2, maxlength: 4000 }, slide.pitfall)),
      field(slide, "example", "사용할 사례·비유", h("textarea", { rows: 2, maxlength: 4000 }, slide.example)))));
  const rebuild = h("button", { type: "button", disabled: busy, onclick: () => guard(() => reportError(async () => {
    if (Object.keys(state.dirty).length) throw new Error("고친 대본을 먼저 저장해 주세요.");
    if (!confirm("이 의도로 대본을 다시 만들까요? 직접 고치지 않은 대본은 다시 생성됩니다. 손으로 고친 대본은 보존됩니다.")) return;
    await save();
    await api(`${base}/jobs`, { json: { kind: "scripts" } });
    await renderLecture(lec.id);
  })) }, "이 의도로 대본 다시 만들기");
  const details = h("details", { open: !lec.scripts || Boolean(state.intentOpen) },
    h("summary", {}, "슬라이드별 의도 편집"),
    form);
  details.addEventListener("toggle", () => { state.intentOpen = details.open; });
  form.append(h("div", { class: "intent-toolbar" }, total,
    h("div", { class: "row" }, status, saveButton, rebuild)),
    ...rows);
  section.append(details, error);
  sync();
  return section;
}
