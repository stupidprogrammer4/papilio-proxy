// UI contract only: controlled HTTP, with real Vue forms and browser interactions.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const { expect } = await import("playwright/test");
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE });
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
page.setDefaultTimeout(5000);
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const definition = {
  node: { name: "Local node", endpoint_url: "https://local-node.papilio.internal:9443",
    runtime: { listen_address: "0.0.0.0:9443", xray_api_address: "127.0.0.1:10085", request_timeout_seconds: 15, read_header_timeout_seconds: 5, idle_timeout_seconds: 60, shutdown_timeout_seconds: 20, max_body_bytes: 1048576, max_grpc_reply_bytes: 16777216 },
    certificate_policy: { validity_seconds: 2592000, authority_validity_seconds: 31536000, backdate_seconds: 60 } },
  core_name: "Local Xray", inbound_tag: "vless", public_host: "vpn.example.test", public_port: 8444,
  default_user_level: 0, bind_address: "0.0.0.0", bind_port: 8443,
};
let signedIn = false, ownerPayload;
let record = { node_id: "d78ba217-1f87-4a15-b94b-cc39282c1a19", core_id: "2b3274a3-6052-4968-9d0a-02e26d719274", inbound_id: "dc6bd935-13a9-46e8-a804-2eb5d0984825", definition,
  delivery: { enabled: true, retry_interval_seconds: 1, max_attempts: 5, revision: "1" },
  operation: { id: "dfb1efec-8b85-476a-a2ab-a0b7c424bc81", request_key: "e58e6eaf-1b5b-444c-b0d2-702e15c4176e", status: "succeeded", attempts: "1", error_code: null, worker_pid: 123, due_at: "2026-10-24T10:00:00Z", lease_until: null, completed_at: "2026-10-24T10:00:00Z", timeout_seconds: 55 } };
await page.route(url => url.pathname.startsWith("/api/"), route => {
  const request = route.request(), path = new URL(request.url()).pathname.slice(4), method = request.method();
  const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  if (path === "/v1/admin/auth/me") return json(signedIn ? { id: 1, username: "local-ui-owner", role: "owner", scopes: ["*"], csrf_token: "ui-csrf" } : { detail: "Sign in" }, signedIn ? 200 : 401);
  if (path === "/v1/admin/auth/csrf") return json({ csrf_token: "ui-csrf" });
  if (path === "/v1/setup/local-node") return json({ available: true, definition, delivery: { enabled: true, retry_interval_seconds: 1, max_attempts: 5 } });
  if (path === "/v1/setup/owner" && method === "POST") { ownerPayload = request.postDataJSON(); signedIn = true; return json({ id: 1, username: ownerPayload.username }, 201); }
  if (path === "/v1/system/status") return json({ version: "test", environment: "sandbox", instance: "ui", database: true, cache: true, workers_ready: true, workers: [] });
  if (path === "/v1/system/schedules") return json([{ key: "local-node-outbox", enabled: true, interval_seconds: 1, changed_at: "2026-10-24T10:00:00Z" }]);
  if (path === "/v1/system/local-node") return json(record);
  if (path === "/v1/system/local-node/delivery" && method === "PUT") {
    const supplied = request.postDataJSON();
    if (supplied.expected_revision !== record.delivery.revision) return json({ detail: "Reload before saving." }, 409);
    record = { ...record, delivery: { enabled: supplied.enabled, retry_interval_seconds: supplied.retry_interval_seconds, max_attempts: supplied.max_attempts, revision: String(Number(record.delivery.revision) + 1) } };
    return json(record.delivery);
  }
  if (path === "/v1/system/local-node/operations" && method === "POST") {
    record = { ...record, operation: { ...record.operation, request_key: request.postDataJSON().request_key, status: "queued", attempts: "0" } };
    return json(record.operation, 202);
  }
  return json({ detail: "Unexpected UI request" }, 404);
});
try {
  await page.goto(`${process.env.PANEL_ORIGIN}/setup`);
  await expect(page.getByTestId("setup-local-enabled")).toBeChecked();
  await page.getByTestId("local-definition-advanced").click();
  await page.getByTestId("local-node-name").fill("Chosen local runtime");
  await page.getByTestId("local-idle_timeout_seconds").fill("71");
  await page.getByTestId("setup-token").fill("private-ui-token");
  await page.getByTestId("setup-username").fill("local-ui-owner");
  await page.getByTestId("setup-password").fill("isolated-ui-password-975!");
  await Promise.all([page.waitForResponse(r => r.url().endsWith("/api/v1/setup/owner")), page.getByTestId("setup-submit").click()]);
  assert.equal(ownerPayload.local_node.enabled, true);
  assert.equal(ownerPayload.local_node.definition.node.name, "Chosen local runtime");
  assert.equal(ownerPayload.local_node.definition.node.runtime.idle_timeout_seconds, 71);
  // A fresh page restores the scoped session supplied by the controlled server.
  await page.goto(`${process.env.PANEL_ORIGIN}/`);
  const panel = page.getByTestId("local-runtime");
  await expect(panel.getByTestId("local-delivery-enabled")).toBeChecked();
  await panel.getByTestId("local-delivery-enabled").uncheck();
  await panel.getByTestId("local-retry-interval").fill("7");
  await panel.getByTestId("local-max-attempts").fill("11");
  await panel.getByTestId("local-delivery-save").click();
  await expect(panel.getByTestId("local-delivery-save")).toBeEnabled();
  assert.equal(record.delivery.enabled, false);
  assert.equal(record.delivery.retry_interval_seconds, 7);
  await page.reload();
  await expect(panel.getByTestId("local-delivery-enabled")).not.toBeChecked();
  await expect(panel.getByTestId("local-retry-interval")).toHaveValue("7");
  record.delivery.revision = "3";
  await panel.getByTestId("local-retry-interval").fill("9");
  await panel.getByTestId("local-delivery-save").click();
  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(panel.getByTestId("local-retry-interval")).toHaveValue("9");
  await panel.getByTestId("local-runtime-refresh").click();
  await expect(panel.getByTestId("local-retry-interval")).toHaveValue("7");
  await panel.getByTestId("local-runtime-retry").click();
  await expect(panel.getByTestId("local-runtime-state")).toContainText("Queued");
  await page.getByTestId("locale-selector").selectOption("fa");
  await expect(panel.getByRole("heading")).toHaveText("نود همین سرور");
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  assert.deepEqual(errors, []);
} finally { await browser.close(); }
