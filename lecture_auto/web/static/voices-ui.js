async function renderVoices() {
  const voices = await api("voices");
  const error = h("p", { class: "error-text", role: "alert" });
  const form = h("form", { class: "card stack", onsubmit: (event) => {
    event.preventDefault();
    guard(async () => {
      const button = form.querySelector("button");
      button.disabled = true;
      try {
        await api("voices", { method: "POST", body: new FormData(form) });
        await renderVoices();
      } catch (e) {
        if (!(e instanceof Error)) throw e;
        error.textContent = e.message;
      } finally { button.disabled = false; }
    });
  } }, h("h2", {}, "음성 등록"),
  field("음성 이름", { name: "name", required: true, maxlength: 100 }),
  field("음성 파일 (WAV, MP3, M4A)", { name: "file", type: "file", accept: ".wav,.mp3,.m4a", required: true }),
  h("label", { class: "check-label" }, h("input", { type: "checkbox", name: "consent", value: "true", required: true }),
    h("span", {}, "이 목소리의 주인이 본인이거나, 주인에게 AI 음성 복제 사용 동의를 받았습니다")),
  error, h("button", { type: "submit", class: "primary" }, "음성 등록"));
  const rows = voices.map((voice) => {
    const name = h("input", { id: `name-${voice.id}`, value: voice.name, maxlength: 100, required: true });
    const defaultBox = h("input", { type: "checkbox", checked: Boolean(voice.is_default), disabled: Boolean(voice.disabled) });
    return h("form", { class: "card stack", onsubmit: (event) => {
      event.preventDefault();
      guard(async () => {
        await api(`voices/${voice.id}`, { method: "PUT", json: { name: name.value, is_default: defaultBox.checked } });
        await renderVoices();
      });
    } }, h("label", { for: `name-${voice.id}` }, "음성 이름"), name,
    voice.disabled ? h("p", { class: "error-text" }, "관리자가 비활성화한 음성입니다. 새 제작에 사용할 수 없습니다.") : null,
    h("audio", { controls: true, preload: "none", src: `api/voices/${voice.id}/audio`, "aria-label": voice.name }),
    h("label", { class: "check-label" }, defaultBox, "기본 음성으로 사용"),
    h("div", { class: "actions" }, h("button", { type: "submit" }, "설정 저장"),
      h("button", { type: "button", class: "danger", onclick: () => guard(async () => {
        if (!confirm("이 음성을 삭제할까요? 이 음성을 사용한 강의는 다른 음성을 선택해야 합니다.")) return;
        await api(`voices/${voice.id}`, { method: "DELETE" });
        await renderVoices();
      }) }, "음성 삭제"),
      h("button", { type: "button", onclick: () => reportDialog("voice", voice.id) }, "신고")));
  });
  app.replaceChildren(h("section", { class: "stack account-page" }, h("h1", {}, "내 음성"),
    h("p", {}, "업로드한 음성은 본인 계정에서만 사용할 수 있습니다."), form,
    h("h2", {}, "등록한 음성"), rows.length ? rows : h("p", {}, "등록한 음성이 없습니다.")));
}
