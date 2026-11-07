function renderLogin() {
  stopPolling();
  nav.hidden = true;
  const email = h("input", { type: "email", id: "email", autocomplete: "username", required: true });
  const input = h("input", { type: "password", id: "pw", autocomplete: "current-password", required: true });
  const form = h("form", { class: "card login stack", onsubmit: (ev) => {
    ev.preventDefault();
    guard(async () => {
      try {
        await api("login", { json: { email: email.value, password: input.value } });
      } catch (e) {
        input.select();
        throw e;
      }
      location.hash = "#/";
      route();
    });
  } },
    h("h1", {}, "로그인"),
    h("div", { class: "field" }, h("label", { for: "email" }, "이메일"), email),
    h("div", { class: "field" }, h("label", { for: "pw" }, "비밀번호"), input),
    h("button", { class: "primary", type: "submit" }, "들어가기"),
    h("a", { href: "#/signup" }, "회원가입"), h("a", { href: "terms", target: "_blank" }, "이용약관"));
  app.replaceChildren(form);
  input.focus();
}

function route() {
  const hash = decodeURIComponent(location.hash.slice(1) || "/");
  guard(async () => {
    stopPolling();
    if (hash === "/signup") return renderSignup();
    const me = await api("me");
    state.me = me;
    document.getElementById("admin-link").hidden = me.role !== "admin";
    document.querySelector('#nav a[href="#/voices"]').hidden = me.raon_enabled === false;
    nav.hidden = false;
    if (hash.startsWith("/lecture/")) return renderLecture(hash.slice("/lecture/".length));
    if (hash === "/jobs") return renderJobs();
    if (hash === "/settings") return renderSettings(me);
    if (hash === "/voices") return renderVoices();
    if (hash === "/admin") return renderAdmin();
    return renderDashboard();
  });
}

document.getElementById("logout").addEventListener("click", () => guard(async () => {
  await api("logout", { method: "POST" });
  renderLogin();
}));
// beforeunload does not fire on hash navigation, and opening another lecture resets
// state.dirty -- ask before an unsaved script edit is thrown away.
let currentHash = location.hash;
window.addEventListener("hashchange", () => {
  if ((Object.keys(state.dirty).length || hasUnsavedIntent()) && !confirm("저장하지 않은 대본 또는 의도 시트 수정이 있습니다. 이동하면 사라집니다. 이동할까요?")) {
    history.replaceState(null, "", currentHash || "#/");
    return;
  }
  state.dirty = {};
  state.intentDraft = null;
  currentHash = location.hash;
  route();
});
window.addEventListener("beforeunload", (ev) => {
  if (Object.keys(state.dirty).length || hasUnsavedIntent()) ev.preventDefault();
});
route();
