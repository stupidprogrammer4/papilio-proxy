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
  console.log("Real setup, CSRF login, authenticated status, outbox submission and session reload passed.");
} finally {
  await browser.close();
}
