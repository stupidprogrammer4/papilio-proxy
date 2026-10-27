import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROMIUM_EXECUTABLE,
});
const page = await browser.newPage();
const botId = "00000000-0000-4000-8000-000000000123";
const definition = {
  public_origin: "https://panel.example.test",
  enabled: true,
  delivery_enabled: true,
  locale: "fa",
  page_size: 10,
  retry_seconds: 30,
  lease_seconds: 120,
  max_attempts: 5,
  confirmation_ttl_seconds: 900,
  ambiguous_delivery: "hold",
  flows: { catalogue: true, wallet: true, orders: true, help: true },
  welcome_photo_url: null,
  texts: Object.fromEntries(["en", "fa", "ru", "zh"].map(locale => [locale, {
    welcome: `${locale} welcome $name`,
    wallet_button: `${locale} wallet`,
  }])),
};
const bot = {
  id: botId,
  owner_id: 1,
  label: "Operator bot",
  revision: "1",
  runtime: {
    api_base_url: "https://api.telegram.org:443",
    poll_timeout_seconds: 10,
    http_timeout_seconds: 15,
    update_limit: 100,
    max_response_bytes: 16777216,
    pairing_ttl_seconds: 300,
    failure_retry_seconds: 30,
  },
  schedule: { enabled: true, interval_seconds: 10 },
  telegram_id: 10,
  username: "fixture_bot",
  verified: true,
  admin_chat_id: 11,
  last_poll_at: null,
  last_error_code: null,
  next_update_id: "0",
  retry_at: null,
};
let savedBody = null;
const errors = [];
const requests = [];
page.on("pageerror", error => errors.push(error.message));
await page.route(url => url.pathname.startsWith("/api/"), async route => {
  const request = route.request();
  const url = new URL(request.url());
  const path = url.pathname.slice(4);
  requests.push({ path, method: request.method() });
  let body;
  if (path === "/v1/admin/auth/me") {
    body = { username: "owner", scopes: ["bots:read", "bots:write", "bot-shop:read", "bot-shop:write"], csrf_token: "controlled" };
  } else if (path === "/v1/admin/branding") {
    body = { data: { brand_title: "Fixture" } };
  } else if (path === "/v1/bots/defaults") {
    body = { runtime: bot.runtime, schedule: bot.schedule };
  } else if (path === "/v1/bots") {
    body = { items: [bot], count: 1, page: 1, page_size: 20 };
  } else if (path === `/v1/bots/${botId}`) {
    body = bot;
  } else if (path === `/v1/bots/${botId}/shop` && request.method() === "GET") {
    body = { bot_id: botId, owner_id: 1, revision: "7", definition };
  } else if (path === `/v1/bots/${botId}/shop` && request.method() === "PUT") {
    savedBody = request.postDataJSON();
    const savedDefinition = { ...savedBody };
    delete savedDefinition.expected_revision;
    body = { bot_id: botId, owner_id: 1, revision: "8", definition: savedDefinition };
  } else if (path.startsWith(`/v1/bots/${botId}/shop/`)) {
    body = { items: [], count: 0, page: 1, page_size: 20 };
  } else {
    return route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  }
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
});

try {
  await page.goto(`${process.env.PANEL_ORIGIN}/bots`);
  await page.getByRole("button", { name: "Operator bot", exact: true }).click();
  await page.getByTestId("shop-texts").click();
  await page.getByTestId("shop-text-locale").selectOption("ru");
  await page.getByTestId("shop-text-welcome").fill("Изменённый текст $name");
  await page.getByTestId("shop-text-locale").selectOption("zh");
  await page.getByTestId("shop-text-wallet_button").fill("修改后的钱包按钮");
  await page.getByTestId("shop-locale").selectOption("zh");
  await page.getByTestId("shop-welcome-photo-url").fill("https://cdn.example.test/welcome.jpg");
  await page.getByTestId("shop-flow-catalogue").uncheck();
  await page.getByTestId("shop-flow-wallet").uncheck();
  const response = page.waitForResponse(result => result.url().endsWith(`/api/v1/bots/${botId}/shop`) && result.request().method() === "PUT");
  await page.getByTestId("shop-save").click();
  assert.equal((await response).status(), 200);
  assert.equal(savedBody.expected_revision, "7");
  assert.equal(savedBody.locale, "zh");
  assert.equal(savedBody.welcome_photo_url, "https://cdn.example.test/welcome.jpg");
  assert.deepEqual(savedBody.flows, { catalogue: false, wallet: false, orders: true, help: true });
  assert.equal(savedBody.texts.en.welcome, "en welcome $name");
  assert.equal(savedBody.texts.fa.welcome, "fa welcome $name");
  assert.equal(savedBody.texts.ru.welcome, "Изменённый текст $name");
  assert.equal(savedBody.texts.zh.wallet_button, "修改后的钱包按钮");
  assert.deepEqual(errors, []);
  console.log("PASS: per-bot shop edits preserve all four localized catalogs and current revision");
} catch (error) {
  console.error(JSON.stringify({ requests, errors, text: await page.locator("body").innerText() }));
  throw error;
} finally {
  await page.close();
  await browser.close();
}
