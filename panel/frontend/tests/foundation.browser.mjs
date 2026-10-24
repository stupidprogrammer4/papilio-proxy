import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { writeFileSync } from "node:fs";
import { chromium } from "playwright";
import { expect } from "playwright/test";

const base = process.env.PAPILIO_BROWSER_URL;
const token = process.env.PAPILIO_SETUP_TOKEN;
const username = process.env.PAPILIO_BROWSER_USERNAME;
const password = process.env.PAPILIO_BROWSER_PASSWORD;
const insecureDomain = process.env.PAPILIO_BROWSER_INSECURE_DOMAIN === "true";
assert(base && token && username && password, "Provide the isolated runtime and setup credentials.");
const browser = await chromium.launch({ headless: true, args: insecureDomain ? ["--host-resolver-rules=MAP papilio-http.test 127.0.0.1", "--no-proxy-server"] : [] });
try {
  // Local TLS uses an isolated Caddy CA; the Python gate separately verifies its chain/hostname.
  const page = await browser.newPage({ ignoreHTTPSErrors: process.env.PAPILIO_BROWSER_LOCAL_TLS === "true" });
  const readJson = url => page.evaluate(address => fetch(address).then(response => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }), url);
  await page.goto(`${base}/setup`);
  if (process.env.PAPILIO_EXPECT_LOCAL_NODE === "true") {
    await expect(page.getByTestId("setup-local-enabled")).toBeChecked();
    await page.getByTestId("local-definition-advanced").click();
    await page.getByLabel("Client connection host", { exact: true }).fill("127.0.0.1");
  }
  if (insecureDomain) {
    assert.equal(await page.evaluate(() => window.isSecureContext), false);
    assert.equal(await page.evaluate(() => typeof crypto.randomUUID), "undefined");
  }
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
  const cookies = (await page.context().cookies()).filter(cookie => /_(session|csrf)$/.test(cookie.name));
  assert.equal(cookies.length, 2);
  assert(cookies.every(cookie => cookie.secure === (new URL(base).protocol === "https:")));
  await page.getByTestId("system-status").waitFor();
  if (process.env.PAPILIO_EXPECT_LOCAL_NODE === "true") {
    const localPath = `${base}/api/v1/system/local-node`;
    await expect.poll(async () => (await readJson(localPath)).operation.status,
      { timeout: 35000, intervals: [100, 250, 500] }).toBe("succeeded");
    const local = await readJson(localPath);
    const service = await page.evaluate(async values => {
      const csrf = await (await fetch("/api/v1/admin/auth/csrf")).json();
      const response = await fetch("/api/v1/services", { method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf.csrf_token }, body: JSON.stringify(values) });
      if (response.status !== 202) throw new Error(`Local service creation returned ${response.status}`);
      return response.json();
    }, { request_key: randomUUID(), name: "Installed local service", core_id: local.core_id,
      inbound_id: local.inbound_id, identifier: randomUUID() });
    await expect.poll(async () => (await readJson(`${base}/api/v1/services/${service.id}`)).status,
      { timeout: 35000, intervals: [100, 250, 500] }).toBe("succeeded");
    const subscription = await readJson(`${base}/api/v1/services/${service.id}/subscription`);
    const feed = await page.request.get(new URL(subscription.url, base).href);
    assert.equal(feed.status(), 200);
    const uri = Buffer.from(await feed.text(), "base64").toString().trim();
    assert(uri.startsWith("vless://"));
    assert(process.env.PAPILIO_LOCAL_NODE_RESULT);
    writeFileSync(process.env.PAPILIO_LOCAL_NODE_RESULT, JSON.stringify({ uri, service_id: service.id }), { mode: 0o600 });
  }
  assert.match(await page.getByTestId("system-status").innerText(), /base01|browser/);
  const schedule = page.getByTestId("schedule-outbox");
  await schedule.locator('input[type="number"]').fill("2");
  const [savedSchedule] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/system/schedules/outbox") && response.request().method() === "PUT"),
    schedule.getByRole("button", { name: "Save", exact: true }).click(),
  ]);
  assert.equal(savedSchedule.status(), 200);
  assert.equal((await savedSchedule.json()).interval_seconds, 2);
  const serviceSchedule = page.getByTestId("schedule-service-outbox");
  await expect(serviceSchedule).toContainText("Service provisioning delivery");
  await serviceSchedule.locator('input[type="number"]').fill("3");
  await serviceSchedule.locator('input[type="checkbox"]').uncheck();
  const [pausedServiceDelivery] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/system/schedules/service-outbox") && response.request().method() === "PUT"),
    serviceSchedule.getByRole("button", { name: "Save", exact: true }).click(),
  ]);
  assert.equal(pausedServiceDelivery.status(), 200);
  assert.equal((await pausedServiceDelivery.json()).enabled, false);
  await page.reload();
  await expect(serviceSchedule.locator('input[type="number"]')).toHaveValue("3");
  await expect(serviceSchedule.locator('input[type="checkbox"]')).not.toBeChecked();
  await serviceSchedule.locator('input[type="checkbox"]').check();
  const [resumedServiceDelivery] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/system/schedules/service-outbox") && response.request().method() === "PUT"),
    serviceSchedule.getByRole("button", { name: "Save", exact: true }).click(),
  ]);
  assert.equal(resumedServiceDelivery.status(), 200);
  const [submission] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/system/probes") && response.request().method() === "POST"),
    page.getByTestId("probe-io").click(),
  ]);
  assert.equal(submission.status(), 202);
  const operation = await submission.json();
  assert.equal(operation.kind, "io");
  await page.getByTestId("probe-operation").waitFor();
  await expect.poll(async () => {
    const result = await readJson(`${base}/api/v1/system/operations/${operation.id}`);
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
  await expect.poll(async () => (await readJson(`${base}/api/v1/nodes/${registration.node.id}/operations/${registration.operation.id}`)).status,
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
  await page.getByTestId("node-row").filter({ hasText: /^browser-node$/ }).click();
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
  assert(process.env.PAPILIO_TEST_TELEGRAM_API_URL && process.env.PAPILIO_TEST_TELEGRAM_CONTAINER);
  await page.getByRole("link", { name: "Telegram bots", exact: true }).click();
  await page.waitForURL(`${base}/bots`);
  await page.getByTestId("bot-create-label").fill("browser-bot");
  await page.getByTestId("bot-create-token").fill("123456789:placeholder-not-a-real-telegram-token");
  await page.getByTestId("bot-create-interval").fill("1");
  await page.getByTestId("bot-create-advanced").click();
  await page.getByTestId("bot-create-api_base_url").fill(process.env.PAPILIO_TEST_TELEGRAM_API_URL);
  await page.getByTestId("bot-create-poll_timeout_seconds").fill("1");
  await page.getByTestId("bot-create-http_timeout_seconds").fill("6");
  const [botCreated] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/api/v1/bots") && response.request().method() === "POST"),
    page.getByTestId("bot-create-submit").click(),
  ]);
  assert.equal(botCreated.status(), 202);
  const bot = await botCreated.json();
  assert.equal("token" in bot, false);
  await expect(page.getByTestId("bot-create-token")).toHaveValue("");
  await expect(page.getByTestId("bot-edit-token")).toHaveValue("");
  const botUrl = `${base}/api/v1/bots/${bot.id}`;
  await expect.poll(async () => (await readJson(botUrl)).verified,
    { timeout: 35000, intervals: [100, 250, 500] }).toBe(true);
  await page.getByTestId("bot-refresh").click();
  await page.getByTestId("bot-pair-create").click();
  const pairingLink = await page.getByTestId("bot-pair-link").getAttribute("href");
  assert(pairingLink);
  const pairingParameter = new URL(pairingLink).searchParams.get("start");
  assert(pairingParameter);
  const fixtureProgram = `import http.client,json,sys,urllib.parse; data=json.load(sys.stdin); endpoint=urllib.parse.urlsplit(data['address']); client=http.client.HTTPConnection(endpoint.hostname,endpoint.port,timeout=5); client.request('POST','/bot123456789:fixture/fixturePush',body=json.dumps({'update_id':40,'text':data['text']}).encode(),headers={'Content-Type':'application/json'}); response=client.getresponse(); assert response.status==200; client.close()`;
  execFileSync("docker", ["exec", "-i", process.env.PAPILIO_TEST_TELEGRAM_CONTAINER, "python", "-c", fixtureProgram],
    { input: JSON.stringify({ address: process.env.PAPILIO_TEST_TELEGRAM_API_URL, text: `/start ${pairingParameter}` }) });
  await expect.poll(async () => (await readJson(botUrl)).admin_chat_id,
    { timeout: 35000, intervals: [100, 250, 500] }).toBe(456789);
  await page.getByTestId("bot-refresh").click();
  await expect(page.getByTestId("bot-detail")).toContainText("456789");
  await page.getByTestId("bot-edit-label").fill("browser-bot-edited");
  await page.getByTestId("bot-edit-enabled").uncheck();
  await page.getByTestId("bot-edit-interval").fill("11");
  await page.getByTestId("bot-edit-advanced").click();
  await page.getByTestId("bot-edit-pairing_ttl_seconds").fill("91");
  const [botSaved] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith(`/api/v1/bots/${bot.id}`) && response.request().method() === "PUT"),
    page.getByTestId("bot-edit-submit").click(),
  ]);
  assert.equal(botSaved.status(), 200);
  assert.equal((await botSaved.json()).schedule.enabled, false);
  await page.reload();
  await page.getByTestId("bot-row").click();
  await expect(page.getByTestId("bot-edit-label")).toHaveValue("browser-bot-edited");
  await expect(page.getByTestId("bot-edit-token")).toHaveValue("");
  await expect(page.getByTestId("bot-edit-enabled")).not.toBeChecked();
  console.log("Installed browser, real worker and external Telegram double: setup, private credentials, pairing and schedule edits passed.");
  console.log("Real setup, CSRF login, authenticated status, outbox submission and session reload passed.");
} finally {
  await browser.close();
}
