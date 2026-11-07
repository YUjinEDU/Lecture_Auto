async function ttsFields(lecture = {}) {
  const options = await api("tts-options");
  const voices = options.raon_enabled ? await api("voices") : [];
  const profiles = await api("style-profiles");
  const profile = h("select", { id: "style-profile", name: "style_profile" },
    h("option", { value: "" }, "기본 말투"),
    profiles.map((p) => h("option", { value: p.id }, p.name)));
  profile.value = lecture.style_profile || "";
  const critic = h("input", { type: "checkbox", name: "critic", value: "true", checked: Boolean(lecture.critic) });
  const engine = h("select", { id: "tts-engine", name: "tts_engine" },
    options.raon_enabled ? h("option", { value: "raon" }, "Raon · 내 음성 복제 (GPU 서버)") : null,
    h("option", { value: "gemini" }, "Gemini · API 음성"));
  engine.value = options.raon_enabled ? lecture.tts_engine || "raon" : "gemini";
  const ref = h("select", { id: "ref-voice", name: "ref_voice" },
    h("option", { value: "" }, "내 기본 음성 (없으면 서버 기본 음성)"),
    h("option", { value: "data/audio_ref/reference_v1.wav" }, "서버 기본 음성 1"),
    h("option", { value: "data/audio_ref/reference_v2.wav" }, "서버 기본 음성 2"),
    voices.filter((v) => !v.disabled).map((v) => h("option", { value: v.ref_voice }, v.name)));
  ref.value = lecture.ref_voice || "";
  const gemini = h("select", { id: "tts-voice", name: "tts_voice" },
    options.gemini_voices.map((v) => h("option", { value: v }, v)));
  gemini.value = lecture.tts_voice || "Charon";
  const instructions = h("textarea", { id: "tts-instructions", name: "tts_instructions", maxlength: 2000 },
    lecture.tts_instructions || "");
  const raonFields = h("div", { class: "field" }, h("label", { for: "ref-voice" }, "참조 음성"), ref);
  const geminiFields = h("div", { class: "stack" },
    h("div", { class: "field" }, h("label", { for: "tts-voice" }, "Gemini 음성"), gemini),
    h("div", { class: "field" }, h("label", { for: "tts-instructions" }, "말투 지시 (선택)"), instructions));
  const update = () => {
    raonFields.hidden = engine.value !== "raon";
    geminiFields.hidden = engine.value !== "gemini";
  };
  engine.addEventListener("change", update);
  update();
  const note = options.raon_enabled ? null : h("p", { class: "muted small" },
    "이 서버는 API 음성(Gemini)만 씁니다. 대본 생성과 음성 비용은 설정에 등록한 본인 API 키로 청구됩니다.");
  return h("fieldset", { class: "stack" }, h("legend", {}, "음성 설정"), note,
    h("div", { class: "field" }, h("label", { for: "tts-engine" }, "음성 엔진"), engine), raonFields, geminiFields,
    h("div", { class: "field" }, h("label", { for: "style-profile" }, "교수님 말투"), profile),
    h("label", { class: "check-label" }, critic, "대본 다듬기(검토 후 약한 슬라이드만 다시 쓰기)"));
}

async function lectureSettingsDialog(lecture) {
  const dialog = h("dialog", {});
  const fields = await ttsFields(lecture);
  const form = h("form", { class: "stack", onsubmit: (event) => {
    event.preventDefault();
    guard(async () => {
      const data = new FormData(form);
      await api(`lectures/${enc(lecture.id)}/settings`, { method: "PUT", json: {
        tts_engine: data.get("tts_engine"), tts_voice: data.get("tts_voice"),
        critic: data.get("critic") === "true", style_profile: data.get("style_profile") || null,
        tts_instructions: data.get("tts_instructions") || null, ref_voice: data.get("ref_voice") || null } });
      dialog.close();
      await renderLecture(lecture.id);
    });
  } }, h("h2", {}, "강의 음성 설정"), fields,
  h("div", { class: "actions" }, h("button", { type: "submit", class: "primary" }, "설정 저장"),
    h("button", { type: "button", onclick: () => dialog.close() }, "취소")));
  dialog.append(form);
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}
