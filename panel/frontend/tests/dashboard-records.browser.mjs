import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROMIUM_EXECUTABLE,
});
const page = await browser.newPage();
const requests = [];
const errors = [];
const reply = (route, body) => route.fulfill({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});
const paged = (data, pageNumber) => ({
  data,
  meta: {
    pager: {
      total_items: 3,
      total_pages: 2,
      current_page: pageNumber,
      per_page: 2,
      has_prev: pageNumber > 1,
      has_next: pageNumber < 2,
    },
  },
});

page.on("pageerror", error => errors.push(error.message));
await page.route(url => url.pathname.startsWith("/api/"), async route => {
  const request = route.request();
  const url = new URL(request.url());
  const path = url.pathname.slice(4);
  const search = url.searchParams.get("q") ?? "";
  const current = Number(url.searchParams.get("page") ?? 1);
  requests.push({ path, search, current, method: request.method() });
  assert.equal(request.method(), "GET", "Dashboard lists must remain read-only");

  if (path === "/v1/admin/auth/me") {
    return reply(route, {
      username: "dashboard-fixture",
      scopes: ["customers:read", "network:read"],
      csrf_token: "controlled",
    });
  }
  if (path === "/v1/admin/branding") {
    return reply(route, { data: { brand_title: "Dashboard fixture" } });
  }
  if (path === "/v1/admin/customers") {
    const suffix = current === 1 ? "first" : "second";
    return reply(route, paged([{
      id: current,
      display_name: `${search || "All"} customer ${suffix}`,
      telegram_id: null,
      is_active: true,
    }], current));
  }
  if (path === "/v1/admin/network/nodes") {
    const suffix = current === 1 ? "first" : "second";
    return reply(route, paged([{
      id: current + 10,
      code: `node-${current}`,
      label: `${search || "All"} server ${suffix}`,
      public_host: "edge.example.test",
      public_port: 443,
      protocol: "vless_reality",
      is_enabled: true,
    }], current));
  }
  return reply(route, paged([], 1));
});

try {
  await page.goto(process.env.PANEL_ORIGIN + "/");
  await page.getByRole("heading", { name: "Customers", exact: true }).waitFor();
  await page.getByRole("heading", { name: "Servers", exact: true }).waitFor();
  await page.getByText("All customer first", { exact: true }).waitFor();
  await page.getByText("All server first", { exact: true }).waitFor();

  const customerSearch = page.getByLabel("Search customers");
  const serverSearch = page.getByLabel("Search servers");
  await customerSearch.fill("alice");
  await page.getByText("alice customer first", { exact: true }).waitFor();
  await serverSearch.fill("west");
  await page.getByText("west server first", { exact: true }).waitFor();

  const customerPanel = page.locator(".record-panel").filter({
    has: page.getByRole("heading", { name: "Customers", exact: true }),
  });
  const serverPanel = page.locator(".record-panel").filter({
    has: page.getByRole("heading", { name: "Servers", exact: true }),
  });
  const customerPage = page.waitForRequest(request => {
    const url = new URL(request.url());
    return url.pathname.endsWith("/v1/admin/customers")
      && url.searchParams.get("q") === "alice"
      && url.searchParams.get("page") === "2";
  });
  await customerPanel.locator(".pager button").last().click();
  await customerPage;
  await page.getByText("alice customer second", { exact: true }).waitFor();

  const serverPage = page.waitForRequest(request => {
    const url = new URL(request.url());
    return url.pathname.endsWith("/v1/admin/network/nodes")
      && url.searchParams.get("q") === "west"
      && url.searchParams.get("page") === "2";
  });
  await serverPanel.locator(".pager button").last().click();
  await serverPage;
  await page.getByText("west server second", { exact: true }).waitFor();
  assert.equal(requests.filter(row => row.method !== "GET").length, 0);
  assert.deepEqual(errors, []);
  console.log("PASS: dashboard shows independent customer/server lists with search and query-preserving pagination");
} catch (error) {
  console.error(JSON.stringify({ requests, errors, text: await page.locator("body").innerText() }));
  throw error;
} finally {
  await page.close();
  await browser.close();
}
