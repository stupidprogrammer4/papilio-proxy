import assert from "node:assert/strict";
import { expect } from "playwright/test";

export async function exerciseServiceSynchronization(page, base, service) {
  const panel = page.getByTestId("service-synchronization");
  const endpoint = `/api/v1/services/${service.id}/synchronization`;
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId("service-sync-enabled")).toBeChecked();
  await panel.getByTestId("service-sync-enabled").uncheck();
  await panel.getByTestId("service-sync-interval").fill("7");
  const [saved] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith(endpoint) && r.request().method() === "PUT"),
    panel.getByTestId("service-sync-save").click(),
  ]);
  assert.equal(saved.status(), 200);
  await page.reload();
  await page.getByTestId("service-picker").getByRole("button", { name: service.name, exact: true }).click();
  await expect(panel.getByTestId("service-sync-enabled")).not.toBeChecked();
  await expect(panel.getByTestId("service-sync-interval")).toHaveValue("7");
  const other = await page.context().newPage();
  try {
    await other.goto(`${base}/services`);
    await other.getByTestId("service-picker").getByRole("button", { name: service.name, exact: true }).click();
    await expect(other.getByTestId("service-sync-interval")).toHaveValue("7");
    await panel.getByTestId("service-sync-interval").fill("11");
    await other.getByTestId("service-sync-interval").fill("13");
    const [changed] = await Promise.all([
      other.waitForResponse(r => r.url().endsWith(endpoint) && r.request().method() === "PUT"),
      other.getByTestId("service-sync-save").click(),
    ]);
    assert.equal(changed.status(), 200);
    const [conflict] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith(endpoint) && r.request().method() === "PUT"),
      panel.getByTestId("service-sync-save").click(),
    ]);
    assert.equal(conflict.status(), 409);
    await expect(panel.getByTestId("service-sync-interval")).toHaveValue("11");
    await panel.getByTestId("service-sync-refresh").click();
    await expect(panel.getByTestId("service-sync-interval")).toHaveValue("13");
    await panel.getByTestId("service-sync-interval").fill("7");
    const [restored] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith(endpoint) && r.request().method() === "PUT"),
      panel.getByTestId("service-sync-save").click(),
    ]);
    assert.equal(restored.status(), 200);
    await other.goto(`${base}/`);
    const schedule = other.getByTestId("schedule-service-synchronization");
    await expect(schedule).toContainText("Native service synchronization");
    await schedule.locator('input[type="checkbox"]').uncheck();
    await schedule.locator('input[type="number"]').fill("2");
    const schedulePath = "/api/v1/system/schedules/service-synchronization";
    const [paused] = await Promise.all([
      other.waitForResponse(r => r.url().endsWith(schedulePath) && r.request().method() === "PUT"),
      schedule.getByRole("button", { name: "Save", exact: true }).click(),
    ]);
    assert.equal(paused.status(), 200);
    await other.reload();
    await expect(schedule.locator('input[type="checkbox"]')).not.toBeChecked();
    await expect(schedule.locator('input[type="number"]')).toHaveValue("2");
    await schedule.locator('input[type="checkbox"]').check();
    await schedule.locator('input[type="number"]').fill("1");
    const [resumed] = await Promise.all([
      other.waitForResponse(r => r.url().endsWith(schedulePath) && r.request().method() === "PUT"),
      schedule.getByRole("button", { name: "Save", exact: true }).click(),
    ]);
    assert.equal(resumed.status(), 200);
  } finally { await other.close(); }
  await page.getByTestId("locale-selector").selectOption("fa");
  await expect(panel.getByTestId("service-sync-title")).toHaveText("همگام‌سازی کاربر هسته");
  await page.getByTestId("locale-selector").selectOption("en");
}
