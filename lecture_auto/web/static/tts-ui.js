async function ttsFields(lecture = {}) {
  const [options, voices] = await Promise.all([api("tts-options"), api("voices")]);
  const engine = h("select", { id: "tts-engine", name: "tts_engine" },
    h("option", { value: "raon" }, "Raon · 내 음성 복제 (학교 내부용)"),
    h("option", { value: "gemini" }, "Gemini · API 음성"));
  engine.value = lecture.tts_engine || "raon";
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
  return h("fieldset", { class: "stack" }, h("legend", {}, "음성 설정"),
    h("div", { class: "field" }, h("label", { for: "tts-engine" }, "음성 엔진"), engine), raonFields, geminiFields);
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
