/**
 * TEMPORARY (removed before merge): the API data added to the panels render against the full
 * Docker stack (backend + ai-engine + multi-mission-api behind nginx), in both languages, with no
 * runtime errors. Screenshots go to test-results/shots.
 */
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
});

const tool = (page: Page, name: string) =>
  page.getByRole("navigation", { name: /Analysis tools|Analiz araçları/ }).getByRole("button", { name: new RegExp(name) });

async function open(page: Page, name: string) {
  await tool(page, name).click();
  const panel = page.getByRole("complementary", { name: new RegExp(name) });
  await expect(panel).toBeVisible();
  return panel;
}

async function load(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/WISE/, { timeout: 45_000 });
  await page.waitForTimeout(1500);
}

test("P01 AI card: spectrum provenance + spectral physics, no ZOGY claim without an image", async ({ page }) => {
  const errors = trackErrors(page);
  await load(page);
  const panel = await open(page, "AI Classification");
  await expect(panel.getByText("Spectral physics")).toBeVisible({ timeout: 45_000 });
  await expect(panel.getByText(/Real SPHEREx|Physical model/).first()).toBeVisible();
  await expect(panel.getByText(/No image was sent/)).toBeVisible();
  await expect(panel.getByText("PSF Verified")).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/P01-ai.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test("P02 spectrum: data badge and model notice / facts", async ({ page }) => {
  const errors = trackErrors(page);
  await load(page);
  const panel = await open(page, "102-Band Spectrum");
  await expect(panel.getByText(/Real SPHEREx|Physical model/).first()).toBeVisible({ timeout: 45_000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/P02-spectrum.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test("P03 cross-match: SED physics, kinematics, data sources", async ({ page }) => {
  const errors = trackErrors(page);
  await load(page);
  const panel = await open(page, "Cross-Match & SED");
  await expect(panel.getByText("SED physics")).toBeVisible({ timeout: 45_000 });
  await expect(panel.getByText("Kinematics")).toBeVisible();
  await expect(panel.getByText("Data sources")).toBeVisible();
  await expect(panel.getByText("SPHEREx in SED")).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/P03-crossmatch.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test("P04 PX-2026-09 cross-match temperature is the equilibrium temperature", async ({ page }) => {
  const errors = trackErrors(page);
  await load(page);
  await page.getByPlaceholder(/Search a target/).click();
  await page.locator("#aeon-search-suggestions").getByRole("button", { name: /PX-2026-09/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/PX-2026-09/, { timeout: 30_000 });
  const panel = await open(page, "Cross-Match & SED");
  await expect(panel.getByText("SED physics")).toBeVisible({ timeout: 45_000 });
  await expect(panel.getByText(/equilibrium/).first()).toBeVisible();
  await expect(panel.getByText(/^1[01]\.\d K$/)).toBeVisible();          // ~11 K at 520 AU
  await expect(panel.getByText(/reflected sunlight/).first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/P04-px-crossmatch.png`, fullPage: true });
  const ai = await open(page, "AI Classification");
  await expect(ai.getByText("Spectral physics")).toBeVisible({ timeout: 45_000 });
  await page.screenshot({ path: `${SHOTS}/P04-px-ai.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test("P05 difference: baselines and data facts", async ({ page }) => {
  const errors = trackErrors(page);
  await load(page);
  const panel = await open(page, "Image Difference");
  await expect(panel.getByText("Nominal baseline")).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${SHOTS}/P05-difference.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test("P06 Turkish: new sections are translated", async ({ page }) => {
  const errors = trackErrors(page);
  await load(page);
  await page.getByRole("button", { name: "tr", exact: true }).click();
  const ai = await open(page, "Yapay Zekâ Sınıflandırma");
  await expect(ai.getByText("Tayf fiziği")).toBeVisible({ timeout: 45_000 });
  await page.screenshot({ path: `${SHOTS}/P06-tr-ai.png`, fullPage: true });
  const xm = await open(page, "Çapraz Eşleme ve SED");
  await expect(xm.getByText("SED fiziği")).toBeVisible({ timeout: 45_000 });
  await expect(xm.getByText("Kinematik")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/P06-tr-crossmatch.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test("P07 mobile width: panels do not overflow horizontally", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await load(page);
  for (const name of ["AI Classification", "Cross-Match & SED"]) {
    await tool(page, name).click();
    await page.waitForTimeout(4000);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${SHOTS}/P07-mobile-${name.split(" ")[0]}.png`, fullPage: true });
    await page.keyboard.press("Escape");
  }
});
