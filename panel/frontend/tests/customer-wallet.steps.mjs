import assert from "node:assert/strict";
import { expect } from "playwright/test";

export async function exerciseCustomerWallet(page, base) {
  await page.getByTestId("locale-selector").selectOption("en");
  await page.goto(`${base}/sales`);
  await expect(page.getByTestId("sales-title")).toHaveText("Customers and wallets", { timeout: 5000 });
  await page.getByTestId("customer-name").fill("Browser customer");
  const [created] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/v1/customer-accounts") && r.request().method() === "POST"),
    page.getByTestId("customer-create").click(),
  ]);
  assert.equal(created.status(), 201);
  const customer = await created.json();
  await expect(page.getByTestId("customer-selected")).toContainText(customer.name);
  await expect(page.getByTestId("wallet-open")).toBeVisible();
  await page.getByTestId("wallet-credit-limit").fill("50");
  await page.getByTestId("wallet-open").click();
  await expect(page.getByTestId("wallet-balance")).toHaveText("0 IRR (rial)");
  await page.getByTestId("wallet-amount").fill("9007199254740993");
  await page.getByTestId("wallet-reason").fill("Exact integer adjustment");
  const [credited] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith(`/api/v1/customer-accounts/${customer.id}/wallet/entries`) && r.request().method() === "POST"),
    page.getByTestId("wallet-post").click(),
  ]);
  assert.equal(credited.status(), 201);
  assert.equal((await credited.json()).amount_minor, "9007199254740993");
  await expect(page.getByTestId("wallet-balance")).toHaveText("9007199254740993 IRR (rial)");
  await page.getByTestId("wallet-kind").selectOption("debit");
  await page.getByTestId("wallet-amount").fill("9007199254740993");
  await page.getByTestId("wallet-reason").fill("Return to zero");
  await page.getByTestId("wallet-post").click();
  await expect(page.getByTestId("wallet-balance")).toHaveText("0 IRR (rial)");
  await page.getByTestId("wallet-credit-limit").fill("75");
  await page.getByTestId("wallet-save-limit").click();
  await expect(page.getByTestId("wallet-limit-current")).toContainText("75");
  await page.reload();
  await page.getByTestId("customer-picker").getByRole("button", { name: customer.name, exact: true }).click();
  await expect(page.getByTestId("wallet-balance")).toHaveText("0 IRR (rial)");
  await expect(page.getByTestId("wallet-limit-current")).toContainText("75");
  await expect(page.getByTestId("wallet-journal")).toContainText("9007199254740993");
  await page.getByTestId("locale-selector").selectOption("fa");
  await expect(page.getByTestId("sales-title")).toHaveText("مشتریان و کیف پول");
  assert.equal(await page.getByRole("alert").count(), 0);
  return customer.id;
}
