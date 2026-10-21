import assert from "node:assert/strict";
import { chromium } from "playwright";
import { expect } from "playwright/test";

const base = process.env.PAPILIO_BROWSER_URL;
const token = process.env.PAPILIO_SETUP_TOKEN;
const username = process.env.PAPILIO_BROWSER_USERNAME;
const password = process.env.PAPILIO_BROWSER_PASSWORD;
assert(base && token && username && password, "Provide the isolated runtime and setup credentials.");
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${base}/setup`);
  await page.getByTestId("setup-token").fill(token);
  await page.getByTestId("setup-username").fill(username);
  await page.getByTestId("setup-password").fill("123");
  const [rejectedSetup] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/setup/owner") && response.request().method() === "POST"),
    page.getByTestId("setup-submit").click(),
  ]);
  assert.equal(rejectedSetup.status(), 400);
  assert.match(await page.getByRole("alert").innerText(), /12/);
  await page.getByTestId("setup-password").fill(password);
  await page.getByTestId("setup-submit").click();
  await page.waitForURL(`${base}/login`);
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.locator('form button[type="submit"], form button.btn').click();
  await page.waitForURL(`${base}/`);
  await page.getByTestId("system-status").waitFor();
  assert.match(await page.getByTestId("system-status").innerText(), /base01|browser/);
  const schedule = page.getByTestId("schedule-outbox");
  await schedule.locator('input[type="number"]').fill("2");
  const [savedSchedule] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/system/schedules/outbox") && response.request().method() === "PUT"),
    schedule.getByRole("button", { name: "Save", exact: true }).click(),
  ]);
  assert.equal(savedSchedule.status(), 200);
  assert.equal((await savedSchedule.json()).interval_seconds, 2);
  const [submission] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/system/probes") && response.request().method() === "POST"),
    page.getByTestId("probe-io").click(),
  ]);
  assert.equal(submission.status(), 202);
  const operation = await submission.json();
  assert.equal(operation.kind, "io");
  await page.getByTestId("probe-operation").waitFor();
  await expect.poll(async () => {
    const response = await page.request.get(`${base}/api/v1/system/operations/${operation.id}`);
    const result = await response.json();
    return result.status;
  }, { timeout: 35000, intervals: [100, 250, 500] }).toBe("succeeded");
  const [operationRead] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith(`/api/v1/system/operations/${operation.id}`)),
    page.getByRole("button", { name: "Refresh", exact: true }).click(),
  ]);
  assert.equal((await operationRead.json()).status, "succeeded");
  try {
    await page.getByTestId("probe-operation").getByText("Succeeded", { exact: false }).waitFor();
  } catch (error) {
    console.error("Rendered operation:", await page.getByTestId("probe-operation").innerText());
    throw error;
  }
  await page.reload();
  await page.getByTestId("system-status").waitFor();
  assert.equal(new URL(page.url()).pathname, "/");
  await page.getByRole("link", { name: "Nodes", exact: true }).click();
  await page.waitForURL(`${base}/nodes`);
  await page.getByTestId("node-name").fill("browser-node");
  await page.getByTestId("node-endpoint").fill("https://127.0.0.1:19443");
  await page.getByTestId("node-advanced").click();
  await page.getByTestId("node-request_timeout_seconds").fill("7");
  const [registered] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/nodes") && response.request().method() === "POST"),
    page.getByTestId("node-create").click(),
  ]);
  assert.equal(registered.status(), 202);
  const registration = await registered.json();
  assert.equal(registration.node.runtime.request_timeout_seconds, 7);
  await expect.poll(async () => (await (await page.request.get(`${base}/api/v1/nodes/${registration.node.id}/operations/${registration.operation.id}`)).json()).status,
    { timeout: 35000, intervals: [100, 250, 500] }).toBe("succeeded");
  await page.getByTestId("node-refresh").click();
  const detail = page.getByTestId("node-detail");
  await expect(detail).toContainText("Succeeded");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("node-bootstrap").click(),
  ]);
  assert.equal(download.suggestedFilename(), `papilio-node-${registration.node.id}.zip`);
  await page.getByTestId("node-search").fill("browser-node");
  await page.getByTestId("node-search-submit").click();
  await expect(page.getByTestId("node-list")).toContainText("browser-node");
  await page.reload();
  await expect(page.getByTestId("node-list")).toContainText("browser-node");
  await page.getByTestId("node-row").click();
  await expect(page.getByTestId("node-detail")).toContainText("https://127.0.0.1:19443");
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  const deliverySchedule = page.getByTestId("schedule-node-outbox");
  await deliverySchedule.locator('input[type="number"]').fill("9");
  await deliverySchedule.locator('input[type="checkbox"]').uncheck();
  const [paused] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/system/schedules/node-outbox") && response.request().method() === "PUT"),
    deliverySchedule.getByRole("button", { name: "Save", exact: true }).click(),
  ]);
  assert.equal(paused.status(), 200);
  assert.equal((await paused.json()).enabled, false);
  console.log("Real node registration, CPU credential issuance, private download and persisted panel state passed.");
  console.log("Real setup, CSRF login, authenticated status, outbox submission and session reload passed.");
} finally {
  await browser.close();
}
