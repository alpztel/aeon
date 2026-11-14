/**
 * AI module in the browser, from easy to torture, against the real stack behind the Nginx gateway
 * (frontend :3000 -> nginx :80 -> ai-engine -> backend). Error paths are injected with page.route;
 * the outage test really stops and restarts the ai-engine container.
 */
import { execSync } from "node:child_process";
import { expect, test, type Page, type Route } from "@playwright/test";

const API = process.env.AEON_API ?? "http://localhost";
const CLASSIFY = `${API}/api/v1/ai/classify`;
const COMPOSE = "docker compose -f ../deploy/docker-compose.yml --profile full";
const SHOTS = "test-results/shots";
const CORS = { "access-control-allow-origin": "http://localhost:3000", "content-type": "application/json" };

const CLASS_LABEL: Record<string, string> = {
  cold_brown_dwarf: "Cold Brown Dwarf",
  planet_x_candidate: "Planet X Candidate",
  young_variable_star: "Young Variable Star",
  main_sequence_star: "Main Sequence Star",
  high_z_galaxy: "High-z Galaxy",
};

function trackErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/aladin|favicon|Failed to load resource|ERR_|net::|CORS/i.test(m.text())) errors.push(`console: ${m.text()}`);
  });
  return errors;
}

async function open(page: Page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("aeon_onboarded_v1", "1");
    } catch {
      /* ignore */
    }
  });
  await page.goto("/");
  await expect(page.getByText("Connecting...")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/WISE/);
}

const search = (page: Page) => page.getByPlaceholder(/Search a target/);
const tool = (page: Page, name: RegExp) => page.getByRole("navigation", { name: "Analysis tools" }).getByRole("button", { name });
const card = (page: Page) => page.locator("[data-ai-state]");
const openClassify = (page: Page) => tool(page, /AI Classification/).click();
const bars = (page: Page) => card(page).locator("span", { hasText: /^\d+%$/ });
const RA: Record<string, number> = { wise: 133.7586977, rw: 76.9564207, px: 51.295473 };
/** Resolves with the classify response that answers the request for the given right ascension. */
const classifyFor = (page: Page, ra: number) =>
  page.waitForResponse((r) => {
    if (r.url() !== CLASSIFY || r.request().method() !== "POST") return false;
    const sent = r.request().postDataJSON() as { ra?: number } | null;
    return typeof sent?.ra === "number" && Math.abs(sent.ra - ra) < 0.3;
  });

async function pickDemo(page: Page, name: RegExp) {
  await search(page).click();
  await page.locator("#aeon-search-suggestions").getByRole("button", { name }).click();
}

function fake(top: string, extra: Record<string, unknown> = {}) {
  const probabilities = Object.fromEntries(Object.keys(CLASS_LABEL).map((c) => [c, c === top ? 0.92 : 0.02]));
  return JSON.stringify({ probabilities, top_class: top, anomaly_score: 0.42, model_versions: { spectral_1d_cnn: "test" },
    spectrum_source: "archive", spectrum_snr_median: 14.2, ...extra });
}

const UNREACHABLE = /AI engine is unreachable right now/;

test.describe("easy: the real engine answers", () => {
  test("A01 classification card shows a real result; the request carries ra and dec", async ({ page }) => {
    const errors = trackErrors(page);
    await open(page);
    const reqP = page.waitForRequest((r) => r.url() === CLASSIFY && r.method() === "POST");
    const resP = page.waitForResponse((r) => r.url() === CLASSIFY && r.request().method() === "POST");
    await openClassify(page);
    const sent = (await reqP).postDataJSON() as { ra?: number; dec?: number };
    expect(typeof sent.ra).toBe("number");
    expect(typeof sent.dec).toBe("number");
    expect(sent.ra).toBeGreaterThan(133.7);
    expect(sent.dec).toBeLessThan(-7.2);
    const res = await resP;
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.spectrum_source).toBe("archive");
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
    await expect(card(page).getByText(`Top Predicted Class: ${CLASS_LABEL[body.top_class]}`)).toBeVisible();
    await expect(card(page).getByText(/Archive spectrum/)).toBeVisible();
    await expect(bars(page)).toHaveCount(5);
    await expect(page.getByText(UNREACHABLE)).toHaveCount(0);
    await expect(page.getByText(/not connected/i)).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/A01-classification.png` });
    expect(errors).toEqual([]);
  });

  test("A02 every demo target gets a classification from the engine", async ({ page }) => {
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
    const seen: string[] = [];
    for (const [name, ra] of [[/RW Aur/, RA.rw], [/PX-2026-09/, RA.px], [/WISE 0855/, RA.wise]] as [RegExp, number][]) {
      const resP = classifyFor(page, ra);
      await pickDemo(page, name);
      const res = await resP;
      expect(res.status()).toBe(200);
      const body = await res.json();
      seen.push(`${name.source}=${body.top_class}`);
      await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
      await expect(card(page).getByText(`Top Predicted Class: ${CLASS_LABEL[body.top_class]}`)).toBeVisible();
    }
    console.log(`AI_CLASSES|${seen.join(" ")}`);
  });

  test("A03 free coordinates are classified or honestly reported as 'no spectrum', never 'unreachable'", async ({ page }) => {
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
    for (const q of ["10 5", "200.5 -45.25", "0.5 89.9", "359.9 -89.9"]) {
      const resP = classifyFor(page, Number(q.split(" ")[0]));
      await search(page).fill(q);
      await search(page).press("Enter");
      expect((await resP).status()).toBe(200);
      await expect(card(page)).toHaveAttribute("data-ai-state", /^(ready|no-spectrum)$/);
      await expect(page.getByText(UNREACHABLE)).toHaveCount(0);
    }
  });

  test("A04 Turkish UI: the card is translated and still classified", async ({ page }) => {
    await open(page);
    await page.getByRole("button", { name: "tr", exact: true }).click();
    await page.getByRole("navigation").getByRole("button", { name: /Yapay Zekâ Sınıflandırma/ }).click();
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
    await expect(card(page).getByText(/Arşiv tayfı/)).toBeVisible();
    await expect(page.getByText(/bağlı değil|ulaşılamıyor/)).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/A04-classification-tr.png` });
  });

  test("A05 Astro-LLM palette is answered by the engine, not by the offline parser", async ({ page }) => {
    await open(page);
    const resP = page.waitForResponse((r) => r.url() === `${API}/api/v1/ai/command`);
    await page.keyboard.press("Control+k");
    const input = page.getByPlaceholder(/Ask Astro-LLM/);
    await input.fill("RW Aur'a git ve tayfı aç");
    await input.press("Enter");
    expect((await resP).status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/RW Aur/, { timeout: 30_000 });
    await expect(page.getByText(/local rule parser|yerel kural motoru/)).toHaveCount(0);
    await expect(page.getByRole("dialog").getByText("Offline Cache")).toHaveCount(0);
  });
});

test.describe("medium: error paths", () => {
  test("A06 gateway 503: one automatic retry, then 'unreachable' with a Retry button that recovers", async ({ page }) => {
    const errors = trackErrors(page);
    let calls = 0;
    let broken = true;
    await page.route(CLASSIFY, (route: Route) => {
      calls++;
      return broken ? route.fulfill({ status: 503, headers: CORS, body: '{"detail":"upstream down"}' }) : route.continue();
    });
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "unreachable");
    await expect(card(page).getByRole("alert")).toHaveText(UNREACHABLE);
    expect(calls).toBe(2);
    await page.screenshot({ path: `${SHOTS}/A06-unreachable.png` });
    broken = false;
    await card(page).getByRole("button", { name: "Retry" }).click();
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
    await expect(card(page).getByRole("alert")).toHaveCount(0);
    expect(calls).toBe(3);
    expect(errors).toEqual([]);
  });

  test("A07 first attempt fails, the automatic retry succeeds: the user never sees an error", async ({ page }) => {
    let calls = 0;
    await page.route(CLASSIFY, (route: Route) => (++calls === 1 ? route.fulfill({ status: 502, headers: CORS, body: "<html>bad gateway</html>" }) : route.continue()));
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
    expect(calls).toBe(2);
    await expect(page.getByText(UNREACHABLE)).toHaveCount(0);
  });

  test("A08 a rejected request (422) is shown as rejected with its reason, not as an outage, and is not retried", async ({ page }) => {
    let calls = 0;
    await page.route(CLASSIFY, (route: Route) => {
      calls++;
      return route.fulfill({ status: 422, headers: CORS, body: JSON.stringify({ detail: [{ type: "value_error", loc: ["body"], msg: "Value error, Provide at least one of flux_ujy (102 bands), image, or (ra, dec)" }] }) });
    });
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "rejected");
    await expect(card(page).getByRole("alert")).toContainText("The AI engine rejected this request: Value error, Provide at least one of");
    await expect(page.getByText(UNREACHABLE)).toHaveCount(0);
    await page.waitForTimeout(2500);
    expect(calls).toBe(1);
    await page.screenshot({ path: `${SHOTS}/A08-rejected.png` });
  });

  test("A09 slow engine: 'Classifying…' is shown, then the result", async ({ page }) => {
    await page.route(CLASSIFY, async (route: Route) => {
      await new Promise((r) => setTimeout(r, 3000));
      await route.fulfill({ status: 200, headers: CORS, body: fake("young_variable_star") });
    });
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "loading");
    await expect(card(page).getByText("Classifying…")).toBeVisible();
    await expect(card(page)).toHaveAttribute("aria-busy", "true");
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
    await expect(card(page).getByText("Top Predicted Class: Young Variable Star")).toBeVisible();
    await expect(card(page).getByText("Classifying…")).toHaveCount(0);
  });

  test("A10 network failure (connection refused) -> unreachable -> Retry recovers", async ({ page }) => {
    let broken = true;
    await page.route(CLASSIFY, (route: Route) => (broken ? route.abort("connectionrefused") : route.continue()));
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "unreachable");
    broken = false;
    await card(page).getByRole("button", { name: "Retry" }).click();
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
  });

  test("A11 no spectrum at the position: says so and shows no probabilities", async ({ page }) => {
    await page.route(CLASSIFY, (route: Route) => route.fulfill({ status: 200, headers: CORS,
      body: fake("main_sequence_star", { spectrum_source: "none", spectrum_snr_median: null, probabilities: Object.fromEntries(Object.keys(CLASS_LABEL).map((c) => [c, 0.2])) }) }));
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "no-spectrum");
    await expect(card(page).getByText("No usable spectrum at this position — nothing was classified.")).toBeVisible();
    await expect(card(page).getByText(/Top Predicted Class/)).toHaveCount(0);
    await expect(bars(page)).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/A11-no-spectrum.png` });
  });

  test("A11b spectrum service down or too slow: says so, Retry classifies", async ({ page }) => {
    let down = true;
    await page.route(CLASSIFY, (route: Route) => (down
      ? route.fulfill({ status: 200, headers: CORS, body: fake("main_sequence_star", { spectrum_source: "unavailable", spectrum_snr_median: null }) })
      : route.continue()));
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "spectrum-unavailable");
    await expect(card(page).getByRole("alert")).toContainText("The spectrum service is not answering right now");
    await expect(card(page).getByText(/Top Predicted Class/)).toHaveCount(0);
    await expect(bars(page)).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/A11b-spectrum-unavailable.png` });
    down = false;
    await card(page).getByRole("button", { name: "Retry" }).click();
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
  });

  test("A12 low S/N spectrum carries a caution", async ({ page }) => {
    await page.route(CLASSIFY, (route: Route) => route.fulfill({ status: 200, headers: CORS, body: fake("planet_x_candidate", { spectrum_snr_median: 0.4 }) }));
    await open(page);
    await openClassify(page);
    await expect(card(page).getByText(/low median S\/N/)).toBeVisible();
    await expect(card(page).getByText(/median S\/N 0\.4/)).toBeVisible();
  });
});

test.describe("hard: hostile and broken answers", () => {
  const BROKEN: [string, { status: number; body: string }, RegExp][] = [
    ["html with 200", { status: 200, body: "<html>oops</html>" }, /^unreachable$/],
    ["empty body", { status: 200, body: "" }, /^unreachable$/],
    ["truncated json", { status: 200, body: '{"probabilities": {"cold_brown_dwarf": 0.9' }, /^unreachable$/],
    ["empty object", { status: 200, body: "{}" }, /^unreachable$/],
    ["json null", { status: 200, body: "null" }, /^unreachable$/],
    ["json array", { status: 200, body: "[1,2,3]" }, /^unreachable$/],
    ["probabilities is a string", { status: 200, body: '{"probabilities":"high","top_class":"cold_brown_dwarf"}' }, /^unreachable$/],
    ["old engine without spectrum_source", { status: 200, body: JSON.stringify({ probabilities: { cold_brown_dwarf: 0.9, planet_x_candidate: 0.1 }, top_class: "cold_brown_dwarf", anomaly_score: 0.7, physics_diagnostics: { teff_k: 300 } }) }, /^ready$/],
    ["old engine, no spectrum", { status: 200, body: JSON.stringify({ probabilities: { cold_brown_dwarf: 0.2 }, top_class: "main_sequence_star", anomaly_score: 0.1, physics_diagnostics: null }) }, /^no-spectrum$/],
    ["unknown class and wild numbers", { status: 200, body: JSON.stringify({ probabilities: { cold_brown_dwarf: 1e308, planet_x_candidate: -5, bogus: "x", young_variable_star: null },
      top_class: "<img src=x onerror=alert(1)>", anomaly_score: 99, model_versions: { "<b>x</b>": "<script>alert(1)</script>" }, spectrum_source: "archive", spectrum_snr_median: "high" }) }, /^ready$/],
    ["500 with html", { status: 500, body: "<html>Internal Server Error</html>" }, /^unreachable$/],
    ["429", { status: 429, body: '{"detail":"Too many requests"}' }, /^rejected$/],
    ["404", { status: 404, body: '{"detail":"Not Found"}' }, /^rejected$/],
    ["413 detail object", { status: 413, body: '{"detail":{"a":1}}' }, /^rejected$/],
  ];

  for (const [name, answer, state] of BROKEN) {
    test(`A13 broken answer (${name}) never crashes the page`, async ({ page }) => {
      const errors = trackErrors(page);
      let dialogs = 0;
      page.on("dialog", (d) => { dialogs++; void d.dismiss(); });
      await page.route(CLASSIFY, (route: Route) => route.fulfill({ status: answer.status, headers: CORS, body: answer.body }));
      await open(page);
      await openClassify(page);
      await expect(card(page)).toHaveAttribute("data-ai-state", state, { timeout: 30_000 });
      await expect(tool(page, /AI Classification/)).toBeVisible();
      await tool(page, /102-Band Spectrum/).click();          // the rest of the app still works
      await expect(page.getByRole("complementary", { name: "102-Band Spectrum" })).toBeVisible();
      expect(dialogs).toBe(0);
      expect(errors).toEqual([]);
    });
  }

  test("A14 engine hangs: the request times out and the card says unreachable", async ({ page }) => {
    await page.route(CLASSIFY, () => { /* never answered */ });
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "loading");
    await expect(card(page)).toHaveAttribute("data-ai-state", "unreachable", { timeout: 25_000 });
  });

  test("A15 a slow answer for an earlier target never overwrites the current target", async ({ page }) => {
    await page.route(CLASSIFY, async (route: Route) => {
      const { ra } = route.request().postDataJSON() as { ra: number };
      const wise = Math.abs(ra - 133.76) < 0.5;
      await new Promise((r) => setTimeout(r, wise ? 3500 : 150));
      await route.fulfill({ status: 200, headers: CORS, body: fake(wise ? "cold_brown_dwarf" : "young_variable_star") }).catch(() => {});
    });
    await open(page);
    await openClassify(page);                                   // WISE: answer in 3.5 s
    await pickDemo(page, /RW Aur/);                             // RW Aur: answer in 0.15 s
    await expect(card(page).getByText("Top Predicted Class: Young Variable Star")).toBeVisible();
    await page.waitForTimeout(4500);                            // the late WISE answer arrives now
    await expect(card(page).getByText("Top Predicted Class: Young Variable Star")).toBeVisible();
    await expect(card(page).getByText("Top Predicted Class: Cold Brown Dwarf")).toHaveCount(0);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/RW Aur/);
  });
});

test.describe("torture: spam and a real outage", () => {
  test("A16 target spam with the real engine: last target wins, no errors, requests stay bounded", async ({ page }) => {
    const errors = trackErrors(page);
    let calls = 0;
    page.on("request", (r) => { if (r.url() === CLASSIFY && r.method() === "POST") calls++; });
    await open(page);
    await openClassify(page);
    const names = [/RW Aur/, /PX-2026-09/, /WISE 0855/];
    for (let i = 0; i < 30; i++) await pickDemo(page, names[i % 3]);
    const resP = classifyFor(page, RA.rw);                      // the loop ended on WISE
    await pickDemo(page, /RW Aur/);
    const body = await (await resP).json();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/RW Aur/);
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
    await expect(card(page).getByText(`Top Predicted Class: ${CLASS_LABEL[body.top_class]}`)).toBeVisible();
    expect(calls).toBeLessThanOrEqual(40);
    expect(errors).toEqual([]);
  });

  test("A17 twenty Retry rounds while the engine is down, then recovery", async ({ page }) => {
    test.setTimeout(180_000);
    const errors = trackErrors(page);
    let broken = true;
    await page.route(CLASSIFY, (route: Route) => (broken ? route.fulfill({ status: 504, headers: CORS, body: "" }) : route.continue()));
    await open(page);
    await openClassify(page);
    for (let i = 0; i < 20; i++) {
      const btn = card(page).getByRole("button", { name: "Retry" });
      await btn.click({ timeout: 15_000 });
    }
    // let the last round finish failing before the engine "comes back" (its auto-retry would otherwise succeed)
    await expect(card(page)).toHaveAttribute("data-ai-state", "unreachable", { timeout: 15_000 });
    broken = false;
    await card(page).getByRole("button", { name: "Retry" }).click({ timeout: 15_000 });
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");
    expect(errors).toEqual([]);
  });

  test("A18 the ai-engine container is stopped mid-session and restarted", async ({ page }) => {
    test.setTimeout(240_000);
    const errors = trackErrors(page);
    await open(page);
    await openClassify(page);
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready");

    execSync(`${COMPOSE} stop ai-engine`, { stdio: "inherit" });
    try {
      await pickDemo(page, /RW Aur/);
      await expect(card(page)).toHaveAttribute("data-ai-state", "unreachable", { timeout: 60_000 });
      await expect(card(page).getByRole("alert")).toHaveText(UNREACHABLE);
      await page.screenshot({ path: `${SHOTS}/A18-engine-down.png` });
      // the rest of the site keeps working without the engine
      await tool(page, /102-Band Spectrum/).click();
      await expect(page.getByRole("complementary", { name: "102-Band Spectrum" })).toBeVisible();
      // the command palette falls back to the local parser and still flies to the target
      await page.keyboard.press("Control+k");
      const input = page.getByPlaceholder(/Ask Astro-LLM/);
      await input.fill("WISE 0855'e git");
      await input.press("Enter");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(/WISE/, { timeout: 40_000 });
      await page.keyboard.press("Escape");
    } finally {
      execSync(`${COMPOSE} start ai-engine`, { stdio: "inherit" });
    }
    await expect.poll(async () => {
      try {
        const r = await page.request.post(CLASSIFY, { data: { ra: 133.7586977, dec: -7.2420576 }, timeout: 10_000 });
        return r.status();
      } catch {
        return 0;
      }
    }, { timeout: 120_000, intervals: [2000] }).toBe(200);

    await openClassify(page);
    await expect(card(page)).not.toHaveAttribute("data-ai-state", "loading", { timeout: 30_000 });
    const state = await card(page).getAttribute("data-ai-state");
    if (state !== "ready") await card(page).getByRole("button", { name: "Retry" }).click();
    await expect(card(page)).toHaveAttribute("data-ai-state", "ready", { timeout: 30_000 });
    await page.screenshot({ path: `${SHOTS}/A18-engine-back.png` });
    expect(errors.filter((e) => e.startsWith("pageerror"))).toEqual([]);
  });
});
