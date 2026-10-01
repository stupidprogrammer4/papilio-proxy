/* Papilio owner console — no third-party scripts, frameworks, or browser storage. */
(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const root = $("#view-root");
  const state = { csrf: "", view: "overview", userQuery: "", offsets: { users: 0, orders: 0, payments: 0 } };
  const titles = {
    overview: ["نمای کلی", "وضعیت کسب‌وکار و سرویس در یک نگاه", "OVERVIEW"],
    plans: ["مدیریت پلن‌ها", "حجم، قیمت، ایموجی و انتشار هر پلن را همین‌جا تنظیم کن", "PLANS"],
    pricing: ["اقتصاد و قیمت‌گذاری", "هزینهٔ سرور، مازاد ترافیک و سناریوی سود را شفاف ببین", "PRICING"],
    users: ["کاربران", "اطلاعات حساب‌های ثبت‌شده در بات", "CUSTOMERS"],
    orders: ["سفارش‌ها", "وضعیت درخواست‌ها و مصرف ثبت‌شده", "ORDERS"],
    payments: ["پرداخت‌ها", "تراکنش‌های متصل به سفارش؛ تأیید فقط از KPay", "PAYMENTS"],
    branding: ["برند و متن بات", "نام و توضیحات پروفایل تلگرام را مدیریت کن", "BRANDING"],
    system: ["وضعیت سیستم", "آنچه آماده است و آنچه قبل از فروش باید کامل شود", "SYSTEM"],
  };

  function node(tag, className = "", text = "") {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== "") element.textContent = String(text);
    return element;
  }
  function add(parent, ...children) { parent.append(...children); return parent; }
  function n(value) { return new Intl.NumberFormat("fa-IR").format(Number(value) || 0); }
  function toman(value) { return `${n(value)} تومان`; }
  function gib(bytes) { return `${n((Number(bytes) || 0) / 1073741824)} گیگابایت`; }
  function date(value) {
    if (!value) return "—";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "—" : new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short" }).format(parsed);
  }
  function shortId(value) { return value ? String(value).slice(0, 8) : "—"; }
  function toast(message, error = false) {
    const item = node("div", error ? "toast error" : "toast", message);
    $("#toasts").append(item);
    window.setTimeout(() => item.remove(), 4500);
  }
  async function api(path, options = {}) {
    const method = options.method || "GET";
    const headers = { Accept: "application/json", ...options.headers };
    if (method !== "GET") {
      headers["Content-Type"] = "application/json";
      if (state.csrf) headers["X-CSRF-Token"] = state.csrf;
    }
    const response = await fetch(`/admin/api${path}`, { ...options, method, headers, credentials: "same-origin", cache: "no-store" });
    if (response.status === 401 && path !== "/login") showLogin();
    if (!response.ok) {
      let message = "درخواست انجام نشد. کمی بعد دوباره تلاش کن.";
      try { const data = await response.json(); if (typeof data.detail === "string") message = data.detail; } catch { /* generic */ }
      throw new Error(message);
    }
    return response.status === 204 ? null : response.json();
  }
  function showLogin() {
    state.csrf = "";
    $("#workspace").hidden = true;
    $("#login-screen").hidden = false;
    $("#login-password").value = "";
  }
  function showWorkspace(session) {
    state.csrf = session.csrf;
    $("#admin-name").textContent = session.username;
    $("#login-screen").hidden = true;
    $("#workspace").hidden = false;
    setView(state.view);
  }
  function button(label, className = "btn btn-quiet", onClick) {
    const b = node("button", className, label);
    b.type = "button";
    if (onClick) b.addEventListener("click", onClick);
    return b;
  }
  function heading(title, subtitle = "") {
    const h = node("div", "section-title");
    const block = node("div");
    add(block, node("h2", "", title));
    if (subtitle) add(block, node("p", "", subtitle));
    return add(h, block);
  }
  function empty(text, icon = "✦") {
    return add(node("div", "empty"), node("span", "empty-icon", icon), node("span", "", text));
  }
  function statusBadge(value) {
    const map = {
      active: ["فعال", "green"], pending_payment: ["در انتظار پرداخت", "amber"],
      paid_awaiting_provisioning: ["پرداخت‌شده · در انتظار تحویل", "blue"],
      expired: ["منقضی", "gray"], suspended: ["متوقف", "red"],
      paid: ["تأییدشده", "green"], pending: ["در انتظار تأیید", "amber"],
      failed: ["ناموفق", "red"],
    };
    const [text, color] = map[value] || [value || "ثبت نشده", "gray"];
    return node("span", `badge ${color}`, text);
  }
  function table(columns, rows, emptyText) {
    const box = node("div", "table-card");
    if (!rows.length) return add(box, empty(emptyText));
    const scroll = node("div", "table-scroll");
    const t = node("table");
    const header = node("tr");
    for (const [title] of columns) add(header, node("th", "", title));
    add(t, add(node("thead"), header));
    const body = node("tbody");
    for (const row of rows) {
      const tr = node("tr");
      for (const [, render] of columns) {
        const td = node("td");
        const value = render(row);
        td.append(value instanceof Node ? value : document.createTextNode(String(value ?? "—")));
        tr.append(td);
      }
      body.append(tr);
    }
    add(t, body);
    return add(box, add(scroll, t));
  }
  function paged(box, kind, rows, load) {
    const nav = node("div", "pager");
    const offset = state.offsets[kind];
    const prev = button("← جدیدتر", "btn btn-ghost btn-small", () => { state.offsets[kind] = Math.max(0, offset - 50); load(); });
    prev.disabled = offset === 0;
    const next = button("قدیمی‌تر →", "btn btn-ghost btn-small", () => { state.offsets[kind] = offset + 50; load(); });
    next.disabled = rows.length < 50;
    return add(box, add(nav, prev, node("span", "", `صفحهٔ ${n(offset / 50 + 1)}`), next));
  }
  function stat(label, value, hint, symbol, accent) {
    const card = node("div", "stat");
    card.style.setProperty("--accent", accent);
    return add(card, node("div", "symbol", symbol), node("div", "label", label),
      node("div", "value", value), node("div", "hint", hint));
  }
  async function overview() {
    const data = await api("/overview");
    const hero = node("div", "hero");
    const heroText = node("div");
    add(heroText, node("span", "eyebrow", "YOUR SPACE, YOUR CONTROL"),
      node("h2", "", "نبض پاپیلیو، همین‌جا."),
      node("p", "", "آمار از MySQL خوانده می‌شود. تا اتصال نود و شمارندهٔ زنده، فروش و تحویل خودکار غیرفعال می‌ماند."));
    add(hero, heroText, node("span", "hero-badge", "● پایلوت · فروش قفل"));
    const stats = node("div", "stats-grid");
    add(stats, stat("کاربران", n(data.users), "حساب‌های ثبت‌شده", "♧", "#67e5ce"),
      stat("سفارش‌ها", n(data.subscriptions), "مجموع درخواست‌ها", "▣", "#a58cff"),
      stat("سرویس فعال", n(data.active), "طبق وضعیت دیتابیس", "✦", "#6fbcff"),
      stat("در انتظار پرداخت", n(data.pending), "بدون فعال‌سازی", "◇", "#f8bc70"));
    const traffic = node("div", "card");
    add(traffic, node("h3", "", "📊 مصرف ثبت‌شده"));
    const ratio = data.traffic_limit > 0 ? Math.min(100, data.traffic_used / data.traffic_limit * 100) : 0;
    const line = node("div", "metric-line");
    add(line, node("span", "", "مصرف / مجموع حجم پلن‌ها"), node("strong", "mono", `${gib(data.traffic_used)} / ${gib(data.traffic_limit)}`));
    const bar = node("div", "bar");
    const fill = node("div", "bar-fill"); fill.style.width = `${ratio}%`;
    add(traffic, line, add(bar, fill), node("p", "", "این عدد از رکوردهای دیتابیس است؛ تا اتصال شمارندهٔ Xray، آن را مصرف لحظه‌ای در نظر نگیر."));
    const latest = node("div", "card");
    add(latest, node("h3", "", "✨ آخرین کاربران"));
    if (!data.recent_users.length) add(latest, empty("هنوز کاربری ثبت نشده است."));
    for (const item of data.recent_users) {
      const row = node("div", "list-row");
      const info = node("div");
      add(info, node("strong", "", item[1]), node("small", "mono", `${item[0]} · ${n(item[3])} سفارش`));
      add(latest, add(row, info, node("span", "muted", item[2] ? `@${item[2]}` : "—")));
    }
    const finance = node("div", "finance-card");
    const financeText = node("div");
    add(financeText, node("div", "eyebrow", "VERIFIED PAYMENTS / مجموع پرداخت‌های تأییدشده"),
      node("strong", "finance-value", toman(data.financial.settled_amount_rial / 10)),
      node("p", "", `${n(data.financial.settled_count)} تراکنش تأییدشدهٔ KPay · ${n(data.financial.pending_count)} تراکنش در انتظار بررسی · بازپرداخت احتمالی لحاظ نشده`));
    add(finance, financeText, node("span", "finance-icon", "◇"));
    const pair = node("div", "split"); add(pair, traffic, latest);
    root.replaceChildren(hero, stats, finance,
      heading("جزئیات سریع", "داده‌های ثبت‌شده، بدون حدس یا عدد ساختگی"), pair);
  }
  function planForm(plan = null) {
    const panel = node("section", "panel form-panel");
    add(panel, node("h2", "", plan ? `ویرایش ${plan.title}` : "ساخت پلن جدید"),
      node("p", "", "قیمت را به تومان وارد کن؛ ذخیره‌سازی در دیتابیس به ریال انجام می‌شود."));
    const form = node("form");
    const grid = node("div", "form-grid");
    const specs = [
      ["code", "کد پلن", "text", plan?.code || "", "", true],
      ["title", "عنوان نمایشی", "text", plan?.title || "", "wide", true],
      ["emoji", "ایموجی", "text", plan?.emoji || "🦋", "", true],
      ["traffic_gb", "حجم (گیگابایت)", "number", plan?.traffic_gb || "", "", true],
      ["duration_days", "مدت (روز)", "number", plan?.duration_days || "", "", true],
      ["price_toman", "قیمت (تومان)", "number", plan?.price_toman || "", "", true],
      ["sort_order", "ترتیب نمایش", "number", plan?.sort_order ?? 0, "", false],
    ];
    for (const [key, label, type, value, span, required] of specs) {
      const wrap = node("div", span);
      const id = `plan-${key}`;
      const caption = node("label", "", label); caption.htmlFor = id;
      const input = node("input", "field");
      input.id = id; input.name = key; input.type = type; input.value = String(value); input.required = required;
      if (type === "number") input.step = "1";
      if (key === "code" && plan) input.readOnly = true;
      add(grid, add(wrap, caption, input));
    }
    const actions = node("div", "form-actions");
    const submit = node("button", "btn btn-primary", plan ? "ذخیره تغییرات" : "ساخت پلن"); submit.type = "submit";
    add(actions, submit, button("انصراف", "btn btn-ghost", () => panel.remove()));
    add(form, grid, actions);
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); submit.disabled = true;
      const fields = Object.fromEntries(new FormData(form));
      for (const key of ["traffic_gb", "duration_days", "price_toman", "sort_order"]) fields[key] = Number(fields[key]);
      try {
        await api(plan ? `/plans/${encodeURIComponent(plan.code)}` : "/plans", { method: plan ? "PUT" : "POST", body: JSON.stringify(fields) });
        toast("پلن ذخیره شد. پلن جدید تا زمان فعال‌سازی در بات پنهان می‌ماند.");
        await plans();
      } catch (error) { toast(error.message, true); submit.disabled = false; }
    });
    return add(panel, form);
  }
  async function plans() {
    const rows = await api("/plans");
    const actions = node("div", "section-title");
    add(actions, node("h2", "", `${n(rows.length)} پلن تعریف‌شده`), button("＋ پلن جدید", "btn btn-primary", () => {
      const existing = $("#plan-editor"); if (existing) existing.remove();
      const editor = planForm(); editor.id = "plan-editor"; root.prepend(editor); editor.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    const grid = node("div", "plans-grid");
    if (!rows.length) add(grid, empty("هنوز پلنی ساخته نشده است.", "◈"));
    for (const plan of rows) {
      const card = node("article", plan.is_active ? "plan-card is-active" : "plan-card");
      const top = node("div", "plan-card-top");
      add(top, node("span", "plan-emoji", plan.emoji), statusBadge(plan.is_active ? "active" : "suspended"));
      const meta = node("div", "plan-meta");
      add(meta, node("span", "", `📶 ${n(plan.traffic_gb)} گیگ`), node("span", "", `🗓 ${n(plan.duration_days)} روز`));
      const actionRow = node("div", "plan-actions");
      add(actionRow, button("ویرایش", "btn btn-quiet btn-small", () => {
        const existing = $("#plan-editor"); if (existing) existing.remove();
        const editor = planForm(plan); editor.id = "plan-editor"; root.prepend(editor); editor.scrollIntoView({ behavior: "smooth", block: "start" });
      }), button(plan.is_active ? "غیرفعال‌سازی" : "فعال‌سازی", plan.is_active ? "btn btn-danger btn-small" : "btn btn-primary btn-small", async () => {
        if (plan.is_active && !window.confirm(`پلن «${plan.title}» از فهرست خرید بات پنهان شود؟`)) return;
        try { await api(`/plans/${encodeURIComponent(plan.code)}/active`, { method: "PATCH", body: JSON.stringify({ active: !plan.is_active }) }); toast("وضعیت پلن به‌روز شد."); await plans(); }
        catch (error) { toast(error.message, true); }
      }));
      add(card, top, node("div", "plan-code", plan.code), node("h3", "", plan.title),
        node("div", "plan-price", toman(plan.price_toman)), meta, actionRow);
      grid.append(card);
    }
    root.replaceChildren(actions, grid, add(node("div", "notice"),
      node("strong", "", "نکتهٔ فروش: "),
      node("span", "", "فعال بودن پلن فقط آن را در فهرست بات نشان می‌دهد؛ پرداخت و تحویل سرویس تا آماده شدن Xray فعال نمی‌شود.")));
  }
  async function pricing() {
    const data = await api("/pricing");
    const notice = node("div", "notice");
    add(notice, node("strong", "", "مدل، نه تضمین سود: "),
      node("span", "", "فرض می‌کند همهٔ مشتریان هدف همان پلن را می‌خرند و تمام حجم را مصرف می‌کنند. گیگابایتِ سهمیهٔ سرور اعشاری است؛ حجم پلن‌ها گیبی‌بایت (۱۰۲۴³ بایت). هزینهٔ جذب، پشتیبانی، مالیات و کارمزد واقعی جز ذخیرهٔ درصدی نیست."));
    const panel = node("div", "panel form-panel");
    add(panel, node("h2", "", "فرض‌های قابل‌ویرایش"),
      node("p", "", "مبلغ‌ها را به تومان وارد کن. ذخیرهٔ این فرم قیمت پلن‌های فروش را خودکار تغییر نمی‌دهد."));
    const form = node("form");
    const grid = node("div", "form-grid");
    const specs = [
      ["period_days", "طول دوره (روز)"],
      ["daily_server_cost_toman", "هزینهٔ روزانهٔ سرور (تومان)"],
      ["included_traffic_gb", "ترافیک همراه سرور (GB اعشاری)"],
      ["overage_cost_toman_per_gb", "هر GB اضافه (تومان)"],
      ["target_customers", "مشتری هدف در دوره"],
      ["contingency_percent", "ذخیرهٔ هزینه (%)"],
      ["target_margin_percent", "حاشیهٔ هدف (%)"],
    ];
    for (const [key, label] of specs) {
      const wrap = node("div"); const caption = node("label", "", label);
      const input = node("input", "field"); input.name = key; input.type = "number";
      input.step = "1"; input.required = true;
      input.value = data.assumptions ? String(data.assumptions[key]) : "";
      caption.htmlFor = `pricing-${key}`; input.id = `pricing-${key}`;
      add(grid, add(wrap, caption, input));
    }
    const submit = node("button", "btn btn-primary", "ذخیرهٔ فرض‌ها"); submit.type = "submit";
    add(form, grid, add(node("div", "form-actions"), submit));
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); submit.disabled = true;
      const fields = Object.fromEntries(new FormData(form));
      for (const key of Object.keys(fields)) fields[key] = Number(fields[key]);
      try {
        await api("/pricing", { method: "PUT", body: JSON.stringify(fields) });
        toast("فرض‌های قیمت‌گذاری ذخیره شد."); await pricing();
      } catch (error) { toast(error.message, true); submit.disabled = false; }
    });
    panel.append(form);
    if (!data.assumptions) { root.replaceChildren(notice, panel); return; }
    const byCode = new Map(data.plans.map(plan => [plan.code, plan]));
    const projections = data.projections;
    const box = table([
      ["پلن", row => `${byCode.get(row.plan_code)?.emoji || "◈"} ${byCode.get(row.plan_code)?.title || row.plan_code}`],
      ["قیمت فعلی", row => toman(byCode.get(row.plan_code)?.price_toman || 0)],
      ["مازاد محاسبه‌شده", row => `${n(row.billable_overage_gb)} GB`],
      ["هزینه با ذخیره", row => toman(row.cost_with_contingency_rial / 10)],
      ["ماندهٔ سناریو", row => node("span", row.contribution_rial >= 0 ? "badge green" : "badge red", toman(row.contribution_rial / 10))],
      ["حاشیهٔ سناریو", row => `${n(row.contribution_margin_basis_points / 100)}٪`],
      ["حداقل برای حاشیهٔ هدف", row => toman(row.minimum_price_rial_for_target_margin / 10)],
    ], projections, "پلنی با مدت برابر با دورهٔ مدل پیدا نشد.");
    root.replaceChildren(notice, panel,
      heading(`سناریوی ${n(data.assumptions.target_customers)} مشتری با مصرف کامل`, "ماندهٔ سناریو پس از هزینهٔ سرور، اضافه‌ترافیک و ذخیره؛ سود خالص نیست"), box);
  }

  async function users() {
    const query = state.userQuery;
    const rows = await api(`/users?q=${encodeURIComponent(query)}&offset=${state.offsets.users}`);
    const toolbar = node("div", "table-toolbar");
    const search = node("input", "field search"); search.type = "search"; search.placeholder = "جست‌وجوی نام، یوزرنیم یا شناسه…"; search.value = query; search.setAttribute("aria-label", "جست‌وجوی کاربران");
    let timer;
    search.addEventListener("input", () => { window.clearTimeout(timer); timer = window.setTimeout(() => { state.userQuery = search.value.trim(); state.offsets.users = 0; users().catch(fail); }, 330); });
    add(toolbar, node("strong", "", "فهرست کاربران"), search);
    const box = table([
      ["کاربر", row => row.display_name], ["شناسهٔ تلگرام", row => node("span", "mono", row.telegram_id)],
      ["نام کاربری", row => row.username ? `@${row.username}` : "—"],
      ["سفارش", row => n(row.subscriptions)], ["عضویت", row => date(row.created_at)],
    ], rows, "کاربری با این مشخصات پیدا نشد.");
    box.prepend(toolbar);
    root.replaceChildren(paged(box, "users", rows, () => users().catch(fail)));
  }
  async function orders() {
    const rows = await api(`/orders?offset=${state.offsets.orders}`);
    const box = table([
      ["کد سفارش", row => node("span", "mono", shortId(row.id))],
      ["کاربر", row => node("span", "mono", row.telegram_id)],
      ["پلن", row => row.plan_code], ["مبلغ", row => toman(row.price_rial / 10)],
      ["وضعیت", row => statusBadge(row.status)], ["پرداخت", row => statusBadge(row.payment_status)],
      ["مصرف", row => `${gib(row.traffic_used_bytes)} / ${gib(row.traffic_limit_bytes)}`],
      ["ثبت", row => date(row.created_at)],
    ], rows, "هنوز سفارشی ثبت نشده است.");
    root.replaceChildren(heading("آخرین سفارش‌ها", "وضعیت پرداخت با فعال‌سازی سرویس یکسان نیست"),
      paged(box, "orders", rows, () => orders().catch(fail)));
  }
  async function payments() {
    const rows = await api(`/payments?offset=${state.offsets.payments}`);
    const notice = node("div", "notice");
    add(notice, node("strong", "", "تأیید پرداخت از KPay: "),
      node("span", "", "رسید یا تصویر به‌تنهایی تأیید نیست. این پنل دکمهٔ تغییر دستی وضعیت تراکنش ندارد."));
    const box = table([
      ["سفارش", row => node("span", "mono", shortId(row.order_id))],
      ["مبلغ", row => toman(row.amount_rial / 10)],
      ["وضعیت", row => statusBadge(row.status)],
      ["ساخته‌شده", row => date(row.created_at)], ["تأییدشده", row => date(row.paid_at)],
    ], rows, "هنوز تراکنشی به سفارشی متصل نشده است.");
    root.replaceChildren(notice, paged(box, "payments", rows, () => payments().catch(fail)));
  }
  async function branding() {
    const data = await api("/branding");
    const notice = node("div", "notice");
    add(notice, node("strong", "", "هماهنگی با تلگرام: "), node("span", "", "تغییرات اینجا در MySQL ذخیره می‌شود؛ پروفایل رسمی بات هنگام شروع مجدد بات همگام می‌شود."));
    const panel = node("div", "panel form-panel");
    add(panel, node("h2", "", "متن‌های هویت بات"), node("p", "", "توضیح کوتاه و کامل مطابق محدودیت‌های تلگرام اعتبارسنجی می‌شوند."));
    for (const [key, label, maximum] of [["name", "نام بات", 64], ["short_description", "توضیح کوتاه", 120], ["description", "توضیح کامل", 512]]) {
      const form = node("form");
      const caption = node("label", "", `${label} · حداکثر ${n(maximum)} نویسه`);
      const input = key === "description" ? node("textarea", "field") : node("input", "field");
      input.name = "value"; input.id = `branding-${key}`; input.maxLength = maximum; input.required = true; input.value = data[key]; caption.htmlFor = input.id;
      const actions = node("div", "form-actions");
      const submit = node("button", "btn btn-primary btn-small", `ذخیرهٔ ${label}`); submit.type = "submit";
      add(actions, submit);
      add(form, caption, input, actions);
      form.addEventListener("submit", async (event) => {
        event.preventDefault(); submit.disabled = true;
        try { await api(`/branding/${key}`, { method: "PATCH", body: JSON.stringify({ value: input.value }) }); toast(`${label} ذخیره شد.`); }
        catch (error) { toast(error.message, true); }
        finally { submit.disabled = false; }
      });
      panel.append(form);
    }
    root.replaceChildren(notice, panel);
  }
  async function system() {
    const data = await api("/readiness");
    const panel = node("div", "card");
    add(panel, node("h3", "", "چک‌لیست عملیاتی"));
    const items = [
      ["کالبک پرداخت", "مسیر API برای بررسی KPay تنظیم شده است", data.callback_configured],
      ["API اشتراک", "لینک عمومی و سرویس اشتراک پیکربندی شده‌اند", data.subscription_api_configured],
      ["صدور کانفیگ روی Xray", "کاربر باید واقعاً روی نود ساخته شود", data.xray_provisioning_connected],
      ["مصرف زنده و سقف حجم", "شمارنده و قطع دسترسی پس از اتمام حجم", data.live_usage_connected],
      ["شروع فروش", "پرداخت و تحویل به مشتریان واقعی", data.sales_enabled],
    ];
    for (const [title, subtitle, ready] of items) {
      const row = node("div", "list-row"); const text = node("div");
      add(text, node("strong", "", title), node("small", "", subtitle));
      add(row, text, node("span", ready ? "status-dot" : "status-dot off")); panel.append(row);
    }
    const notice = node("div", "notice");
    add(notice, node("strong", "", "قبل از فروش: "), node("span", "", "اتصال واقعی از شبکه‌های ایران، تمام‌شدن حجم، انقضا، بازیابی نسخهٔ پشتیبان و تحویل پس از پرداخت باید با آزمون عملی تأیید شوند."));
    const security = node("div", "panel form-panel");
    add(security, node("h2", "", "🔐 امنیت حساب"),
      node("p", "", "رمز فعلی را تأیید کن و یک رمز اختصاصیِ حداقل ۱۲ نویسه‌ای بگذار. همهٔ نشست‌ها خارج می‌شوند."));
    const form = node("form");
    const grid = node("div", "form-grid");
    const inputs = [];
    for (const [key, label, autocomplete] of [
      ["current_password", "رمز فعلی", "current-password"],
      ["new_password", "رمز جدید", "new-password"],
      ["repeat_password", "تکرار رمز جدید", "new-password"],
    ]) {
      const wrap = node("div");
      const input = node("input", "field"); input.type = "password"; input.name = key;
      input.required = true; input.autocomplete = autocomplete; input.minLength = key === "current_password" ? 8 : 12;
      add(grid, add(wrap, node("label", "", label), input)); inputs.push(input);
    }
    const submit = node("button", "btn btn-primary", "تغییر رمز و خروج"); submit.type = "submit";
    add(form, grid, add(node("div", "form-actions"), submit));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (inputs[1].value !== inputs[2].value) { toast("تکرار رمز جدید یکسان نیست.", true); return; }
      submit.disabled = true;
      try {
        await api("/password", { method: "POST", body: JSON.stringify({ current_password: inputs[0].value, new_password: inputs[1].value }) });
        showLogin(); toast("رمز تغییر کرد؛ با رمز جدید وارد شو.");
      } catch (error) { toast(error.message, true); }
      finally { submit.disabled = false; inputs.forEach(input => { input.value = ""; }); }
    });
    root.replaceChildren(panel, notice, add(security, form));
  }
  const renderers = { overview, plans, pricing, users, orders, payments, branding, system };
  function fail(error) { toast(error instanceof Error ? error.message : "خطای ناشناخته", true); }
  async function setView(view) {
    if (!renderers[view]) return;
    state.view = view;
    for (const item of document.querySelectorAll(".nav-item")) item.classList.toggle("active", item.dataset.view === view);
    $("#path-title").textContent = titles[view][0];
    $("#page-title").textContent = titles[view][0];
    $("#page-subtitle").textContent = titles[view][1];
    $(".page-heading .eyebrow").textContent = `PAPILIO / ${titles[view][2]}`;
    root.replaceChildren(empty("در حال بارگذاری…", "◌"));
    try { await renderers[view](); }
    catch (error) { root.replaceChildren(empty("دریافت اطلاعات ممکن نشد. دوباره تلاش کن.", "⚠")); fail(error); }
  }
  for (const item of document.querySelectorAll(".nav-item")) item.addEventListener("click", () => setView(item.dataset.view));
  $("#refresh").addEventListener("click", () => setView(state.view));
  $("#logout").addEventListener("click", async () => {
    try { await api("/logout", { method: "POST", body: "{}" }); } catch (error) { fail(error); }
    showLogin();
  });
  $("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = $("#login-submit"); submit.disabled = true;
    $("#login-message").textContent = "";
    try {
      const session = await api("/login", { method: "POST", body: JSON.stringify({ username: $("#login-username").value.trim(), password: $("#login-password").value }) });
      showWorkspace(session);
    } catch (error) { $("#login-message").textContent = error.message; }
    finally { submit.disabled = false; }
  });
  $("#today").textContent = new Intl.DateTimeFormat("fa-IR", { dateStyle: "full" }).format(new Date());
  api("/me").then(showWorkspace).catch(() => showLogin());
})();
