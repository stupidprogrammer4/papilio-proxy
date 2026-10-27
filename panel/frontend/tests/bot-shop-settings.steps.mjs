import assert from "node:assert/strict";
import { expect } from "playwright/test";

async function save(page, botId, method) {
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith(`/api/v1/bots/${botId}/shop`) && r.request().method() === method),
    page.getByTestId("shop-save").click(),
  ]);
  return response;
}

export async function exerciseBotShopSettings(page, base) {
  await page.getByTestId("locale-selector").selectOption("en");
  await page.goto(`${base}/bots`);
  await page.getByTestId("bot-create-label").fill("Browser shop one");
  await page.getByTestId("bot-create-token").fill("123456789:placeholder-not-a-real-telegram-token");
  await page.getByTestId("bot-create-enabled").uncheck();
  const [created] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/v1/bots") && r.request().method() === "POST"),
    page.getByTestId("bot-create-submit").click(),
  ]);
  assert.equal(created.status(), 202);
  const first = await created.json();
  const endpoint = `${base}/api/v1/bots/${first.id}/shop`;
  await expect(page.getByTestId("shop-title")).toHaveText("Bot shop");
  assert.equal((await page.request.get(endpoint)).status(), 404, "Reading defaults must not create shop settings.");
  await page.getByTestId("shop-public_origin").fill("http://shop-one.example.invalid");
  await page.getByTestId("shop-enabled").check();
  await page.getByTestId("shop-delivery_enabled").uncheck();
  await page.getByTestId("shop-locale").selectOption("en");
  await page.getByTestId("shop-advanced").click();
  const numbers = { page_size: 3, retry_seconds: 17, lease_seconds: 65, max_attempts: 7, confirmation_ttl_seconds: 91 };
  // Browser input actions share focus; concurrent fills can type into another field.
  await page.getByTestId("shop-page_size").fill("3");
  await page.getByTestId("shop-retry_seconds").fill("17");
  await page.getByTestId("shop-lease_seconds").fill("65");
  await page.getByTestId("shop-max_attempts").fill("7");
  await page.getByTestId("shop-confirmation_ttl_seconds").fill("91");
  await page.getByTestId("shop-ambiguous_delivery").selectOption("retry");
  await page.getByTestId("shop-texts").click();
  await page.getByTestId("shop-text-locale").selectOption("en");
  await page.getByTestId("shop-text-welcome").fill("Private shop $name");
  await page.getByTestId("shop-text-wallet_button").fill("My balance");
  await page.getByTestId("shop-text-locale").selectOption("fa");
  await page.getByTestId("shop-text-welcome").fill("فروشگاه $name");
  await page.getByTestId("shop-text-locale").selectOption("ru");
  await page.getByTestId("shop-text-welcome").fill("Магазин $name");
  await page.getByTestId("shop-text-locale").selectOption("zh");
  await page.getByTestId("shop-text-welcome").fill("商店 $name");
  const saved = await save(page, first.id, "POST");
  assert.equal(saved.status(), 201);
  const initial = await saved.json();
  assert.deepEqual(Object.fromEntries(Object.keys(numbers).map(key => [key, initial.definition[key]])), numbers);
  assert.equal(initial.definition.enabled, true);
  assert.equal(initial.definition.delivery_enabled, false);
  assert.equal(initial.definition.ambiguous_delivery, "retry");
  assert.equal(initial.definition.texts.en.welcome, "Private shop $name");
  assert.equal(initial.definition.texts.fa.welcome, "فروشگاه $name");
  assert.equal(initial.definition.texts.ru.welcome, "Магазин $name");
  assert.equal(initial.definition.texts.zh.welcome, "商店 $name");
  assert.equal(initial.definition.texts.en.wallet_button, "My balance");
  await expect(page.getByTestId("shop-settings").locator("textarea")).toHaveCount(Object.keys(initial.definition.texts.fa).length);
  await page.getByTestId("shop-text-welcome").fill("$unsupported_placeholder");
  assert.equal((await save(page, first.id, "PUT")).status(), 400);
  await expect(page.getByTestId("shop-text-welcome")).toHaveValue("$unsupported_placeholder");
  assert.deepEqual((await (await page.request.get(endpoint)).json()).definition, initial.definition);
  await page.reload();
  await page.getByRole("button", { name: "Browser shop one", exact: true }).click();
  await expect(page.getByTestId("shop-public_origin")).toHaveValue("http://shop-one.example.invalid");
  await expect(page.getByTestId("shop-delivery_enabled")).not.toBeChecked();
  await page.getByTestId("shop-public_origin").fill("http://my-draft.example.invalid");
  await page.getByTestId("bot-refresh").click();
  await expect(page.getByTestId("shop-public_origin")).toHaveValue("http://my-draft.example.invalid");
  const other = await page.context().newPage();
  try {
    await other.goto(`${base}/bots`);
    await other.getByRole("button", { name: "Browser shop one", exact: true }).click();
    await other.getByTestId("shop-enabled").uncheck();
    assert.equal((await save(other, first.id, "PUT")).status(), 200);
    assert.equal((await save(page, first.id, "PUT")).status(), 409);
    await expect(page.getByTestId("shop-public_origin")).toHaveValue("http://my-draft.example.invalid");
    await expect(page.getByTestId("shop-error")).toBeVisible();
    await page.getByTestId("shop-reload").click();
    await expect(page.getByTestId("shop-public_origin")).toHaveValue("http://shop-one.example.invalid");
    await expect(page.getByTestId("shop-enabled")).not.toBeChecked();
  } finally { await other.close(); }
  await page.getByTestId("bot-create-label").fill("Browser shop two");
  await page.getByTestId("bot-create-token").fill("987654321:placeholder-not-a-real-second-token");
  await page.getByTestId("bot-create-enabled").uncheck();
  const [secondResponse] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/v1/bots") && r.request().method() === "POST"),
    page.getByTestId("bot-create-submit").click(),
  ]);
  const second = await secondResponse.json();
  await expect(page.getByTestId("shop-public_origin")).toHaveValue("");
  await page.getByTestId("shop-public_origin").fill("https://shop-two.example.invalid");
  assert.equal((await save(page, second.id, "POST")).status(), 201);
  await page.getByRole("button", { name: "Browser shop one", exact: true }).click();
  await expect(page.getByTestId("shop-public_origin")).toHaveValue("http://shop-one.example.invalid");
  await page.getByTestId("locale-selector").selectOption("fa");
  await expect(page.getByTestId("shop-title")).toHaveText("فروشگاه بات");
  await page.getByTestId("locale-selector").selectOption("en");
  assert.deepEqual((await (await page.request.get(endpoint)).json()).definition, { ...initial.definition, enabled: false });
  return { first: first.id, second: second.id };
}

export async function assertStaffShopDenied(page, base) {
  await page.goto(`${base}/bots`);
  await page.getByTestId("bot-create-label").fill("Staff connection only");
  await page.getByTestId("bot-create-token").fill("234567890:placeholder-not-a-real-staff-token");
  await page.getByTestId("bot-create-enabled").uncheck();
  const [created] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/api/v1/bots") && r.request().method() === "POST"),
    page.getByTestId("bot-create-submit").click(),
  ]);
  assert.equal(created.status(), 202);
  const bot = await created.json();
  await expect(page.getByTestId("bot-detail")).toBeVisible();
  await expect(page.getByTestId("shop-settings")).toHaveCount(0);
  await expect(page.getByTestId("shop-recovery-title")).toHaveCount(0);
  assert.equal((await page.request.get(`${base}/api/v1/bots/${bot.id}/shop`)).status(), 401);
  assert.equal((await page.request.get(`${base}/api/v1/bot-shop-defaults`)).status(), 401);
  assert.equal((await page.request.get(`${base}/api/v1/bots/${bot.id}/shop/work`)).status(), 401);
  assert.equal((await page.request.get(`${base}/api/v1/bots/${bot.id}/shop/messages`)).status(), 401);
}
