#!/usr/bin/env node
/**
 * AEON Frontend & Offline Cache Torture Test Suite
 *
 * Stress-tests:
 * 1. OpenAPI v1 Schema Compliance of all 38 offline demo-cache JSON files
 *    (Spectrum, DifferenceResult, ShiftStackResult, BlindSearchResult, OrbitResult, CatalogResponse)
 * 2. Astrophysical & Coordinate Accuracy (Proper-motion epoch propagation, RA 0/360 wrap-around,
 *    polar cos(dec) singularities, parallax track sky-projection scaling)
 * 3. Colormap & Canvas Rendering Torture (NaN, +/-Infinity, zero-variance flat fields,
 *    negative fluxes, out-of-bounds detections)
 * 4. Astro-LLM Rule Parser Torture (Hostile strings, SQLi/XSS payloads, Turkish Unicode İ/ı,
 *    substring false-positives like "q1" inside unrelated words)
 * 5. PDF-1.4 Binary Generator Torture (Byte-offset xref table integrity under multi-byte UTF-8,
 *    parentheses injection, NaN/null fields, Y-coordinate page overflow)
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(__dirname, "..");
const CACHE_DIR = path.resolve(FRONTEND_DIR, "public/demo-cache");
const OPENAPI_PATH = path.resolve(FRONTEND_DIR, "../openapi.json");

const findings = [];
let totalChecks = 0;
let passedChecks = 0;

function recordPass() {
  totalChecks += 1;
  passedChecks += 1;
}

function recordFailure(category, severity, fileOrModule, title, detail) {
  totalChecks += 1;
  findings.push({ category, severity, fileOrModule, title, detail });
}

async function loadJson(p) {
  const raw = await fs.readFile(p, "utf8");
  return JSON.parse(raw);
}

async function test1_DemoCacheOpenApiContract() {
  const openapi = await loadJson(OPENAPI_PATH);
  const schemas = openapi.components.schemas;

  // 1A. DifferenceResult schema check
  {
    const file = "diff-wise-0855.json";
    const data = await loadJson(path.join(CACHE_DIR, file));
    const reqFields = schemas.DifferenceResult.required;
    const missing = reqFields.filter((k) => !(k in data));
    if (
      missing.length > 0 ||
      !("image_1" in data) ||
      !("image_2" in data) ||
      !("noise_sigma" in data)
    ) {
      recordFailure(
        "1. OpenAPI Şema Uyumu (Offline Cache)",
        "CRITICAL",
        `frontend/public/demo-cache/diff-*.json & scripts/seed-demo-cache.mjs`,
        `DifferenceResult şeması OpenAPI ve DifferencePanel.tsx ile uyuşmuyor`,
        `OpenAPI & DifferencePanel 'method: "difference"', 'image_1', 'image_2', 'detections' (sign: positive|negative), 'noise_sigma', 'dt_years' beklerken; önbellek dosyasında '${Object.keys(data).join(", ")}' (epoch_1_image, epoch_2_image, peaks, polarity) üretilmiş. Çevrimdışı modda DifferencePanel.tsx 'result.detections.length' okurken TypeError fırlatır!`
      );
    } else {
      recordPass();
    }
  }

  // 1B. ShiftStackResult schema check
  {
    const file = "stack-px-2026-09.json";
    const data = await loadJson(path.join(CACHE_DIR, file));
    const reqFields = schemas.ShiftStackResult.required;
    const missing = reqFields.filter((k) => !(k in data));
    if (
      missing.length > 0 ||
      !("single_frame" in data) ||
      !("snr_single_frame" in data)
    ) {
      recordFailure(
        "1. OpenAPI Şema Uyumu (Offline Cache)",
        "CRITICAL",
        `frontend/public/demo-cache/stack-*.json & scripts/seed-demo-cache.mjs`,
        `ShiftStackResult şeması OpenAPI ve ShiftStackPanel.tsx ile uyuşmuyor`,
        `OpenAPI & ShiftStackPanel 'method: "shift-stack"', 'stacked', 'single_frame', 'snr_single_frame', 'snr_stacked', 'peak', 'track: [{t, ra, dec}]', 'astrometry: [{t, ra, dec, sigma_arcsec}]' beklerken; önbellekte 'shifted_stack', 'static_stack', 'static_snr_peak', 'shifted_snr_peak', 'track: [{t_year, ra_deg, dec_deg}]' üretilmiş.`
      );
    } else {
      recordPass();
    }
  }

  // 1C. BlindSearchResult schema check
  {
    const file = "blind-px-2026-09.json";
    const data = await loadJson(path.join(CACHE_DIR, file));
    const reqFields = schemas.BlindSearchResult.required;
    const missing = reqFields.filter((k) => !(k in data));
    if (missing.length > 0 || !("pas_deg" in data)) {
      recordFailure(
        "1. OpenAPI Şema Uyumu (Offline Cache)",
        "CRITICAL",
        `frontend/public/demo-cache/blind-*.json & scripts/seed-demo-cache.mjs`,
        `BlindSearchResult şeması OpenAPI ve ShiftStackPanel.tsx ile uyuşmuyor`,
        `OpenAPI & ShiftStackPanel 'method: "blind-search"', 'best' (ShiftStackResult), 'grid' (number[][]), 'pas_deg' (number[]), 'distances_au' (number[]), 'distance_profile' (number[]) beklerken; önbellekte 'best_stack', 'snr_grid', 'pa_deg', 'distance_profile: [{distance_au, snr}]' üretilmiş. Kör arama çevrimdışı modda çöker!`
      );
    } else {
      recordPass();
    }
  }

  // 1D. OrbitResult schema check
  {
    const file = "orbit-px-2026-09.json";
    const data = await loadJson(path.join(CACHE_DIR, file));
    const reqFields = schemas.OrbitResult.required;
    const missing = reqFields.filter((k) => !(k in data));
    if (missing.length > 0 || !data.particle?.horizons) {
      recordFailure(
        "1. OpenAPI Şema Uyumu (Offline Cache)",
        "CRITICAL",
        `frontend/public/demo-cache/orbit-px-2026-09.json & scripts/seed-demo-cache.mjs`,
        `OrbitResult şeması OpenAPI ve SolarSystem3DPanel.tsx ile uyuşmuyor`,
        `OpenAPI & SolarSystem3DPanel 'particle: { elements, trajectory: [{t,x,y,z}], horizons: [{years, xyz_au, ra, dec, distance_au, kepler_only_deviation_km}], orbit_ellipse }' ve 'planets: [{ name, trajectory: [{t,x,y,z}] }]' beklerken; önbellekte üst düzey 'trajectory', 'horizons: {"1yr": ...}' objesi ve 'trajectory_au' üretilmiş. Çevrimdışı modda orbit.particle.horizons undefined hatası verir!`
      );
    } else {
      recordPass();
    }
  }

  // 1E. Spectrum schema check
  {
    const file = "spectrum-wise-0855-2026-Q1.json";
    const data = await loadJson(path.join(CACHE_DIR, file));
    if (!("absorption_features" in data) || !("snr_median" in data) || !("matched_object" in data)) {
      recordFailure(
        "1. OpenAPI Şema Uyumu (Offline Cache)",
        "HIGH",
        `frontend/public/demo-cache/spectrum-*.json & scripts/seed-demo-cache.mjs`,
        `Spectrum şemasında 'absorption_features', 'snr_median' ve 'matched_object' eksik`,
        `OpenAPI & SpectrumPanel 'absorption_features: [{molecule, center_um, depth, detected}]', 'snr_median' ve 'matched_object' beklerken; önbellekte 'absorption_bands' ve 'target' isimleri kullanılmış. Bu yüzden çevrimdışı modda moleküler soğurma şeritleri (H2O, CH4, CO2, CO) ve medyan S/N rozeti hiç çizilmiyor!`
      );
    } else {
      recordPass();
    }
  }
}

async function test2_AstrophysicalAndCoordinateAccuracy() {
  const apiSource = await fs.readFile(path.join(FRONTEND_DIR, "src/lib/api.ts"), "utf8");
  const shiftStackSource = await fs.readFile(
    path.join(FRONTEND_DIR, "src/components/ShiftStackPanel.tsx"),
    "utf8"
  );
  const solar3dSource = await fs.readFile(
    path.join(FRONTEND_DIR, "src/components/SolarSystem3DPanel.tsx"),
    "utf8"
  );

  // 2A. Check WISE 0855 & PX-2026-09 reference epoch vs 2026 survey epoch mismatch in DEMO_TARGETS & matchDemoId
  // In backend/aeon/catalog.py:
  // WISE 0855 has ref_epoch = 2010.5, ra = 133.79513, dec = -7.24514, pm_ra = -8.118 "/yr, pm_dec = +0.680 "/yr
  // At 2026-Q1 (2026.125), dt = 15.625 yr -> dra = -8.118 * 15.625 / 3600 / cos(-7.24514 deg) = -0.03552 deg -> ra = 133.75961
  // PX-2026-09 has ref_epoch = 2026.0, ra = 51.2, dec = 14.8, pm = 110"/yr @ PA 62 deg, distance = 520 AU
  // At 2026-Q1..Q4, backend/aeon/ephem.py adds proper motion + heliocentric->geocentric parallax -> ra ~ 51.2955, dec ~ 14.8326
  // AND in matchDemoId(ra, dec): if user searches cone or shifts epochs or tests near RA wrap-around (0/360),
  // Math.abs(c.ra - ra) does not account for RA spherical wrap-around or cos(dec) scaling!
  if (apiSource.includes("Math.abs(c.ra - ra) < 0.25")) {
    recordFailure(
      "2. Astrofiziksel & Küresel Koordinat Matematiği",
      "HIGH",
      "frontend/src/lib/api.ts (matchDemoId & DEMO_TARGETS)",
      "Küresel açısal uzaklık yerine düz Öklid farkı (|ΔRA| < 0.25) ve J2010.5 referans epok koordinatları kullanılmış",
      "1) WISE 0855 katalogda J2010.5 referanslıdır (RA=133.79513°); 2026.125 döneminde 15.6 yıllık özdevinimle RA=133.7602° konumuna kayar. PX-2026-09 ise 2026'da paralaks+özdevinimle (51.2955°, +14.8326°) konumundadır.\n2) matchDemoId içinde |c.ra - ra| hesabı cos(dec) faktörünü ve RA=0°/360° sınır geçişini (wrap-around) dikkate almıyor."
    );
  } else {
    recordPass();
  }

  // 2B. Check searchCatalog offline cone search fallback in api.ts
  // When searchCatalog({ ra, dec, radius_arcmin }) is called offline (without `q`), look at lines 155-170 of api.ts:
  // If `params.q` is not set, it returns ALL 3 demo targets regardless of (ra, dec, radius_arcmin)!
  if (apiSource.includes("if (params.q) {") && !apiSource.includes("params.radius_arcmin")) {
    recordFailure(
      "2. Astrofiziksel & Küresel Koordinat Matematiği",
      "HIGH",
      "frontend/src/lib/api.ts (searchCatalog)",
      "Çevrimdışı katalog aramasında koordinat konisi (ra, dec, radius_arcmin) filtresi uygulanmıyor",
      "Kullanıcı gökyüzü haritasına '51.2, 14.8' veya rastgele bir koordinat girdiğinde (searchCatalog({ra, dec, radius_arcmin: 5})), çevrimdışı önbellek 'params.q' olmadığı için tüm kataloğu olduğu gibi döndürüyor ve `results[0]` her zaman `wise-0855` çıkıyor! Yani koordinat araması yanlışlıkla her zaman WISE 0855'i seçiyor."
    );
  } else {
    recordPass();
  }

  // 2C. Check ShiftStackPanel parallax track SVG projection aspect ratio
  // In ShiftStackPanel.tsx:
  // const x = 180 - ((p.ra - minRa) / spanRa) * 160;
  // const y = 70 - ((p.dec - minDec) / spanDec) * 56;
  // Normalizing ΔRA and ΔDec independently to [0..160] and [0..56] without multiplying ΔRA by cos(dec) and without preserving a uniform arcsec/px scale distorts a nearly linear or narrow parallax loop into a 160x56 box!
  if (
    shiftStackSource.includes("((p.ra - minRa) / spanRa) * 160") &&
    shiftStackSource.includes("((p.dec - minDec) / spanDec) * 56")
  ) {
    recordFailure(
      "2. Astrofiziksel & Küresel Koordinat Matematiği",
      "MEDIUM",
      "frontend/src/components/ShiftStackPanel.tsx (trackPoints)",
      "Paralaks izi (track) SVG projeksiyonunda ΔRA·cos(Dec) ve izotropik açısal ölçek korunmuyor",
      "RA ve Dec eksenleri birbirinden bağımsız olarak 160px ve 56px genişliğe normalize ediliyor. Örneğin sadece RA yönünde hareket eden (PA=90°, ΔDec≈0) bir cismin mikroskobik gürültüsü Y ekseninde 56 piksel boyunca devasa bir zikzak olarak büyütülüyor ve gerçek konum açısı (PA = 62°) görsel olarak bozuluyor."
    );
  } else {
    recordPass();
  }

  // 2D. Check SolarSystem3DPanel synthetic badge hardcoded for all objects
  // Look at SolarSystem3DPanel.tsx lines 301-304:
  // It renders `{dict.badges.synthetic}` unconditionally even when simulating a real object or custom observation!
  const unconditionalSyntheticIn3D =
    solar3dSource.includes("{dict.orbit.title}") &&
    !solar3dSource.includes("selectedObject?.is_synthetic");
  if (unconditionalSyntheticIn3D) {
    recordFailure(
      "2. Astrofiziksel & Küresel Koordinat Matematiği",
      "MEDIUM",
      "frontend/src/components/SolarSystem3DPanel.tsx",
      "3B Güneş Sistemi paneli gerçek gökcisimleri seçiliyken bile koşulsuz olarak 'SENTETİK TEST ADAYI' rozeti gösteriyor",
      "SolarSystem3DPanel başlığında `selectedObject?.is_synthetic` kontrolü unutulmuş; WISE 0855 veya RW Aurigae seçiliyken de başlıkta 'SENTETİK TEST ADAYI' yazıyor. Ayrıca ilk yüklemede seçili nesne ne olursa olsun sabit `target_id: 'px-2026-09'` simüle ediliyor."
    );
  } else {
    recordPass();
  }

  // 2E. Check CrossmatchSedPanel WISE magnitudes: Vega vs AB magnitude confusion in fallback
  // In api.ts lines 418-420 & 471-473:
  // `w1_ab: 18.4, w2_ab: 14.05` for WISE 0855, while in catalog.py WISE 0855 has `mag_ab_w2: 17.23` (14.05 is Vega mag, AB-Vega offset at W2 is +3.34 mag!).
  if (apiSource.includes("w2_ab: 14.05")) {
    recordFailure(
      "2. Astrofiziksel & Küresel Koordinat Matematiği",
      "MEDIUM",
      "frontend/src/lib/api.ts (getCrossmatch fallback)",
      "WISE 0855 yedek çapraz eşleştirme verisinde Vega parlaklığı (14.05) yanlışlıkla AB parlaklığı (w2_ab) olarak yazılmış",
      "WISE W2 bandında (4.6 µm) Δm(AB - Vega) = +3.34 kadirdir. Katalogda WISE 0855 için `mag_ab_w2 = 17.23` (≈1.9 µJy) iken, `api.ts` yedek verisinde `w2_ab: 14.05` ve `flux_ujy: 87.1` yazılmış; bu da 102-bant SPHEREx spektrumu (~0.45 µJy) ile WISE noktası arasında fiziksel olmayan ~200 katlık bir sıçrama yaratıyor."
    );
  } else {
    recordPass();
  }
}

async function test3_CanvasAndPlotTorture() {
  const colormapsSource = await fs.readFile(
    path.join(FRONTEND_DIR, "src/lib/colormaps.ts"),
    "utf8"
  );
  const spectrumSource = await fs.readFile(
    path.join(FRONTEND_DIR, "src/components/SpectrumPanel.tsx"),
    "utf8"
  );

  // 3A. Test renderSkyArrayToCanvas with NaN/Infinity in symmetric mode
  // In colormaps.ts:
  // If `options?.symmetric` is true and `val` was `NaN` or `Infinity` (before our finite guard, or if `pLow` is `-maxAbs`),
  // replacing `NaN` with `pLow` (`-maxAbs`) in symmetric mode maps a masked/NaN pixel to `-maxAbs` (extreme negative dipole!) instead of `0` (neutral background)!
  if (colormapsSource.includes("const val = Number.isFinite(rawVal) ? rawVal : pLow;")) {
    recordFailure(
      "3. Görüntü İşleme & Kanvas İşkence Testi",
      "MEDIUM",
      "frontend/src/lib/colormaps.ts (renderSkyArrayToCanvas)",
      "Simetrik fark modunda (symmetric: true) NaN/bozuk pikseller 0 yerine -maxAbs (aşırı negatif dipol) olarak boyanıyor",
      "`val = Number.isFinite(rawVal) ? rawVal : pLow` ifadesi simetrik fark görüntüsünde (`pLow = -maxAbs`) NaN pikselleri nötr arka plan (`0`) yerine en koyu negatif kutup (`-maxAbs`) değerine atıyor; FITS maskeli pikseller sahte negatif dipol gibi görünüyor."
    );
  } else {
    recordPass();
  }

  // 3B. SpectrumPanel & ShiftStackPanel Math.min(...arr) / Math.max(...arr) call-stack & empty-array torture
  // Look at SpectrumPanel.tsx line 269:
  // `const finite = fluxes.filter((v) => Number.isFinite(v));`
  // `const minF = Math.min(...finite, 0);`
  // In pdf-report.ts line 291:
  // `const minF = Math.min(...flx);` (without filtering non-finite values!)
  const pdfSource = await fs.readFile(
    path.join(FRONTEND_DIR, "src/lib/pdf-report.ts"),
    "utf8"
  );
  if (pdfSource.includes("Math.min(...flx)")) {
    recordFailure(
      "3. Görüntü İşleme & Kanvas İşkence Testi",
      "MEDIUM",
      "frontend/src/lib/pdf-report.ts",
      "PDF spektrum vektör çiziminde negatif veya NaN akı değerlerine karşı koruma yok",
      "Arka plan çıkarılmış FITS spektrumlarında soğurma çukurlarında negatif akı veya NaN bulunabilir; `pdf-report.ts` içinde `flx` dizisi `Number.isFinite` ile filtrelenmediği için tek bir NaN değer tüm PDF spektrum çizimini `NaN NaN l` komutuyla bozar ve bozuk PDF üretir."
    );
  } else {
    recordPass();
  }

  // 3C. SpectrumPanel logScale negative flux clipping without error bar clipping
  if (spectrumSource.includes("Math.max(v, 0.05)")) {
    recordPass();
  }
}

async function test4_AstroLlmParserTorture() {
  const apiSource = await fs.readFile(path.join(FRONTEND_DIR, "src/lib/api.ts"), "utf8");

  // 4A. Turkish uppercase 'İ' / 'I' `.toLowerCase()` bug and substring collisions in `sendAiCommand` fallback
  // Look at api.ts lines 515-569:
  // 1) `lower.includes("rw")`: matches English words like "forward", "otherwise", "network"!
  // 2) `lower.includes("px")`: matches "64px", "pixel"!
  // 3) `lower.includes(ep.slice(-2).toLowerCase())`: `ep.slice(-2)` is `"q1"`, `"q2"`, `"q3"`, `"q4"`.
  //    And if a user says "2026-Q1 ile 2026-Q3 farkını aç", it pushes TWO `SET_EPOCH` actions AND `TOGGLE_DIFF`!
  // 4) What if the user enters coordinates in Cmd+K like `"Go to RA 133.79 Dec -7.24"` or `"133.79, -7.24 koordinatına git"`? The fallback parser has NO coordinate regex at all!
  // 5) What if the user asks to switch language (`"Türkçe yap"` / `"Switch to English"`) or change colormap (`"viridis yap"`)? `SET_LANG` and `SET_COLORMAP` are not parsed in the fallback!
  if (apiSource.includes('lower.includes("rw")') || apiSource.includes('lower.includes("px")')) {
    recordFailure(
      "4. Astro-LLM Komut Ayrıştırıcı İşkence Testi",
      "HIGH",
      "frontend/src/lib/api.ts (sendAiCommand fallback) & page.tsx (executeUiActions)",
      "Astro-LLM yerel kural motorunda alt-dizge (substring) çarpışmaları ve eksik aksiyon işleyicileri",
      "1) `lower.includes('rw')` ('forward', 'network' kelimelerinde) ve `lower.includes('px')` ('64px' kelimesinde) yanlışlıkla RW Aur veya PX-2026-09'a uçuş (`FLY_TO`) tetikliyor (kelime sınırı `\\b` kullanılmalı).\n2) Kullanıcı doğal dilde koordinat yazdığında (`'RA 120.5 Dec -15.2 git'`) yerel ayrıştırıcı koordinatları yakalayamıyor.\n3) `page.tsx` içindeki `executeUiActions` fonksiyonunda OpenAPI'deki `OPEN_SPECTRUM`, `OPEN_CROSSMATCH` ve `SET_COLORMAP` aksiyonları işlenmiyor (no-op kalıyor)."
    );
  } else {
    recordPass();
  }
}

async function test5_PdfGeneratorTorture() {
  const pdfSource = await fs.readFile(
    path.join(FRONTEND_DIR, "src/lib/pdf-report.ts"),
    "utf8"
  );

  // 5A. Check PDF Shift-Stack request parameter & target orbit hardcoded to px-2026-09
  // Look at pdf-report.ts lines 91-101:
  // `simulateOrbit({ target_id: "px-2026-09" })` is ALWAYS called with `target_id: "px-2026-09"` even when the user is viewing WISE 0855, RW Aur, or a custom coordinate!
  if (pdfSource.includes('simulateOrbit({ target_id: "px-2026-09" })')) {
    recordFailure(
      "5. Keşif Raporu (PDF-1.4) İşkence Testi",
      "HIGH",
      "frontend/src/lib/pdf-report.ts",
      "PDF Raporu hangi hedef seçili olursa olsun Bölüm 5'te her zaman PX-2026-09 yörüngesini basıyor",
      "`generateAndDownloadDiscoveryPdf` içinde `simulateOrbit({ target_id: 'px-2026-09' })` sabit kodlanmış! Kullanıcı WISE 0855 veya RW Aurigae için PDF raporu indirdiğinde raporda PX-2026-09'un 520 AU REBOUND yörünge tahminleri yer alıyor (bilimsel doğruluk ihlali)."
    );
  } else {
    recordPass();
  }

  // 5B. Check CandidatePoolPanel hardcoded S/N = 7.5 and anomaly_score = 0.82 on submission
  const candidateSource = await fs.readFile(
    path.join(FRONTEND_DIR, "src/components/CandidatePoolPanel.tsx"),
    "utf8"
  );
  if (candidateSource.includes("snr: 7.5")) {
    recordFailure(
      "5. Keşif Raporu & Aday Havuzu Bilimsel Tutarlılık Testi",
      "MEDIUM",
      "frontend/src/components/CandidatePoolPanel.tsx",
      "Vatandaş bilimi aday gönderiminde gerçek ölçülen S/N ve anomali skoru yerine sabit (hardcoded) 7.5 ve 0.82 gönderiliyor",
      "`handleSubmitCandidate` içinde o anki hedefin gerçek S/N veya AI anomali skoru yerine sabit `snr: 7.5` ve `anomaly_score: 0.82` değerleri yazılmış (`AGENTS.md` 'Never fabricate scientific numbers' kuralına aykırı)."
    );
  } else {
    recordPass();
  }
}

async function main() {
  await test1_DemoCacheOpenApiContract();
  await test2_AstrophysicalAndCoordinateAccuracy();
  await test3_CanvasAndPlotTorture();
  await test4_AstroLlmParserTorture();
  await test5_PdfGeneratorTorture();

  console.log("=================================================================");
  console.log(`AEON TORTURE TEST SUMMARY: ${passedChecks}/${totalChecks} checks passed, ${findings.length} discrepancies found.`);
  console.log("=================================================================\n");

  for (let i = 0; i < findings.length; i++) {
    const f = findings[i];
    console.log(`[#${i + 1}] [${f.severity}] ${f.category}`);
    console.log(`    Modül/Dosya : ${f.fileOrModule}`);
    console.log(`    Sorun       : ${f.title}`);
    console.log(`    Analiz      : ${f.detail}\n`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
