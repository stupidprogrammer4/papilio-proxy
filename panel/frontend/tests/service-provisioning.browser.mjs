import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { chromium } from "playwright";
import { expect } from "playwright/test";
import { exerciseCustomerWallet } from "./customer-wallet.steps.mjs";
import { fundNativeInvoice } from "./manual-payment.steps.mjs";
import { createNativeProduct, buyNativeService } from "./product-purchase.steps.mjs";
import { assertStaffShopDenied, exerciseBotShopSettings } from "./bot-shop-settings.steps.mjs";
import { exerciseBotRecovery } from "./bot-shop-recovery.steps.mjs";
import { exerciseServiceSynchronization } from "./service-synchronization.steps.mjs";

const base = process.env.PAPILIO_BROWSER_URL;
assert(base && process.env.PAPILIO_BROWSER_RESULT && process.env.PAPILIO_BROWSER_DATA_PORT);
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${base}/login`);
  await page.locator('input[autocomplete="username"]').fill("native-user-owner");
  await page.locator('input[autocomplete="current-password"]').fill("isolated-node-owner-password-944!");
  await page.locator("form button[type=submit], form button.btn").click();
  await page.waitForURL(`${base}/`);
  await page.goto(`${base}/services`);
  await expect(page.getByTestId("service-title")).toHaveText("Services", { timeout: 5000 });
  await page.getByTestId("core-registration").click();
  await page.getByTestId("core-node-picker").getByRole("button", { name: "first-node", exact: true }).click();
  await page.getByTestId("core-name").fill("Browser native Xray");
  const [registered] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/v1/cores/xray") && r.request().method() === "POST"),
    page.getByTestId("core-create").click(),
  ]);
  assert.equal(registered.status(), 201);
  const core = await registered.json();
  await expect(page.getByTestId("selected-core")).toContainText(core.name);
  const picker = page.getByTestId("core-picker");
  await picker.locator('input[type=search]').fill("no-such-core");
  await picker.getByRole("button", { name: "Search", exact: true }).click();
  await expect(picker.getByTestId("record-empty")).toBeVisible();
  await expect(page.getByTestId("selected-core")).toContainText(core.name);
  await page.getByTestId("inbound-registration").click();
  await page.getByTestId("inbound-tag").fill("vless-test");
  await page.getByTestId("inbound-host").fill("127.0.0.1");
  await page.getByTestId("inbound-port").fill(process.env.PAPILIO_BROWSER_DATA_PORT);
  await page.getByTestId("inbound-create").click();
  await expect(page.getByTestId("selected-inbound")).toContainText("vless-test");
  await page.getByTestId("service-name").fill("Browser real service");
  const [created] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/v1/services") && r.request().method() === "POST"),
    page.getByTestId("service-create").click(),
  ]);
  assert.equal(created.status(), 202);
  const service = await created.json();
  await expect.poll(async () => {
    await page.getByTestId("service-refresh").click();
    return page.getByTestId("service-status").innerText();
  }, { timeout: 35000, intervals: [200, 500] }).toContain("Succeeded");
  await page.getByTestId("service-subscription").click();
  await expect(page.getByTestId("subscription-url")).toHaveValue(/\/api\/v1\/subscriptions\?token=/);
  const subscription = await page.getByTestId("subscription-url").inputValue();
  const response = await page.request.get(subscription);
  assert.equal(response.status(), 200);
  const uri = Buffer.from(await response.text(), "base64").toString().trim();
  await page.getByTestId("service-name").fill("Second browser service");
  await page.getByTestId("service-create").click();
  const servicePicker = page.getByTestId("service-picker");
  await servicePicker.locator('input[type=number]').fill("1");
  await servicePicker.getByRole("button", { name: "Search", exact: true }).click();
  await servicePicker.getByRole("button", { name: service.name, exact: true }).click();
  await servicePicker.getByRole("button", { name: "Next page", exact: true }).click();
  await expect(servicePicker.getByRole("button", { name: "Second browser service", exact: true })).toBeVisible();
  await expect(page.getByTestId("service-detail")).toContainText(service.name);
  await page.reload();
  await page.getByTestId("service-picker").getByRole("button", { name: service.name, exact: true }).click();
  await expect(page.getByTestId("service-status")).toContainText("Succeeded");
  await expect(page.getByTestId("subscription-url")).toHaveCount(0);
  await exerciseServiceSynchronization(page, base, service);
  await page.getByTestId("locale-selector").selectOption("fa");
  await expect(page.getByTestId("service-title")).toHaveText("سرویس‌ها");
  await expect(page.getByTestId("service-subscription")).toHaveText("دریافت لینک اشتراک");
  assert.equal(await page.getByRole("alert").count(), 0);
  const staff = await browser.newPage();
  await staff.goto(`${base}/login`);
  await staff.locator('input[autocomplete="username"]').fill("service-browser-staff");
  await staff.locator('input[autocomplete="current-password"]').fill("isolated-node-owner-password-944!");
  await staff.locator("form button[type=submit], form button.btn").click();
  await staff.waitForURL(`${base}/`);
  await expect(staff.locator('nav a[href="/services"]')).toHaveCount(0);
  await staff.goto(`${base}/services`);
  await staff.waitForURL(`${base}/`);
  await expect(staff.getByTestId("service-title")).toHaveCount(0);
  assert.equal((await staff.request.get(`${base}/api/v1/services/${service.id}/synchronization`)).status(), 401);
  const product = await createNativeProduct(page, base, core.name);
  const customerId = await exerciseCustomerWallet(page, base);
  const invoiceId = await fundNativeInvoice(page, base, customerId);
  const purchase = await buyNativeService(page, base, product);
  await expect(staff.locator('nav a[href="/sales"]')).toHaveCount(0);
  await staff.goto(`${base}/sales`);
  await staff.waitForURL(`${base}/`);
  await expect(staff.getByTestId("sales-title")).toHaveCount(0);
  await expect(staff.locator('nav a[href="/products"]')).toHaveCount(0);
  await staff.goto(`${base}/products`);
  await staff.waitForURL(`${base}/`);
  assert.equal((await staff.request.get(`${base}/api/v1/products`)).status(), 401);
  await expect(staff.locator('nav a[href="/invoices"]')).toHaveCount(0);
  await staff.goto(`${base}/invoices`);
  await staff.waitForURL(`${base}/`);
  assert.equal((await staff.request.get(`${base}/api/v1/invoices`)).status(), 401);
  const shops = await exerciseBotShopSettings(page, base);
  await assertStaffShopDenied(staff, base);
  await exerciseBotRecovery(page, base);
  writeFileSync(process.env.PAPILIO_BROWSER_RESULT, JSON.stringify({ service_id: service.id, customer_id: customerId, invoice_id: invoiceId, uri, purchase, shops }), { mode: 0o600 });
} finally {
  await browser.close();
}
