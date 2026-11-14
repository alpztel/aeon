/**
 * Browser torture tests for the AEON frontend (PR #6) against the real core backend.
 * Each test documents one property the jury demo relies on.
 */
import { expect, test, type Page } from "@playwright/test";

const API = process.env.AEON_API ?? "http://localhost:8000";

function trackErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/aladin|favicon|Failed to load resource/i.test(m.text())) errors.push(`console: ${m.text()}`);
  });
  return errors;
}

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.getByText("Rendering sky cutout...")).toHaveCount(0);
}

test("T01 loads with backend data mode and no runtime errors", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/");
  await expect(page.getByText("Physical Model").or(page.getByText("FITS Archive")).first()).toBeVisible();
  await settle(page);
  expect(errors).toEqual([]);
});

test("T02 TR|EN toggle switches text and persists across reload", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "TR", exact: true }).click();
  await expect(page.getByText("Astrofizik Keşif İşletim Sistemi")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Astrofizik Keşif İşletim Sistemi")).toBeVisible();
  await page.getByRole("button", { name: "EN", exact: true }).click();
  await expect(page.getByText("Astrophysical Discovery OS")).toBeVisible();
});

const HOSTILE = ["%", "_", "' OR 1=1 --", "<img src=x onerror=alert(1)>", "../../etc/passwd", "🪐".repeat(50),
  "a".repeat(5000), "NaN NaN", "999 999", "-1 0", "133.7605 -7.2421", "Gezegen X", "  ", "\\"];

test("T03 hostile search inputs never crash the page or execute markup", async ({ page }) => {
  const errors = trackErrors(page);
  let dialogs = 0;
  page.on("dialog", (d) => { dialogs++; d.dismiss(); });
  await page.goto("/");
  await settle(page);
  const box = page.getByPlaceholder(/Search target/);
  for (const q of HOSTILE) {
    await box.fill(q);
    await box.press("Enter");
    await page.waitForTimeout(300);
    await expect(page.getByText("Astrophysical Discovery OS")).toBeVisible();
  }
  expect(dialogs).toBe(0);
  expect(errors).toEqual([]);
});

test("T04 coordinate search: invalid rejected, valid recentres", async ({ page }) => {
  await page.goto("/");
  await settle(page);
  const box = page.getByPlaceholder(/Search target/);
  await box.fill("400 0");
  await box.press("Enter");
  await expect(page.locator("text=/invalid|range|geçersiz/i").first()).toBeVisible();
  await box.fill("76.95642 30.40142");
  await box.press("Enter");
  await expect(page.getByText("76.95642°")).toBeVisible();
});

test("T05 epoch slider spam: final image equals a fresh render of the final epoch (no stale race)", async ({ page }) => {
  await page.goto("/");
  await settle(page);
  const epochs = ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"];
  for (let i = 0; i < 40; i++) await page.getByRole("button", { name: epochs[(i * 7) % 4], exact: true }).click();
  await page.getByRole("button", { name: "2026-Q3", exact: true }).click();
  await settle(page);
  const canvas = page.locator("canvas").first();
  const spammed = await canvas.evaluate((c: HTMLCanvasElement) => c.toDataURL());
  await page.reload();
  await settle(page);
  await page.getByRole("button", { name: "2026-Q3", exact: true }).click();
  await settle(page);
  const fresh = await canvas.evaluate((c: HTMLCanvasElement) => c.toDataURL());
  expect(spammed).toBe(fresh);
});

test("T06 quick-target spam ends on the last clicked target", async ({ page }) => {
  await page.goto("/");
  await settle(page);
  const names = ["WISE 0855", "RW Aur", "PX-2026-09"];
  for (let i = 0; i < 30; i++) await page.getByRole("button", { name: new RegExp(names[i % 3]) }).first().click();
  await page.getByRole("button", { name: /RW Aur/ }).first().click();
  await settle(page);
  await expect(page.getByRole("heading", { name: "RW Aurigae" })).toBeVisible();
});

test("T07 PX-2026-09 demo: synthetic badge shown and default shift-stack recovers it (S/N > 5)", async ({ page }) => {
  await page.goto("/");
  await settle(page);
  const stackResp = page.waitForResponse(
    async (r) => r.url().includes("/analysis/shift-stack") && (r.request().postData() ?? "").includes("520"), { timeout: 60_000 });
  await page.getByRole("button", { name: /PX-2026-09/ }).first().click();
  await expect(page.getByText("Synthetic Test Candidate").first()).toBeVisible();
  const body = await (await stackResp).json();
  expect(body.snr_stacked, `request ${(await stackResp).request().postData()}`).toBeGreaterThan(5);
});

test("T08 PX-2026-09 position follows the epoch (parallax ~400 arcsec between quarters)", async ({ page }) => {
  await page.goto("/");
  await settle(page);
  await page.getByRole("button", { name: /PX-2026-09/ }).first().click();
  await settle(page);
  const q1 = page.waitForRequest((r) => r.url().includes("/sky/cutout") && r.url().includes("2026-Q3"));
  await page.getByRole("button", { name: "2026-Q3", exact: true }).click();
  const url = new URL((await q1).url());
  const cat = await (await page.request.get(`${API}/api/v1/catalog/search?q=px-2026-09&epoch=2026-Q3`)).json();
  const ra = Number(url.searchParams.get("ra")), dec = Number(url.searchParams.get("dec"));
  const sepArcsec = Math.hypot((ra - cat.results[0].ra) * Math.cos((dec * Math.PI) / 180), dec - cat.results[0].dec) * 3600;
  expect(sepArcsec, "cutout centre vs catalog position at Q3").toBeLessThan(30);
});

test("T09 no fabricated multi-mission data while the missions service is absent", async ({ page }) => {
  const missions = await page.request.get(`${API}/api/v1/missions/crossmatch?ra=133.76&dec=-7.24`);
  test.skip(missions.status() === 200, "missions service deployed");
  await page.goto("/");
  await settle(page);
  // Hand-typed archive identifiers / magnitudes must never appear as if they were query results.
  for (const s of ["jw01902", "hst_13869", "156431440590447744", "14.05"]) {
    await expect(page.getByText(s)).toHaveCount(0);
  }
});

test("T10 keyboard shortcuts: ? opens help, Escape closes, D/S/3 toggle panels", async ({ page }) => {
  await page.goto("/");
  await settle(page);
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const before = await page.locator("canvas").count();
  await page.keyboard.press("d");
  await page.keyboard.press("s");
  await page.waitForTimeout(300);
  expect(await page.locator("canvas").count()).toBeLessThan(before);
});

test("T11 phone width: no horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await settle(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("T12 backend offline: page stays usable and labels the mode", async ({ page }) => {
  const errors = trackErrors(page);
  await page.route(`${API}/**`, (r) => r.abort());
  await page.goto("/");
  await expect(page.getByText("Offline Cache").first()).toBeVisible();
  const box = page.getByPlaceholder(/Search target/);
  await box.fill("WISE 0855");
  await box.press("Enter");
  await page.waitForTimeout(1000);
  await expect(page.getByText("Astrophysical Discovery OS")).toBeVisible();
  expect(errors.filter((e) => e.startsWith("pageerror"))).toEqual([]);
});

test("T13 colormap cycling changes pixels and never throws", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/");
  await settle(page);
  const select = page.locator("select").first();
  const canvas = page.locator("canvas").first();
  const seen = new Set<string>();
  for (let i = 0; i < 12; i++) {
    await select.selectOption(["inferno", "viridis", "magma", "grayscale"][i % 4]);
    seen.add(await canvas.evaluate((c: HTMLCanvasElement) => c.toDataURL()));
  }
  expect(seen.size).toBe(4);
  expect(errors).toEqual([]);
});
