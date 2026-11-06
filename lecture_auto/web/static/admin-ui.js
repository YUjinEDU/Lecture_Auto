async function renderAdmin() {
  const [reports, users] = await Promise.all([api("admin/reports"), api("admin/users")]);
  const invite = h("p", { role: "status", class: "wrap" });
  const toggle = (path, disabled) => guard(async () => {
    await api(`admin/${path}`, { method: "PUT", json: { disabled } });
    toast(disabled ? "비활성화했습니다." : "다시 활성화했습니다.");
    await renderAdmin();
  });
  app.replaceChildren(h("section", { class: "stack" }, h("h1", {}, "서비스 관리"),
    h("section", { class: "card stack" }, h("h2", {}, "초대 코드"),
      h("button", { type: "button", class: "primary", onclick: () => guard(async () => {
        const result = await api("admin/invites", { method: "POST" });
        invite.textContent = result.code;
      }) }, "일회용 초대 코드 발급"), invite),
    h("section", { class: "card stack" }, h("h2", {}, "사용자"),
      users.map((user) => h("div", { class: "row spread" },
        h("span", { class: "wrap" }, `${user.display_name} · ${user.email} · ${user.disabled ? "비활성" : "사용 중"}`),
        h("button", { class: user.disabled ? "" : "danger", onclick: () => toggle(`users/${user.id}`, !user.disabled) },
          user.disabled ? "활성화" : "비활성화")))),
    h("section", { class: "card stack" }, h("h2", {}, "신고"),
      reports.length ? reports.map((report) => h("article", { class: "stack" },
        h("p", { class: "wrap" }, `${report.target_type === "voice" ? "음성" : "강의"} · ${report.target_id}`),
        h("p", { class: "wrap" }, report.reason),
        h("div", { class: "actions" },
          h("button", { class: "danger", onclick: () => toggle(
            `${report.target_type === "voice" ? "voices" : "lectures"}/${enc(report.target_id)}`, true) }, "대상 비활성화"),
          h("button", { onclick: () => toggle(
            `${report.target_type === "voice" ? "voices" : "lectures"}/${enc(report.target_id)}`, false) }, "다시 활성화"))))
        : h("p", {}, "접수된 신고가 없습니다."))));
}
