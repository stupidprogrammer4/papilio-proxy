import assert from "node:assert/strict";
import { fileURLToPath, pathToFileURL } from "node:url";

// Exercise the actual Vue app with controlled HTTP responses, without writes.
const modulePath = process.env.PLAYWRIGHT_MODULE;
const origin = process.env.PANEL_ORIGIN;
const apiModuleUrl = "/@fs" + fileURLToPath(new URL("../packages/api/src/index.ts", import.meta.url));
if (!modulePath || !origin) throw new Error("Set PLAYWRIGHT_MODULE and PANEL_ORIGIN");
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE });
const page = await browser.newPage();
const pageErrors = [], cancellations = [], held = new Map(), observed = [];
const customer = (name, id = 101) => ({ id, display_name: name, telegram_id: null, is_active: true, services_enabled: true, renewals_enabled: true, service_hold_pending: false, service_hold_clock: null });
const plan = title => ({ id: 1, code: "test-plan", title, price_rial: 1000, quota_bytes: 1024, duration_days: 30, sort_order: 0, is_active: true, group_id: null, quota_policy: null, fulfillment: null, ip_limit: null });
const paged = (data, current = 1) => ({ data, meta: { pager: { total_items: 2, total_pages: 2, current_page: current, per_page: 1, has_prev: current > 1, has_next: current < 2 } } });
const reply = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
page.on("pageerror", error => pageErrors.push(error.message));
page.on("requestfailed", request => cancellations.push(request.url()));
await page.route(url => url.pathname.startsWith("/api/"), async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname.slice(4), q = url.searchParams.get("q");
  assert.equal(request.method(), "GET", "This check must never mutate data");
  observed.push(path + url.search);
  if (q?.startsWith("hold-")) { held.set(q, route); return; }
  if (path === "/v1/admin/auth/me") return reply(route, { username: "browser-fixture", scopes: ["*"], csrf_token: "controlled-browser-token" });
  if (path === "/v1/admin/branding") return reply(route, { data: { brand_title: "Browser fixture" } });
  if (path === "/v1/admin/customers/creation-policy") return reply(route, { data: { is_active: true, services_enabled: true, renewals_enabled: true } });
  if (path === "/v1/admin/customers") return reply(route, paged([customer(q === "latest-customers" ? "Latest customer" : "Initial customer", q === "latest-customers" ? 102 : 101)], Number(url.searchParams.get("page") ?? 1)));
  if (path === "/v1/plans") return reply(route, paged([plan(q === "latest-plans" ? "Latest plan" : "Initial plan")], Number(url.searchParams.get("page") ?? 1)));
  if (path.startsWith("/v1/admin/payments/wallets/")) return reply(route, { data: { customer_id: 101, balance_rial: 10000 } });
  if (path.endsWith("/trial-availability")) return reply(route, { data: { policy: { enabled: false, duration_days: 1, quota_bytes: 1024 }, eligible: false, reason: "trial_disabled", claims: 0, next_claim_at: null } });
  return reply(route, paged([]));
});

async function waitHeld(name) {
  await page.waitForRequest(request => new URL(request.url()).searchParams.get("q") === name);
}

async function rendered() { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }

try {
  await page.goto(origin + "/customers");
  await page.getByRole("row").filter({ hasText: "Initial customer" }).click();
  await page.getByRole("heading", { name: "Purchase with wallet" }).waitFor();
  await page.getByLabel("Customer display name").fill("Retained profile draft");
  const customers = page.getByLabel("Search customers"), plans = page.getByLabel("Find a plan");
  const oldCustomers = waitHeld("hold-customer-cancel");
  await customers.fill("hold-customer-cancel"); await oldCustomers;
  await customers.fill("latest-customers");
  await page.getByRole("row").filter({ hasText: "Latest customer" }).waitFor();
  assert(cancellations.some(url => url.includes("hold-customer-cancel")), "Superseded customer request was not canceled");
  await held.get("hold-customer-cancel").abort().catch(() => {});
  assert.equal(await page.getByLabel("Customer display name").inputValue(), "Retained profile draft", "Search discarded the selected customer draft");

  const oldPlans = waitHeld("hold-plan-cancel");
  await plans.fill("hold-plan-cancel"); await oldPlans;
  await plans.fill("latest-plans");
  await page.getByRole("row").filter({ hasText: "Latest plan" }).waitFor();
  assert(cancellations.some(url => url.includes("hold-plan-cancel")), "Superseded plan request was not canceled");
  await held.get("hold-plan-cancel").abort().catch(() => {});

  // A transport that delivers after cancellation still must not replace newer rows.
  await page.evaluate(() => {
    const native = window.fetch.bind(window);
    window.fetch = (input, options) => String(input).includes("hold-reversed-") ? native(input, { ...options, signal: undefined }) : native(input, options);
  });
  const delayedCustomers = waitHeld("hold-reversed-customers");
  await customers.fill("hold-reversed-customers"); await delayedCustomers;
  await customers.fill("latest-customers");
  await page.getByRole("row").filter({ hasText: "Latest customer" }).waitFor();
  const oldCustomerResponse = page.waitForResponse(response => response.url().includes("hold-reversed-customers"));
  await reply(held.get("hold-reversed-customers"), paged([customer("Obsolete customer", 103)]));
  await (await oldCustomerResponse).finished(); await rendered();
  assert.equal(await page.getByRole("row").filter({ hasText: "Obsolete customer" }).count(), 0);

  const delayedPlans = waitHeld("hold-reversed-plans");
  await plans.fill("hold-reversed-plans"); await delayedPlans;
  await plans.fill("latest-plans");
  await page.getByRole("row").filter({ hasText: "Latest plan" }).waitFor();
  const oldPlanResponse = page.waitForResponse(response => response.url().includes("hold-reversed-plans"));
  await reply(held.get("hold-reversed-plans"), paged([plan("Obsolete plan")])); await (await oldPlanResponse).finished(); await rendered();
  assert.equal(await page.getByRole("row").filter({ hasText: "Obsolete plan" }).count(), 0);
  assert.equal(await page.getByLabel("Customer display name").inputValue(), "Retained profile draft");
  assert.equal(await page.locator(".message.error").count(), 0, "Canceled reads displayed an error");

  const customerTable = customers.locator("xpath=ancestor::div[contains(concat(' ',normalize-space(@class),' '),' card ')][1]");
  const nextPage = page.waitForResponse(response => response.url().includes("/v1/admin/customers?") && new URL(response.url()).searchParams.get("page") === "2");
  await customerTable.locator(".pager button").last().click(); await nextPage;
  assert(observed.some(path => path.includes("q=latest-customers&page=2")), "Customer paging lost its search");

  const apiRead = waitHeld("hold-api-abort");
  await page.evaluate(async apiModuleUrl => {
    const { request } = await import(apiModuleUrl);
    window.__apiRead = new AbortController();
    void request("/v1/admin/customers?q=hold-api-abort", "GET", undefined, { signal: window.__apiRead.signal }).catch(error => { window.__apiError = error.name; });
  }, apiModuleUrl);
  await apiRead;
  await page.evaluate(() => window.__apiRead.abort());
  await page.waitForFunction(() => window.__apiError === "AbortError");
  await held.get("hold-api-abort").abort().catch(() => {});

  const unmounted = waitHeld("hold-plan-unmount");
  await plans.fill("hold-plan-unmount"); await unmounted;
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
  assert(cancellations.some(url => url.includes("hold-plan-unmount")), "Leaving the page did not cancel its pending request");
  await held.get("hold-plan-unmount").abort().catch(() => {});
  assert.deepEqual(pageErrors, []);
  console.log("PASS: customer/plan cancellation, reversed responses, retained selected draft, no cancellation error, full paging, shared AbortError, unmount cancellation");
} catch (error) {
  console.error(JSON.stringify({ url: page.url(), pageErrors, observed, text: await page.locator("body").innerText() }));
  throw error;
} finally {
  await page.close();
  await browser.close();
}
