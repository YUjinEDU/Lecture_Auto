async function styleProfileCard() {
  const profiles = await api("style-profiles");
  const error = h("p", { role: "alert", class: "error-text" });
  const form = h("form", { class: "stack", onsubmit: (event) => {
    event.preventDefault();
    guard(async () => {
      const button = form.querySelector("button");
      button.disabled = true;
      error.textContent = "";
      try {
        await api("style-profiles", { method: "POST", body: new FormData(form) });
        await route();
      } catch (e) {
        if (!(e instanceof Error)) throw e;
        error.textContent = e.message;
      } finally { button.disabled = false; }
    });
  } }, field("강의 녹취록 (UTF-8 TXT, 최대 2 MB)", {
    name: "file", type: "file", accept: ".txt", required: true }),
  error, h("button", { type: "submit" }, "녹취록에서 말투 만들기"));
  return h("section", { class: "card stack" }, h("h2", {}, "교수님 말투"),
    h("p", {}, "등록한 말투는 본인 강의에서 반복 사용할 수 있습니다. 녹취록 원문은 저장하지 않습니다."),
    form, profiles.length ? profiles.map((p) => h("div", { class: "row spread" },
      h("span", {}, p.name), h("button", { type: "button", onclick: () => guard(async () => {
        if (!confirm("이 말투를 삭제할까요? 사용 중인 강의는 다른 말투를 선택해야 합니다.")) return;
        await api(`style-profiles/${enc(p.id)}`, { method: "DELETE" });
        await route();
      }) }, "말투 삭제"))) : h("p", {}, "등록한 말투가 없습니다."));
}
