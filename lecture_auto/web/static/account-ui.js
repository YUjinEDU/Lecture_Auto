function field(label, attrs) {
  return h("div", { class: "field" }, h("label", { for: attrs.id || attrs.name }, label),
    h("input", { id: attrs.name, ...attrs }));
}

async function renderSignup() {
  nav.hidden = true;
  const { mode } = await api("signup");
  if (mode === "closed") {
    app.replaceChildren(h("section", { class: "card login stack" }, h("h1", {}, "회원가입"),
      h("p", {}, "현재 회원가입을 받지 않습니다."), h("a", { href: "#/" }, "로그인으로 돌아가기")));
    return;
  }
  const error = h("p", { role: "alert", class: "error-text" });
  const form = h("form", { class: "card login stack", onsubmit: (ev) => {
    ev.preventDefault();
    guard(async () => {
      const data = new FormData(form);
      const button = form.querySelector("button");
      button.disabled = true;
      try {
        await api("signup", { json: { email: data.get("email"), password: data.get("password"),
          display_name: data.get("display_name"), terms_accepted: data.get("terms") === "on",
          invite_code: data.get("invite_code") || "" } });
        toast("가입했습니다. 이메일과 비밀번호로 로그인해 주세요.");
        location.hash = "#/";
      } catch (e) {
        if (!(e instanceof Error)) throw e;
        error.textContent = e.message;
      } finally { button.disabled = false; }
    });
  } }, h("h1", {}, "회원가입"),
  field("이메일", { name: "email", type: "email", autocomplete: "username", required: true }),
  field("비밀번호 (10자 이상)", { name: "password", type: "password", minlength: 10, maxlength: 1024,
    autocomplete: "new-password", required: true }),
  field("이름", { name: "display_name", maxlength: 100, autocomplete: "name", required: true }),
  mode === "invite" ? field("초대 코드", { name: "invite_code", required: true }) : null,
  h("label", { class: "check-label" }, h("input", { name: "terms", type: "checkbox", required: true }),
    h("span", {}, h("a", { href: "terms", target: "_blank" }, "이용약관"), "에 동의합니다")),
  error, h("button", { type: "submit", class: "primary" }, "가입하기"),
  h("a", { href: "#/" }, "로그인으로 돌아가기"));
  app.replaceChildren(form);
}

async function renderSettings(me) {
  const key = await api("settings/key");
  const status = h("p", { role: "status" }, key.last4 ? `등록된 키: 끝 4자리 ${key.last4}` : "등록된 키가 없습니다.");
  const error = h("p", { role: "alert", class: "error-text" });
  const input = h("input", { id: "api-key", type: "password", autocomplete: "off", required: true, minlength: 4 });
  const save = h("button", { type: "submit", class: "primary" }, "키 검증 후 저장");
  const form = h("form", { class: "card stack", onsubmit: (ev) => {
    ev.preventDefault();
    guard(async () => {
      save.disabled = true;
      error.textContent = "";
      try {
        const result = await api("settings/key", { method: "PUT", json: { key: input.value } });
        input.value = "";
        status.textContent = `등록된 키: 끝 4자리 ${result.last4}`;
      } catch (e) {
        if (!(e instanceof Error)) throw e;
        error.textContent = e.message;
      } finally { save.disabled = false; }
    });
  } }, h("h2", {}, "BAZE API 키"), status,
  h("p", {}, "대본 생성과 Gemini 음성 제작 비용은 본인의 API 계정에서 청구됩니다."),
  h("label", { for: "api-key" }, "새 API 키"), input, error,
  h("div", { class: "actions" }, save, h("button", { type: "button", class: "danger", onclick: () => guard(async () => {
    if (!confirm("등록된 API 키를 삭제할까요?")) return;
    await api("settings/key", { method: "DELETE" });
    status.textContent = "등록된 키가 없습니다.";
  }) }, "키 삭제")));
  app.replaceChildren(h("section", { class: "stack account-page" }, h("h1", {}, "계정 설정"),
    h("p", {}, `${me.display_name} · ${me.email}`), usageCard(me), form, h("a", { href: "terms" }, "이용약관")));
}

function usageCard(me) {
  if (!me.limits || !me.usage) return null;
  const meter = (label, used, limit, fmt) => h("div", { class: "meter" },
    h("div", { class: "row spread small" }, h("span", {}, label),
      h("span", {}, limit === null ? `${fmt(used)} 사용 · 무제한` : `${fmt(used)} / ${fmt(limit)}`)),
    limit === null ? null : h("div", { class: "progress" + (used >= limit ? " full" : "") },
      h("span", { style: `width:${limit ? Math.min(100, (used / limit) * 100) : 100}%` })));
  const n = (x) => `${x}개`;
  const mb = me.limits.storage_limit_mb;
  return h("section", { class: "card stack" }, h("h2", {}, "사용량"),
    meter("강의", me.usage.lectures, me.limits.max_lectures, n),
    meter("내 음성", me.usage.voices, me.limits.max_voices, n),
    meter("저장 공간", me.usage.storage_bytes, mb === null ? null : mb * 1024 * 1024, fmtSize),
    me.limits.unlimited ? h("p", { class: "muted small" }, "이 계정은 한도 없이 사용할 수 있습니다.")
      : h("p", { class: "muted small" }, "한도를 늘리려면 관리자에게 문의하세요."));
}

function reportDialog(type, id) {
  const dialog = h("dialog", {});
  const reason = h("textarea", { id: "report-reason", required: true, maxlength: 4000 });
  const form = h("form", { class: "stack", onsubmit: (event) => {
    event.preventDefault();
    guard(async () => {
      await api("reports", { json: { target_type: type, target_id: id, reason: reason.value } });
      dialog.close();
      toast("신고를 접수했습니다.");
    });
  } }, h("h2", {}, "신고 접수"), h("label", { for: "report-reason" }, "신고 사유"), reason,
  h("div", { class: "actions" }, h("button", { type: "submit", class: "primary" }, "신고 보내기"),
    h("button", { type: "button", onclick: () => dialog.close() }, "취소")));
  dialog.append(form);
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}
