import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { expect } from "playwright/test";

export async function fundNativeInvoice(page, base, customerId) {
  await page.getByTestId("locale-selector").selectOption("en");
  await page.goto(`${base}/invoices`);
  await expect(page.getByTestId("invoices-title")).toHaveText("Manual payments", { timeout: 5000 });
  await page.getByTestId("payment-recipient").fill("Browser receiving account");
  await page.getByTestId("payment-destination").fill("TEST-ACCOUNT-ORIGINAL");
  await page.getByTestId("payment-instructions").fill("Submit your payment receipt for review.");
  await page.getByTestId("payment-max-bytes").fill("1000000");
  const [configured] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/v1/payment-settings") && r.request().method() === "POST"),
    page.getByTestId("payment-save").click(),
  ]);
  assert.equal(configured.status(), 201);
  await page.goto(`${base}/sales`);
  await page.getByTestId("customer-picker").getByRole("button", { name: "Browser customer", exact: true }).click();
  await page.getByTestId("invoice-amount").fill("1000");
  const [issued] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/v1/invoices") && r.request().method() === "POST"),
    page.getByTestId("invoice-issue").click(),
  ]);
  assert.equal(issued.status(), 201);
  const invoice = await issued.json();
  assert.equal(invoice.customer_id, customerId);
  await expect(page.getByTestId("invoice-destination")).toHaveText("TEST-ACCOUNT-ORIGINAL");
  await page.getByTestId("receipt-reference").fill("TEST-BROWSER-TRANSFER");
  await page.getByTestId("receipt-file").setInputFiles({ name: "browser-receipt.png", mimeType: "image/png", buffer: Buffer.from("controlled-private-receipt") });
  const [submitted] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith(`/api/v1/invoices/${invoice.id}/receipts`) && r.request().method() === "POST"),
    page.getByTestId("receipt-submit").click(),
  ]);
  assert.equal(submitted.status(), 201);
  const receipt = await submitted.json();
  await expect(page.getByTestId("invoice-status")).toHaveText("Awaiting review");
  await page.goto(`${base}/invoices`);
  await page.getByTestId("payment-destination").fill("TEST-ACCOUNT-NEW");
  await page.getByTestId("payment-enabled").uncheck();
  await page.getByTestId("payment-save").click();
  await expect(page.getByTestId("payment-revision")).toHaveText("2");
  await page.getByTestId("invoice-status-filter").selectOption("review");
  await page.getByTestId("invoice-picker").getByRole("button", { name: new RegExp(invoice.id) }).click();
  await page.goto(`${base}/invoices?invoice_id=${encodeURIComponent(invoice.id)}`);
  await expect(page.getByTestId("invoice-detail").getByRole("heading", { name: invoice.id, exact: true })).toBeVisible();
  await expect(page.getByTestId("invoice-customer")).toHaveText("Browser customer");
  await expect(page.getByTestId("invoice-destination")).toHaveText("TEST-ACCOUNT-ORIGINAL");
  await page.getByTestId("receipt-picker").getByRole("button", { name: /TEST-BROWSER-TRANSFER/ }).click();
  const [download] = await Promise.all([
    page.waitForEvent("download"), page.getByTestId("receipt-download").click(),
  ]);
  assert.equal((await readFile(await download.path())).toString(), "controlled-private-receipt");
  await page.getByTestId("payment-decision-reason").fill("Verified in the receiving bank account (controlled test).");
  const [approved] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith(`/api/v1/invoices/${invoice.id}/decisions`) && r.request().method() === "POST"),
    page.getByTestId("payment-approve").click(),
  ]);
  assert.equal(approved.status(), 201);
  assert.equal((await approved.json()).decision.receipt_id, receipt.id);
  await expect(page.getByTestId("invoice-status")).toHaveText("Settled");
  await expect(page.getByTestId("payment-approve")).toBeDisabled();
  await page.getByTestId("locale-selector").selectOption("fa");
  await expect(page.getByTestId("invoices-title")).toHaveText("پرداخت‌های دستی");
  await page.getByTestId("locale-selector").selectOption("en");
  await page.goto(`${base}/sales`);
  await page.getByTestId("customer-picker").getByRole("button", { name: "Browser customer", exact: true }).click();
  await expect(page.getByTestId("wallet-balance")).toHaveText("1000 IRR (rial)");
  return invoice.id;
}
