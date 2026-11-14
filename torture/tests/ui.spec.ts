/**
 * Browser torture tests + screenshot tour for the "Gözlemevi" AEON UI, against the real core backend.
 */
import { expect, test, type Page } from "@playwright/test";

const API = process.env.AEON_API ?? "http://localhost:8000";
const SHOTS = "test-results/shots";

function trackErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/aladin|favicon|Failed to load resource|ERR_|net::/i.test(m.text())) errors.push(`console: ${m.text()}`);
  });
  return errors;
}

async function skipWelcome(page: Page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("aeon_onboarded_v1", "1");
    } catch {
      /* ignore */
    }
  });
}

async function settle(page: Page) {
  await page.waitForLoadState("domcontentloaded");
  await expect(page.getByText("Connecting...")).toHaveCount(0, { timeout: 30_000 });
  await page.waitForFunction(() => !document.querySelector(".aeon-progress")?.parentElement?.classList.contains("opacity-100"), null, { timeout: 45_000 });
  await page.waitForTimeout(600);
}

const search = (page: Page) => page.getByPlaceholder(/Search a target/);
const epochBtn = (page: Page, ep: string) => page.getByRole("button", { name: `Survey epoch ${ep}` });
const tool = (page: Page, name: RegExp) => page.getByRole("navigation", { name: "Analysis tools" }).getByRole("button", { name });

async function pickDemo(page: Page, name: RegExp) {
  await search(page).click();
  await page.locator("#aeon-search-suggestions").getByRole("button", { name }).click();
}

test.describe("functional torture", () => {
  test.beforeEach(async ({ page }) => skipWelcome(page));

  test("U01 loads with backend data mode, target card and no runtime errors", async ({ page }) => {
    const errors = trackErrors(page);
    await page.goto("/");
    await expect(page.getByText("Physical Model").or(page.getByText("FITS Archive")).first()).toBeVisible();
    await settle(page);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/WISE/);
    expect(errors).toEqual([]);
  });

  test("U02 TR|EN toggle switches text and persists across reload", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "tr", exact: true }).click();
    await expect(page.getByPlaceholder("Hedef veya RA, Dec ara")).toBeVisible();
    await page.reload();
    await expect(page.getByPlaceholder("Hedef veya RA, Dec ara")).toBeVisible();
    await page.getByRole("button", { name: "en", exact: true }).click();
    await expect(search(page)).toBeVisible();
  });

  const HOSTILE = ["%", "_", "' OR 1=1 --", "<img src=x onerror=alert(1)>", "../../etc/passwd", "🪐".repeat(50),
    "a".repeat(5000), "NaN NaN", "999 999", "-1 0", "133.7605 -7.2421", "Gezegen X", "\\"];

  test("U03 hostile search inputs never crash the page or execute markup", async ({ page }) => {
    const errors = trackErrors(page);
    let dialogs = 0;
    page.on("dialog", (d) => { dialogs++; void d.dismiss(); });
    await page.goto("/");
    await settle(page);
    for (const q of HOSTILE) {
      await search(page).fill(q);
      await search(page).press("Enter");
      await page.waitForTimeout(300);
      await expect(page.getByRole("navigation", { name: "Analysis tools" })).toBeVisible();
    }
    expect(dialogs).toBe(0);
    expect(errors).toEqual([]);
  });

  test("U04 coordinate search: invalid rejected, valid recentres", async ({ page }) => {
    await page.goto("/");
    await settle(page);
    await search(page).fill("400 0");
    await search(page).press("Enter");
    await expect(page.getByText(/Enter valid ICRS coordinates/).first()).toBeVisible();
    await search(page).fill("76.95642 30.40142");
    await search(page).press("Enter");
    await expect(page.getByText("76.95642°").first()).toBeVisible();
  });

  test("U05 epoch spam: final image equals a fresh render of the final epoch", async ({ page }) => {
    await page.goto("/");
    await settle(page);
    const eps = ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"];
    for (let i = 0; i < 40; i++) await epochBtn(page, eps[(i * 7) % 4]).click();
    await epochBtn(page, "2026-Q3").click();
    await settle(page);
    const canvas = page.locator("figure canvas").first();
    const spammed = await canvas.evaluate((c: HTMLCanvasElement) => c.toDataURL());
    await page.reload();
    await settle(page);
    await epochBtn(page, "2026-Q3").click();
    await settle(page);
    expect(spammed).toBe(await canvas.evaluate((c: HTMLCanvasElement) => c.toDataURL()));
  });

  test("U06 arrow keys step the epoch", async ({ page }) => {
    await page.goto("/");
    await settle(page);
    await page.locator("body").click({ position: { x: 5, y: 400 } });
    await page.keyboard.press("ArrowRight");
    await expect(epochBtn(page, "2026-Q2")).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("ArrowLeft");
    await expect(epochBtn(page, "2026-Q1")).toHaveAttribute("aria-pressed", "true");
  });

  test("U07 demo-target spam ends on the last clicked target", async ({ page }) => {
    await page.goto("/");
    await settle(page);
    const names = [/WISE 0855/, /RW Aur/, /PX-2026-09/];
    for (let i = 0; i < 12; i++) await pickDemo(page, names[i % 3]);
    await pickDemo(page, /RW Aur/);
    await settle(page);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/RW Aur/);
  });

  test("U08 every tool opens in the inspector, renders without errors, Esc closes", async ({ page }) => {
    const errors = trackErrors(page);
    await page.goto("/");
    await settle(page);
    for (const name of [/Image Difference/, /102-Band Spectrum/, /AI Classification/, /Cross-Match/, /Shift & Stack/, /3D Orbit/, /Candidate Pool/]) {
      await tool(page, name).click();
      await expect(page.getByRole("complementary", { name })).toBeVisible();
      await expect(tool(page, name)).toHaveAttribute("aria-pressed", "true");
      await page.waitForTimeout(1500);
    }
    await page.keyboard.press("Escape");
    await expect(page.getByRole("complementary")).toHaveCount(0);
    expect(errors.filter((e) => e.startsWith("pageerror"))).toEqual([]);
  });

  test("U09 shortcuts: ? help dialog, D / S / 3 toggle tools", async ({ page }) => {
    await page.goto("/");
    await settle(page);
    await page.keyboard.press("?");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.keyboard.press("d");
    await expect(page.getByRole("complementary", { name: "Image Difference" })).toBeVisible();
    await page.keyboard.press("s");
    await expect(page.getByRole("complementary", { name: "Shift & Stack" })).toBeVisible();
    await page.keyboard.press("3");
    await expect(page.getByRole("complementary", { name: "3D Orbit" })).toBeVisible();
    await page.keyboard.press("3");
    await expect(page.getByRole("complementary")).toHaveCount(0);
  });

  test("U10 PX-2026-09: synthetic badge and shift-stack recovers it (S/N > 5)", async ({ page }) => {
    await page.goto("/");
    await settle(page);
    await pickDemo(page, /PX-2026-09/);
    await expect(page.getByText("Synthetic Test Candidate").first()).toBeVisible();
    const stackResp = page.waitForResponse(
      async (r) => r.url().includes("/analysis/shift-stack") && (r.request().postData() ?? "").includes("520"), { timeout: 60_000 });
    await tool(page, /Shift & Stack/).click();
    const body = await (await stackResp).json();
    expect(body.snr_stacked).toBeGreaterThan(5);
  });

  test("U11 phone width: no horizontal scroll, rail at the bottom, tool opens as a sheet", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await settle(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
    const rail = await page.getByRole("navigation", { name: "Analysis tools" }).boundingBox();
    expect(rail!.y + rail!.height).toBeGreaterThan(800);
    await tool(page, /102-Band Spectrum/).click();
    const sheet = await page.getByRole("complementary").boundingBox();
    expect(sheet!.width).toBeGreaterThan(380);
  });

  test("U12 backend offline: page stays usable and labels the mode", async ({ page }) => {
    const errors = trackErrors(page);
    await page.route(`${API}/**`, (r) => r.abort());
    await page.goto("/");
    await expect(page.getByText("Offline Cache").first()).toBeVisible();
    await search(page).fill("WISE 0855");
    await search(page).press("Enter");
    await page.waitForTimeout(1000);
    await tool(page, /102-Band Spectrum/).click();
    await page.waitForTimeout(1500);
    await expect(page.getByRole("navigation", { name: "Analysis tools" })).toBeVisible();
    expect(errors.filter((e) => e.startsWith("pageerror"))).toEqual([]);
  });

  test("U13 colormap cycling changes pixels and never throws", async ({ page }) => {
    const errors = trackErrors(page);
    await page.goto("/");
    await settle(page);
    await page.getByRole("button", { name: "View settings" }).click();
    const canvas = page.locator("figure canvas").first();
    const seen = new Set<string>();
    for (let i = 0; i < 8; i++) {
      await page.getByRole("button", { name: ["Inferno", "Viridis", "Magma", "Grayscale"][i % 4], exact: true }).click();
      seen.add(await canvas.evaluate((c: HTMLCanvasElement) => c.toDataURL()));
    }
    expect(seen.size).toBe(4);
    expect(errors).toEqual([]);
  });

  test("U14 page goes quiet after load (no polling loops, star field is canvas only)", async ({ page }) => {
    const urls: string[] = [];
    await page.goto("/");
    await settle(page);
    await page.waitForTimeout(5000);
    page.on("request", (r) => urls.push(`${r.method()} ${r.url().replace(/\?.*/, "")}`));
    await page.waitForTimeout(10_000);
    expect(urls.length, JSON.stringify(urls)).toBeLessThan(5);
  });

  test("U15 Astro-LLM palette: Ctrl+K opens, TR command flies to the target", async ({ page }) => {
    const errors = trackErrors(page);
    await page.goto("/");
    await settle(page);
    await page.keyboard.press("Control+k");
    await expect(page.getByText("Astro-LLM Copilot Command Palette")).toBeVisible();
    const input = page.getByPlaceholder(/Ask Astro-LLM/);
    await input.fill("RW Aur'a git");
    await input.press("Enter");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/RW Aur/, { timeout: 30_000 });
    expect(errors.filter((e) => e.startsWith("pageerror"))).toEqual([]);
  });

  test("U16 guided tour: three steps, each opens its tool, no errors", async ({ page }) => {
    const errors = trackErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await settle(page);
    await page.getByRole("button", { name: "Guided tour" }).first().click();
    await expect(page.getByText(/Step 1\/3/)).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Image Difference" })).toBeVisible();
    await page.getByRole("button", { name: /Next Step/ }).click();
    await expect(page.getByText(/Step 2\/3/)).toBeVisible();
    await expect(page.getByRole("complementary", { name: "102-Band Spectrum" })).toBeVisible();
    await page.getByRole("button", { name: /Next Step/ }).click();
    await expect(page.getByText(/Step 3\/3/)).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Shift & Stack" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Download Discovery PDF/ })).toBeVisible();
    expect(errors.filter((e) => e.startsWith("pageerror"))).toEqual([]);
  });

  test("U17 PDF discovery report downloads (P shortcut)", async ({ page }) => {
    await page.goto("/");
    await settle(page);
    const dl = page.waitForEvent("download", { timeout: 60_000 });
    await page.keyboard.press("p");
    expect((await dl).suggestedFilename()).toMatch(/AEON_Discovery_Report.*\.pdf$/);
  });

  test("U18 keyboard-only: every rail tool reachable with Tab and has a visible focus ring", async ({ page }) => {
    await page.goto("/");
    await settle(page);
    let reached = 0;
    for (let i = 0; i < 40 && reached < 7; i++) {
      await page.keyboard.press("Tab");
      const info = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el?.closest("nav")) return null;
        return getComputedStyle(el).outlineStyle;
      });
      if (info) {
        reached++;
        expect(info).not.toBe("none");
      }
    }
    expect(reached).toBe(7);
  });
});

test.describe("welcome", () => {
  test("U19 first visit shows the welcome; 'don't show again' persists", async ({ page }) => {
    await page.goto("/");
    const dialog = page.getByRole("dialog", { name: /Find what moves/ });
    await expect(dialog).toBeVisible();
    await page.getByRole("button", { name: "Explore freely" }).click();
    await expect(dialog).toHaveCount(0);
    await page.reload();
    await page.waitForTimeout(1000);
    await expect(page.getByRole("dialog", { name: /Find what moves/ })).toHaveCount(0);
  });
});

/* ---------------- screenshots (always pass; for visual review) ---------------- */
const SIZES = [
  { tag: "desktop", width: 1440, height: 900 },
  { tag: "tablet", width: 1024, height: 768 },
  { tag: "mobile", width: 390, height: 844 },
];

for (const size of SIZES) {
  test(`S-${size.tag} screenshot tour`, async ({ page }) => {
    test.setTimeout(240_000);
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.goto("/");
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${SHOTS}/${size.tag}-01-welcome.png` });
    await page.getByRole("button", { name: "Explore freely" }).click();
    await settle(page);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/${size.tag}-02-home.png` });
    await search(page).click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/${size.tag}-03-search.png` });
    await page.keyboard.press("Escape");
    const tools = size.tag === "desktop"
      ? ["Image Difference", "102-Band Spectrum", "AI Classification", "Cross-Match", "Shift & Stack", "3D Orbit", "Candidate Pool"]
      : ["102-Band Spectrum", "Shift & Stack"];
    let n = 4;
    for (const t of tools) {
      await tool(page, new RegExp(t.replace(/[&]/g, "\\&"))).click();
      await page.waitForTimeout(6000);
      await page.screenshot({ path: `${SHOTS}/${size.tag}-${String(n++).padStart(2, "0")}-${t.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.png` });
    }
    if (size.tag === "desktop") {
      await page.getByRole("button", { name: "Widen panel" }).click();
      await page.waitForTimeout(2500);
      await page.screenshot({ path: `${SHOTS}/${size.tag}-${String(n++).padStart(2, "0")}-wide.png` });
      await page.getByRole("button", { name: "Narrow panel" }).click();
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "Guided tour" }).first().click();
      await page.waitForTimeout(5000);
      await page.screenshot({ path: `${SHOTS}/${size.tag}-${String(n++).padStart(2, "0")}-tour-1.png` });
      await page.getByRole("button", { name: /Next Step/ }).click();
      await page.getByRole("button", { name: /Next Step/ }).click();
      await page.waitForTimeout(6000);
      await page.screenshot({ path: `${SHOTS}/${size.tag}-${String(n++).padStart(2, "0")}-tour-3.png` });
      await page.getByRole("button", { name: /Finish Tour/ }).click();
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "tr", exact: true }).click();
      await page.waitForTimeout(800);
      await page.screenshot({ path: `${SHOTS}/${size.tag}-${String(n++).padStart(2, "0")}-home-tr.png` });
    }
  });
}
