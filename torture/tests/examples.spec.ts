/** TEMPORARY (removed before merge): example gallery against the full Docker stack. */
import { expect, test, type Page } from "@playwright/test";

const SHOTS = "test-results/shots";

function trackErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/aladin|favicon|Failed to load resource|ERR_|net::/i.test(m.text())) errors.push(`console: ${m.text()}`);
  });
  return errors;
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("aeon_onboarded_v1", "1");
    } catch {
      /* ignore */
    }
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/WISE/, { timeout: 45_000 });
});

const rail = (page: Page) => page.getByRole("navigation", { name: /Analysis tools|Analiz araçları/ });

test("E01 gallery lists the catalog by class and reports archive status", async ({ page }) => {
  const errors = trackErrors(page);
  await rail(page).getByRole("button", { name: /Examples/ }).click();
  const panel = page.getByRole("complementary", { name: /Examples/ });
  await expect(panel.getByText(/targets ·/)).toBeVisible({ timeout: 45_000 });
  const cards = panel.locator("li button");
  await expect(cards).toHaveCount(8, { timeout: 30_000 });          // the 8 catalog entries of this stack
  await expect(panel.getByRole("heading", { name: /Cold Brown Dwarf/ })).toBeVisible();
  await expect(panel.getByText(/checking the archive/)).toHaveCount(0, { timeout: 60_000 });
  await page.screenshot({ path: `${SHOTS}/E01-gallery.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test("E02 picking a card flies to that target", async ({ page }) => {
  const errors = trackErrors(page);
  await page.keyboard.press("g");
  const panel = page.getByRole("complementary", { name: /Examples/ });
  await panel.locator("li button", { hasText: "WISE J182831" }).click({ timeout: 45_000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/WISE J1828/, { timeout: 30_000 });
  await expect(panel.locator("li button[aria-current=true]")).toContainText(/WISE J1828/);
  await page.screenshot({ path: `${SHOTS}/E02-picked.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test("E03 Turkish + filter + mobile width", async ({ page }) => {
  await page.getByRole("button", { name: "tr", exact: true }).click();
  await rail(page).getByRole("button", { name: /Örnekler/ }).click();
  const panel = page.getByRole("complementary", { name: /Örnekler/ });
  await expect(panel.getByText(/hedef ·/)).toBeVisible({ timeout: 45_000 });
  await panel.getByRole("button", { name: "Gerçek SPHEREx" }).click();
  await page.screenshot({ path: `${SHOTS}/E03-tr-filter.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(1500);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${SHOTS}/E03-mobile.png`, fullPage: true });
});
