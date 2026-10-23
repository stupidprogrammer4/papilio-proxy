import assert from "node:assert/strict";
import { expect } from "playwright/test";

export async function createNativeProduct(page, base, coreName) {
  await page.getByTestId("locale-selector").selectOption("en");
  await page.goto(`${base}/products`);
  await expect(page.getByTestId("products-title")).toHaveText("Products", { timeout: 5000 });
  await page.getByTestId("core-picker").getByRole("button", { name: coreName, exact: true }).click();
  await page.getByTestId("inbound-picker").getByRole("button", { name: /vless-test/ }).click();
  await page.getByTestId("product-name").fill("Browser purchase product");
  await page.getByTestId("product-price").fill("1000");
  const [created] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/v1/products") && r.request().method() === "POST"),
    page.getByTestId("product-save").click(),
  ]);
  assert.equal(created.status(), 201);
  const product = await created.json();
  await expect(page.getByTestId("product-current")).toContainText(product.offer.definition.name);
  await page.reload();
  await page.getByTestId("product-picker").getByRole("button", { name: product.offer.definition.name, exact: true }).click();
  await expect(page.getByTestId("product-price")).toHaveValue("1000");
  await expect(page.getByTestId("selected-inbound")).toContainText("vless-test");
  await page.getByTestId("product-price").fill("2000");
  const [updated] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith(`/api/v1/products/${product.id}`) && r.request().method() === "PUT"),
    page.getByTestId("product-save").click(),
  ]);
  assert.equal(updated.status(), 200);
  const historical = await page.request.get(`${base}/api/v1/product-offers/${product.offer.id}`);
  assert.equal((await historical.json()).definition.price_minor, "1000");
  await page.getByTestId("product-price").fill("1000");
  const [restored] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith(`/api/v1/products/${product.id}`) && r.request().method() === "PUT"),
    page.getByTestId("product-save").click(),
  ]);
  assert.equal(restored.status(), 200);
  await page.getByTestId("locale-selector").selectOption("fa");
  await expect(page.getByTestId("products-title")).toHaveText("محصولات");
  await page.getByTestId("locale-selector").selectOption("en");
  return restored.json();
}

export async function buyNativeService(page, base, product) {
  await page.getByTestId("locale-selector").selectOption("en");
  await page.getByTestId("wallet-amount").fill("1000");
  await page.getByTestId("wallet-reason").fill("Funds for actual purchase");
  await page.getByTestId("wallet-post").click();
  await expect(page.getByTestId("wallet-balance")).toHaveText("1000 IRR (rial)");
  await page.getByTestId("purchase-product-picker").getByRole("button", { name: product.offer.definition.name, exact: true }).click();
  await page.getByTestId("purchase-service-name").fill("Bought from browser");
  const [purchased] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/v1/orders") && r.request().method() === "POST"),
    page.getByTestId("purchase-submit").click(),
  ]);
  assert.equal(purchased.status(), 201);
  const order = await purchased.json();
  assert.equal(order.terms.price_minor, "1000");
  await expect.poll(async () => {
    await page.getByTestId("purchase-refresh").click();
    return page.getByTestId("purchase-service-status").innerText();
  }, { timeout: 35000, intervals: [200, 500] }).toContain("Succeeded");
  await page.getByTestId("purchase-subscription").click();
  await expect(page.getByTestId("purchase-url")).toBeVisible();
  const link = await page.getByTestId("purchase-url").inputValue();
  const response = await page.request.get(link);
  assert.equal(response.status(), 200);
  const uri = Buffer.from(await response.text(), "base64").toString().trim();
  await page.getByTestId("wallet-refresh").click();
  await expect(page.getByTestId("wallet-balance")).toHaveText("0 IRR (rial)");
  await page.getByTestId("customer-name").fill("Other browser customer");
  await page.getByTestId("customer-create").click();
  await expect(page.getByTestId("wallet-open")).toBeVisible();
  await expect(page.getByTestId("purchase-history").getByTestId("record-empty")).toBeVisible();
  await page.getByTestId("customer-picker").getByRole("button", { name: "Browser customer", exact: true }).click();
  await page.getByTestId("purchase-history").getByRole("button", { name: order.service_name, exact: true }).click();
  await expect(page.getByTestId("purchase-service-status")).toContainText("Succeeded");
  await expect(page.getByTestId("purchase-url")).toHaveCount(0);
  return { order_id: order.id, service_id: order.service_id, uri };
}
