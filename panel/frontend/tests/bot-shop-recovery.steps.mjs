import assert from "node:assert/strict";
import { expect } from "playwright/test";

export async function exerciseBotRecovery(page, base) {
  const botId = process.env.PAPILIO_RECOVERY_BOT_ID;
  const workId = process.env.PAPILIO_RECOVERY_WORK_ID;
  const messageId = process.env.PAPILIO_RECOVERY_MESSAGE_ID;
  assert(botId && workId && messageId);
  await page.goto(`${base}/bots`);
  await page.getByRole("button", { name: "Browser recovery bot", exact: true }).click();
  await expect(page.getByTestId("shop-recovery-title")).toHaveText("Shop processing and delivery");
  const picker = page.getByTestId("shop-recovery-picker");
  await picker.locator('input[type="search"]').fill(workId);
  await picker.getByRole("button", { name: "Search", exact: true }).click();
  await picker.getByRole("button", { name: new RegExp(workId) }).click();
  await expect(page.getByTestId("recovery-status")).toHaveText("Failed");
  await page.getByTestId("recovery-note").fill("Browser cancelled failed work");
  const [cancelled] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith(`/api/v1/bots/${botId}/shop/work/${workId}/recoveries`) && r.request().method() === "POST"),
    page.getByTestId("recovery-cancel").click(),
  ]);
  assert.equal(cancelled.status(), 201);
  await expect(page.getByTestId("recovery-status")).toHaveText("Cancelled");
  await expect(page.getByTestId("recovery-history")).toContainText("Browser cancelled failed work");
  await picker.locator('input[type="search"]').fill("no-matching-work");
  await picker.getByRole("button", { name: "Search", exact: true }).click();
  await expect(picker.getByTestId("record-empty")).toBeVisible();
  await expect(page.getByTestId("recovery-status")).toHaveText("Cancelled");
  await page.getByTestId("shop-recovery-kind").selectOption("messages");
  await picker.locator('input[type="search"]').fill(messageId);
  await picker.getByRole("button", { name: "Search", exact: true }).click();
  await picker.getByRole("button", { name: new RegExp(messageId) }).click();
  await expect(page.getByTestId("recovery-status")).toHaveText("Delivery uncertain");
  await page.getByTestId("recovery-note").fill("Browser retried stored reply");
  const [retried] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith(`/api/v1/bots/${botId}/shop/messages/${messageId}/recoveries`) && r.request().method() === "POST"),
    page.getByTestId("recovery-retry").click(),
  ]);
  assert.equal(retried.status(), 201);
  await expect.poll(async () => {
    const response = await page.request.get(`${base}/api/v1/bots/${botId}/shop/messages/${messageId}`);
    assert.equal(response.status(), 200);
    return (await response.json()).status;
  }, { timeout: 12000, intervals: [100, 250, 500] }).toBe("sent");
  await page.getByTestId("recovery-refresh").click();
  await expect(page.getByTestId("recovery-status")).toHaveText("Sent");
  await expect(page.getByTestId("recovery-retry")).toHaveCount(0);
  await expect(page.getByTestId("recovery-history")).toContainText("Browser retried stored reply");
  await page.getByTestId("locale-selector").selectOption("fa");
  await expect(page.getByTestId("shop-recovery-title")).toHaveText("پردازش و ارسال فروشگاه");
  await page.getByTestId("locale-selector").selectOption("en");
}
