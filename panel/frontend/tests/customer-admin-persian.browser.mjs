import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE });
const page = await browser.newPage();
const customer = {
  id: 41,
  display_name: "آزمایشی",
  telegram_id: null,
  is_active: true,
  services_enabled: true,
  renewals_enabled: true,
  service_hold_pending: false,
  service_hold_clock: null,
};
const reply = (route, data) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });

try {
  await page.addInitScript(() => localStorage.setItem("papilio.locale", "fa"));
  await page.route(url => url.pathname.startsWith("/api/"), route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.slice(4);
    assert.equal(request.method(), "GET");
    if (path === "/v1/admin/auth/me") {
      return reply(route, { username: "reviewer", scopes: ["*"], csrf_token: "controlled" });
    }
    if (path === "/v1/admin/branding") return reply(route, { data: { brand_title: "Papilio" } });
    if (path === "/v1/admin/customers/creation-policy") {
      return reply(route, { data: { is_active: true, services_enabled: true, renewals_enabled: true } });
    }
    if (path === "/v1/admin/customers") {
      return reply(route, {
        data: [customer],
        meta: { pager: { total_items: 1, total_pages: 1, current_page: 1, per_page: 20 } },
      });
    }
    if (path === "/v1/admin/payments/wallets/41") return reply(route, { data: { customer_id: 41, balance_rial: 500000 } });
    if (path === "/v1/plans") {
      return reply(route, {
        data: [],
        meta: { pager: { total_items: 0, total_pages: 1, current_page: 1, per_page: 20 } },
      });
    }
    if (path.endsWith("/trial-availability")) {
      return reply(route, {
        data: {
          policy: { enabled: false, duration_days: 1, quota_bytes: 1024 },
          eligible: false,
          reason: "trial_disabled",
          claims: 0,
          next_claim_at: null,
        },
      });
    }
    return reply(route, {
      data: [],
      meta: { pager: { total_items: 0, total_pages: 1, current_page: 1, per_page: 20 } },
    });
  });
  await page.goto(process.env.PANEL_ORIGIN + "/customers");
  await page.getByRole("row").filter({ hasText: "آزمایشی" }).click();
  await page.getByRole("heading", { name: "خرید با کیف پول", exact: true }).waitFor();
  const body = await page.locator("body").innerText();
  for (const phrase of ["نام نمایشی مشتری", "ذخیرهٔ نام", "اشتراک‌های مشتری", "موجودی کیف پول", "تومان", "مبلغ شارژ (تومان)", "جست‌وجوی پلن", "تمدید خودکار با کیف پول", "خرید پلن انتخاب‌شده"]) {
    assert(body.includes(phrase), `Missing Persian customer workflow label: ${phrase}`);
  }
  for (const phrase of ["Customer display name", "Save name", "Customer subscriptions", "Wallet balance", "toman", "Top-up amount", "Purchase with wallet", "Automatic wallet renewal", "Purchase selected plan"]) {
    assert(!body.includes(phrase), `Untranslated customer workflow label: ${phrase}`);
  }
  await page.getByTestId("locale-selector").selectOption("en");
  await page.getByRole("heading", { name: "Purchase with wallet", exact: true }).waitFor();
  const englishBody = await page.locator("body").innerText();
  for (const phrase of ["Customer display name", "Save name", "Customer subscriptions", "Wallet balance", "Top-up amount (toman)", "Find a plan", "Automatic wallet renewal", "Purchase selected plan"]) {
    assert(englishBody.includes(phrase), `Missing English customer workflow label: ${phrase}`);
  }
  console.log("Customer account and wallet purchase workflow render in Persian and English.");
} catch (error) {
  console.error(await page.locator("body").innerText());
  throw error;
} finally {
  await browser.close();
}
