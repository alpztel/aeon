import {
  classifyTarget,
  getCrossmatch,
  getSpectrum,
  runDifference,
  runShiftStack,
  simulateOrbit,
  type CatalogObject,
  type DataMode,
  type Epoch,
} from "./api";
import type { Lang } from "@/i18n/context";

function asciiSanitize(text: string): string {
  return text
    .replace(/ğ/g, "g")
    .replace(/Ğ/g, "G")
    .replace(/ü/g, "u")
    .replace(/Ü/g, "U")
    .replace(/ş/g, "s")
    .replace(/Ş/g, "S")
    .replace(/ı/g, "i")
    .replace(/İ/g, "I")
    .replace(/ö/g, "o")
    .replace(/Ö/g, "O")
    .replace(/ç/g, "c")
    .replace(/Ç/g, "C")
    .replace(/[−–—]/g, "-")
    .replace(/″/g, " arcsec")
    .replace(/′/g, " arcmin")
    .replace(/µ/g, "u")
    .replace(/°/g, " deg")
    .replace(/±/g, "+/-")
    .replace(/×/g, "x")
    .replace(/₂/g, "2")
    .replace(/₄/g, "4")
    .replace(/[^\x20-\x7E]/g, " ")
    .replace(/[()\\]/g, "");
}

function buildMinimalPdf(contentStream: string): Uint8Array {
  const encoder = new TextEncoder();
  const objects: string[] = [];

  objects.push("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n");
  objects.push("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n");
  objects.push(
    "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\nendobj\n"
  );
  objects.push(
    "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
  );
  objects.push(
    "5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n"
  );
  objects.push(
    `6 0 obj\n<< /Length ${contentStream.length} >>\nstream\n${contentStream}\nendstream\nendobj\n`
  );

  let body = "%PDF-1.4\n";
  const offsets: number[] = [0];
  for (const obj of objects) {
    offsets.push(body.length);
    body += obj;
  }

  const xrefOffset = body.length;
  body += `xref\n0 ${objects.length + 1}\n`;
  body += "0000000000 65535 f \n";
  for (let i = 1; i <= objects.length; i++) {
    body += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  }
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;

  return encoder.encode(body);
}

export async function generateAndDownloadDiscoveryPdf(params: {
  lang: Lang;
  coords: { ra: number; dec: number };
  epoch: Epoch;
  selectedObject: CatalogObject | null;
  dataMode: DataMode | "checking";
}): Promise<void> {
  const { lang, coords, epoch, selectedObject, dataMode } = params;
  const isTr = lang === "tr";

  const isPx = selectedObject?.id === "px-2026-09";
  const orbitReq = isPx
    ? { target_id: "px-2026-09" }
    : {
        observation: {
          ra: coords.ra,
          dec: coords.dec,
          distance_au:
            selectedObject?.distance_au ??
            (selectedObject?.distance_pc ? selectedObject.distance_pc * 206265 : 520),
          rate_arcsec_yr: Math.hypot(
            selectedObject?.pm_ra_cosdec_arcsec_yr ?? 0,
            selectedObject?.pm_dec_arcsec_yr ?? 0
          ),
          pa_deg: 275,
          radial_velocity_km_s: 0,
        },
      };

  const [specRes, diffRes, stackRes, crossRes, aiRes, orbitRes] = await Promise.all([
    getSpectrum({ ra: coords.ra, dec: coords.dec, epoch }).catch(() => null),
    runDifference({ ra: coords.ra, dec: coords.dec }).catch(() => null),
    runShiftStack({
      ra: coords.ra,
      dec: coords.dec,
      rate_arcsec_yr: isPx ? 110 : 8.15,
      pa_deg: isPx ? 62 : 275,
      distance_au: isPx ? 520 : null,
    }).catch(() => null),
    getCrossmatch({ ra: coords.ra, dec: coords.dec }).catch(() => null),
    classifyTarget({ ra: coords.ra, dec: coords.dec }).catch(() => null),
    simulateOrbit(orbitReq).catch(() => null),
  ]);

  const isSynthetic =
    Boolean(selectedObject?.is_synthetic) || selectedObject?.id === "px-2026-09";

  const lines: string[] = [];

  // Dark header banner
  lines.push("0.02 0.04 0.09 rg 0 770 595 72 re f");
  lines.push("0.96 0.62 0.04 rg 0 767 595 3 re f");

  const addText = (
    x: number,
    y: number,
    size: number,
    bold: boolean,
    rgb: [number, number, number],
    raw: string
  ) => {
    const clean = asciiSanitize(raw);
    lines.push(
      `BT /${bold ? "F2" : "F1"} ${size} Tf ${rgb[0]} ${rgb[1]} ${rgb[2]} rg ${x} ${y} Td (${clean}) Tj ET`
    );
  };

  addText(
    36,
    812,
    16,
    true,
    [1, 1, 1],
    isTr
      ? "AEON - ASTROFIZIK KESIF RAPORU (NASA SPACE APPS 2026)"
      : "AEON - ASTROPHYSICAL DISCOVERY REPORT (NASA SPACE APPS 2026)"
  );
  addText(
    36,
    790,
    9,
    false,
    [0.75, 0.82, 0.9],
    `UTC: ${new Date().toISOString()}  |  Data Mode: ${dataMode}  |  Epoch: ${epoch}`
  );

  let y = 742;

  if (isSynthetic) {
    lines.push("0.95 0.25 0.37 rg 36 706 523 32 re S");
    addText(
      44,
      724,
      10,
      true,
      [0.85, 0.1, 0.25],
      isTr
        ? "UYARI: SENTETIK TEST ADAYI (is_synthetic: true)"
        : "NOTICE: SYNTHETIC TEST CANDIDATE (is_synthetic: true)"
    );
    addText(
      44,
      712,
      8.5,
      false,
      [0.3, 0.1, 0.15],
      isTr
        ? "PX-2026-09 algilama ve yorunge zincirini dogrulamak icin fiziksel modele enjekte edilmistir."
        : "PX-2026-09 is an injected synthetic object used to validate the detection and orbit pipeline."
    );
    y = 684;
  }

  // Section 1: Target & Coordinates
  addText(
    36,
    y,
    12,
    true,
    [0.05, 0.2, 0.45],
    isTr ? "1. HEDEF VE ICRS KOORDINATLARI" : "1. TARGET & ICRS COORDINATES"
  );
  y -= 18;
  addText(
    36,
    y,
    10,
    false,
    [0.1, 0.1, 0.15],
    `${isTr ? "Hedef Adi" : "Target Designation"}: ${selectedObject?.name ?? "Custom Field"} (${selectedObject?.id ?? "field"})`
  );
  y -= 14;
  addText(
    36,
    y,
    10,
    false,
    [0.1, 0.1, 0.15],
    `ICRS RA / Dec: ${coords.ra.toFixed(5)} deg, ${coords.dec >= 0 ? "+" : ""}${coords.dec.toFixed(5)} deg   |   Class: ${selectedObject?.object_class ?? "unknown"}`
  );
  y -= 14;
  addText(
    36,
    y,
    10,
    false,
    [0.1, 0.1, 0.15],
    `${isTr ? "Uzaklik" : "Distance"}: ${
      selectedObject?.distance_au
        ? `${selectedObject.distance_au} AU`
        : selectedObject?.distance_pc
          ? `${selectedObject.distance_pc} pc`
          : "N/A"
    }   |   Teff: ${selectedObject?.teff_k ? `${selectedObject.teff_k} K` : "N/A"}`
  );

  // Section 2: Difference & Shift-and-Stack
  y -= 26;
  addText(
    36,
    y,
    12,
    true,
    [0.05, 0.2, 0.45],
    isTr
      ? "2. COK DONEMLI FARK VE SHIFT-AND-STACK ANALIZI"
      : "2. MULTI-EPOCH DIFFERENCING & SHIFT-AND-STACK"
  );
  y -= 18;
  const detCount = diffRes?.data.detections.length ?? 0;
  addText(
    36,
    y,
    10,
    false,
    [0.1, 0.1, 0.15],
    `${isTr ? "Goruntu Farki (Q1 vs Q3) Tespit Sayisi" : "Difference Detections (Q1 vs Q3)"}: ${detCount}   |   Noise sigma: ${diffRes?.data.noise_sigma?.toFixed(2) ?? "N/A"} uJy`
  );
  y -= 14;
  addText(
    36,
    y,
    10,
    false,
    [0.1, 0.1, 0.15],
    `Shift-and-Stack (24 frames): Single S/N = ${stackRes?.data.snr_single_frame?.toFixed(2) ?? "N/A"}  ->  Stacked S/N = ${stackRes?.data.snr_stacked.toFixed(2) ?? "N/A"} (Gain x${stackRes?.data.snr_gain?.toFixed(2) ?? "N/A"})`
  );
  y -= 14;
  addText(
    36,
    y,
    10,
    false,
    [0.1, 0.1, 0.15],
    `${isTr ? "Hiz Vektoru" : "Velocity Vector"}: ${stackRes?.data.rate_arcsec_yr?.toFixed(1) ?? "0"} arcsec/yr, PA ${stackRes?.data.pa_deg?.toFixed(1) ?? "0"} deg, Trial d = ${stackRes?.data.distance_au ?? "inf"} AU`
  );

  // Section 3: 102-Band Near-IR Spectrum Plot (Vector Box)
  y -= 26;
  addText(
    36,
    y,
    12,
    true,
    [0.05, 0.2, 0.45],
    isTr
      ? "3. 102-BANT YAKIN-KIZILOTESI TAYF (0.75 - 5.0 um)"
      : "3. 102-BAND NEAR-IR SPECTRUM (0.75 - 5.0 um)"
  );
  y -= 14;
  const feats = (specRes?.data.absorption_features ?? [])
    .map((f) => `${f.molecule} @ ${f.center_um?.toFixed(2)}um (${((f.depth ?? 0) * 100).toFixed(0)}%)`)
    .join(", ");
  addText(
    36,
    y,
    9.5,
    false,
    [0.15, 0.15, 0.2],
    `${isTr ? "Molekuler Bantlar" : "Molecular Bands"}: ${feats || "Continuum"}`
  );

  // Draw spectrum box at (36, y-125, 523, 110)
  const boxBottom = y - 125;
  const boxHeight = 110;
  const boxLeft = 36;
  const boxWidth = 523;
  lines.push(`0.85 0.88 0.92 RG 1 w ${boxLeft} ${boxBottom} ${boxWidth} ${boxHeight} re S`);

  if (specRes?.data.wavelength_um && specRes.data.flux_ujy.length > 1) {
    const wls = specRes.data.wavelength_um;
    const flx = specRes.data.flux_ujy.map((v) => (Number.isFinite(v) ? v : 0));
    const finiteFlx = flx.filter((v) => Number.isFinite(v));
    const minF = finiteFlx.length > 0 ? Math.min(...finiteFlx) : 0;
    const maxF = finiteFlx.length > 0 ? Math.max(...finiteFlx, minF + 1e-3) : 1;
    lines.push("0.08 0.55 0.75 RG 1.5 w");
    wls.forEach((w, idx) => {
      const safeW = Number.isFinite(w) ? w : 0.75;
      const px = boxLeft + ((safeW - 0.75) / (5.0 - 0.75)) * boxWidth;
      const py = boxBottom + 8 + ((flx[idx] - minF) / (maxF - minF)) * (boxHeight - 16);
      lines.push(`${px.toFixed(1)} ${py.toFixed(1)} ${idx === 0 ? "m" : "l"}`);
    });
    lines.push("S");
  }

  y = boxBottom - 24;

  // Section 4: Multi-Mission Cross-Match & AI Classification
  addText(
    36,
    y,
    12,
    true,
    [0.05, 0.2, 0.45],
    isTr
      ? "4. COKLU GOREV ESLESTIRME & AI SINIFLANDIRMA"
      : "4. MULTI-MISSION CROSS-MATCH & AI CLASSIFICATION"
  );
  y -= 18;
  addText(
    36,
    y,
    10,
    false,
    [0.1, 0.1, 0.15],
    `Gaia DR3 Matches: ${crossRes?.data.gaia?.length ?? 0}  |  WISE Matches: ${crossRes?.data.wise?.length ?? 0}  |  MAST (JWST/HST): ${crossRes?.data.mast_overlap?.length ?? 0}  |  Unmatched Cold IR: ${crossRes?.data.unmatched_ir_candidate ? "YES" : "NO"}`
  );
  y -= 14;
  addText(
    36,
    y,
    10,
    false,
    [0.1, 0.1, 0.15],
    aiRes && aiRes.data.spectrum_source === "none"
      ? "1D-CNN Top Class: N/A (no spectrum at this position)  |  PatchAnomalyViT Score: N/A"
      : `1D-CNN Top Class: ${aiRes?.data.top_class ?? "N/A"}  |  PatchAnomalyViT Score: ${aiRes?.data.anomaly_score?.toFixed(2) ?? "N/A"} / 1.00`
  );

  // Section 5: REBOUND N-Body Forecast
  y -= 26;
  addText(
    36,
    y,
    12,
    true,
    [0.05, 0.2, 0.45],
    isTr
      ? "5. REBOUND N-GOVDE YORUNGE TAHMINI (1 / 5 / 10 YIL)"
      : "5. REBOUND N-BODY ORBIT FORECAST (1 / 5 / 10 YR)"
  );
  y -= 18;
  for (const h of orbitRes?.data.particle.horizons ?? []) {
    addText(
      36,
      y,
      9.5,
      false,
      [0.1, 0.1, 0.15],
      `+${h.years} yr: RA ${h.ra?.toFixed(4)} deg, Dec ${h.dec?.toFixed(4)} deg  |  r = ${h.distance_au?.toFixed(2)} AU  |  Kepler Dev = ${Math.round(h.kepler_only_deviation_km ?? 0)} km`
    );
    y -= 14;
  }

  addText(
    36,
    36,
    8.5,
    false,
    [0.45, 0.5, 0.58],
    "Generated by AEON Astrophysical Discovery OS (https://www.a-eon.engineer) - Istanbul Medeniyet University Physics Engineering"
  );

  const pdfBytes = buildMinimalPdf(lines.join("\n"));
  const blob = new Blob([pdfBytes.buffer as ArrayBuffer], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "AEON_Discovery_Report.pdf";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
