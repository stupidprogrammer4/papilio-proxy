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
const customerPage = (data, pageNumber) => ({
  items: data,
  count: 3,
  page: pageNumber,
  page_size: 2,
});
const nodePage = (data, pageNumber) => ({
  items: data,
  count: 3,
  page: pageNumber,
  page_size: 2,
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
      scopes: ["customers:read", "nodes:read"],
      csrf_token: "controlled",
    });
  }
  if (path === "/v1/admin/branding") {
    return reply(route, { data: { brand_title: "Dashboard fixture" } });
  }
  if (path === "/v1/customer-accounts") {
    const suffix = current === 1 ? "first" : "second";
    return reply(route, customerPage([{
      id: `00000000-0000-4000-8000-00000000000${current}`,
      owner_id: 1,
      name: `${search || "All"} customer ${suffix}`,
    }], current));
  }
  if (path === "/v1/nodes") {
    const suffix = current === 1 ? "first" : "second";
    return reply(route, nodePage([{
      id: `00000000-0000-4000-8000-00000000001${current}`,
      deployment_id: "00000000-0000-4000-8000-000000000099",
      owner_id: 1,
      name: `${search || "All"} server ${suffix}`,
      endpoint_url: "https://edge.example.test:443",
      runtime: {},
      certificate_policy: {},
      credentials_ready: true,
      certificate_expires_at: null,
      last_reachable: true,
      last_checked_at: null,
      last_error_code: null,
      uptime_seconds: null,
      last_operation_id: null,
      configuration_revision: 1,
    }], current));
  }
    return reply(route, customerPage([], 1));
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
    return url.pathname.endsWith("/v1/customer-accounts")
      && url.searchParams.get("q") === "alice"
      && url.searchParams.get("page") === "2";
  });
  await customerPanel.locator(".pager button").last().click();
  await customerPage;
  await page.getByText("alice customer second", { exact: true }).waitFor();

  const serverPage = page.waitForRequest(request => {
    const url = new URL(request.url());
    return url.pathname.endsWith("/v1/nodes")
      && url.searchParams.get("q") === "west"
      && url.searchParams.get("page") === "2";
  });
  await serverPanel.locator(".pager button").last().click();
  await serverPage;
  await page.getByText("west server second", { exact: true }).waitFor();
  assert.equal(requests.filter(row => row.method !== "GET").length, 0);
  assert(requests.some(row => row.path === "/v1/customer-accounts"));
  assert(requests.some(row => row.path === "/v1/nodes"));
  assert.deepEqual(errors, []);
  console.log("PASS: dashboard shows independent customer/server lists with search and query-preserving pagination");
} catch (error) {
  console.error(JSON.stringify({ requests, errors, text: await page.locator("body").innerText() }));
  throw error;
} finally {
  await page.close();
  await browser.close();
}
