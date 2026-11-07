const LIMIT_LABELS = [["max_lectures", "강의 수", "개"], ["max_voices", "음성 수", "개"], ["storage_limit_mb", "저장 공간", "MB"]];

function usageText(usage) {
  return `강의 ${usage.lectures}개 · 음성 ${usage.voices}개 · 저장 ${fmtSize(usage.storage_bytes)}`;
}

function numberInput(value, label, placeholder) {
  return h("input", { type: "number", min: 0, step: 1, value: value ?? "", placeholder, "aria-label": label, class: "num" });
}

function readNumber(input) {
  return input.value === "" ? null : Math.max(0, Math.floor(Number(input.value)));
}

function randomPassword() {
  const chars = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return Array.from(crypto.getRandomValues(new Uint32Array(14)), (n) => chars[n % chars.length]).join("");
}

function defaultsCard(defaults) {
  const inputs = Object.fromEntries(LIMIT_LABELS.map(([k, label]) => [k, numberInput(defaults[k], label, "")]));
  return h("form", { class: "card stack", onsubmit: (ev) => {
    ev.preventDefault();
    guard(async () => {
      const body = Object.fromEntries(LIMIT_LABELS.map(([k]) => [k, readNumber(inputs[k]) ?? 0]));
      await api("admin/limits", { method: "PUT", json: body });
      toast("기본 한도를 저장했습니다.");
      await renderAdmin();
    });
  } },
    h("h2", {}, "기본 한도"),
    h("p", { class: "muted small" }, "직접 정하지 않은 계정(공개 가입 등)에 적용됩니다. 관리자와 '무제한' 계정은 한도가 없습니다."),
    h("div", { class: "limit-grid" }, LIMIT_LABELS.map(([k, label, unit]) =>
      h("label", { class: "limit-field" }, `${label} (${unit})`, inputs[k]))),
    h("div", { class: "actions" }, h("button", { type: "submit", class: "primary" }, "기본 한도 저장")));
}

function newUserCard() {
  const email = h("input", { type: "email", required: true, autocomplete: "off" });
  const name = h("input", { required: true, maxlength: 100 });
  const password = h("input", { type: "text", required: true, minlength: 10, autocomplete: "off", value: randomPassword() });
  const role = h("select", {}, h("option", { value: "user" }, "교수자 (일반)"), h("option", { value: "admin" }, "관리자"));
  const unlimited = h("input", { type: "checkbox", checked: true });
  const result = h("p", { class: "wrap", role: "status" });
  return h("form", { class: "card stack", onsubmit: (ev) => {
    ev.preventDefault();
    guard(async () => {
      await api("admin/users", { json: { email: email.value, display_name: name.value, password: password.value,
        role: role.value, unlimited: unlimited.checked } });
      result.textContent = `만들었습니다. 이메일 ${email.value} / 비밀번호 ${password.value} 를 전달해 주세요 (이 화면을 벗어나면 다시 볼 수 없습니다).`;
      toast("계정을 만들었습니다.");
      email.value = ""; name.value = ""; password.value = randomPassword();
      document.getElementById("user-list")?.replaceWith(await usersCard());
    });
  } },
    h("h2", {}, "계정 직접 만들기"),
    h("p", { class: "muted small" }, "같은 학교 교수님처럼 직접 계정을 드릴 때 씁니다. 가입 방식(닫힘/공개/초대)과 상관없이 만들 수 있습니다."),
    h("div", { class: "limit-grid" },
      h("label", { class: "limit-field" }, "이메일", email),
      h("label", { class: "limit-field" }, "이름", name),
      h("label", { class: "limit-field" }, "비밀번호 (10자 이상)", password),
      h("label", { class: "limit-field" }, "권한", role)),
    h("label", { class: "check-label" }, unlimited, h("span", {}, "용량 한도 없이 사용 (무제한)")),
    h("div", { class: "actions" }, h("button", { type: "submit", class: "primary" }, "계정 만들기")),
    result);
}

function userRow(user, refresh) {
  const o = user.overrides || {};
  const isAdmin = user.role === "admin";
  const unlimited = h("input", { type: "checkbox", checked: Boolean(o.unlimited), disabled: isAdmin });
  const inputs = Object.fromEntries(LIMIT_LABELS.map(([k, label]) => [k, numberInput(o[k], label, "기본값")]));
  const syncDisabled = () => Object.values(inputs).forEach((i) => { i.disabled = isAdmin || unlimited.checked; });
  unlimited.addEventListener("change", syncDisabled);
  syncDisabled();
  const effective = user.limits.unlimited ? "무제한"
    : LIMIT_LABELS.map(([k, label, unit]) => `${label} ${user.limits[k]}${unit}`).join(" · ");
  return h("article", { class: "user-row" },
    h("div", { class: "row spread" },
      h("div", { class: "wrap" }, h("b", {}, user.display_name), ` · ${user.email} `,
        badge(isAdmin ? ["관리자", "b-info"] : ["교수자", "b-none"]), " ", user.disabled ? badge(["비활성", "b-bad"]) : null),
      isAdmin ? null : h("button", { class: user.disabled ? "" : "danger", onclick: () => guard(async () => {
        await api(`admin/users/${user.id}`, { method: "PUT", json: { disabled: !user.disabled } });
        toast(user.disabled ? "다시 활성화했습니다." : "비활성화했습니다.");
        refresh();
      }) }, user.disabled ? "활성화" : "비활성화")),
    h("p", { class: "muted small" }, `사용: ${usageText(user.usage)} · 적용 한도: ${effective}`),
    isAdmin ? h("p", { class: "muted small" }, "관리자는 항상 한도가 없습니다.") : h("div", { class: "row limit-row" },
      h("label", { class: "check-label" }, unlimited, h("span", {}, "무제한")),
      LIMIT_LABELS.map(([k, label, unit]) => h("label", { class: "limit-field" }, `${label} (${unit})`, inputs[k])),
      h("button", { onclick: () => guard(async () => {
        await api(`admin/users/${user.id}/limits`, { method: "PUT", json: {
          unlimited: unlimited.checked, ...Object.fromEntries(LIMIT_LABELS.map(([k]) => [k, readNumber(inputs[k])])) } });
        toast(`${user.display_name}님의 한도를 저장했습니다.`);
        refresh();
      }) }, "한도 저장")));
}

async function usersCard() {
  const users = await api("admin/users");
  const card = h("section", { class: "card stack", id: "user-list" }, h("h2", {}, `계정 (${users.length})`),
    h("p", { class: "muted small" }, "칸을 비워 두면 기본 한도를 씁니다. 0은 '더 만들 수 없음'입니다."));
  const refresh = () => guard(async () => card.replaceWith(await usersCard()));
  users.forEach((u) => card.append(userRow(u, refresh)));
  return card;
}

async function renderAdmin() {
  const [reports, defaults] = await Promise.all([api("admin/reports"), api("admin/limits")]);
  const invite = h("p", { role: "status", class: "wrap" });
  const toggle = (path, disabled) => guard(async () => {
    await api(`admin/${path}`, { method: "PUT", json: { disabled } });
    toast(disabled ? "비활성화했습니다." : "다시 활성화했습니다.");
    await renderAdmin();
  });
  app.replaceChildren(h("section", { class: "stack admin-page" }, h("h1", {}, "서비스 관리"),
    newUserCard(), await usersCard(), defaultsCard(defaults),
    h("section", { class: "card stack" }, h("h2", {}, "초대 코드"),
      h("p", { class: "muted small" }, "가입 방식이 '초대'일 때, 이 코드를 받은 사람만 스스로 가입할 수 있습니다."),
      h("div", { class: "actions" }, h("button", { type: "button", onclick: () => guard(async () => {
        const result = await api("admin/invites", { method: "POST" });
        invite.textContent = result.code;
      }) }, "일회용 초대 코드 발급")), invite),
    h("section", { class: "card stack" }, h("h2", {}, `신고 (${reports.length})`),
      reports.length ? reports.map((report) => h("article", { class: "user-row stack" },
        h("p", { class: "wrap" }, h("b", {}, report.target_type === "voice" ? "음성" : "강의"), ` · ${report.target_id} · ${new Date(report.created_at).toLocaleString("ko-KR")}`),
        h("p", { class: "wrap" }, report.reason),
        h("div", { class: "actions" },
          h("button", { class: "danger", onclick: () => toggle(
            `${report.target_type === "voice" ? "voices" : "lectures"}/${enc(report.target_id)}`, true) }, "대상 비활성화"),
          h("button", { onclick: () => toggle(
            `${report.target_type === "voice" ? "voices" : "lectures"}/${enc(report.target_id)}`, false) }, "다시 활성화"))))
        : h("p", { class: "muted" }, "접수된 신고가 없습니다."))));
}
