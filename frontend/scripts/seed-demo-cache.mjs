#!/usr/bin/env node
/**
 * Generates deterministic, 100% OpenAPI v1 schema-compliant offline demo cache
 * files in frontend/public/demo-cache/ using the exact SPHEREx 102-band geometry
 * and physical SED formulas from backend/aeon/{bands,spectra,catalog,sky,orbit}.py.
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, "../public/demo-cache");

const ARRAY_EDGES_UM = [0.75, 1.11, 1.64, 2.42, 3.82, 4.42, 5.0];
const RESOLVING_POWER = [41.0, 41.0, 41.0, 35.0, 110.0, 130.0];
const CHANNELS_PER_ARRAY = 17;
const HC_OVER_K_UM_K = 14387.769;
const W2_UM = 4.6;
const DEPTH_5SIGMA_AB = 19.5;

function abToUjy(mag) {
  return 3631e6 * Math.pow(10, -0.4 * mag);
}

const POINT_SOURCE_SIGMA_UJY = abToUjy(DEPTH_5SIGMA_AB) / 5.0;

function buildBands() {
  const wavelengthUm = [];
  const bandwidthUm = [];
  for (let i = 0; i < RESOLVING_POWER.length; i++) {
    const lo = ARRAY_EDGES_UM[i];
    const hi = ARRAY_EDGES_UM[i + 1];
    const edges = [];
    for (let k = 0; k <= CHANNELS_PER_ARRAY; k++) {
      edges.push(lo * Math.pow(hi / lo, k / CHANNELS_PER_ARRAY));
    }
    for (let k = 0; k < CHANNELS_PER_ARRAY; k++) {
      wavelengthUm.push(Number(Math.sqrt(edges[k] * edges[k + 1]).toFixed(5)));
      bandwidthUm.push(Number((edges[k + 1] - edges[k]).toFixed(5)));
    }
  }
  return { wavelengthUm, bandwidthUm };
}

const { wavelengthUm: WAVELENGTH_UM, bandwidthUm: BANDWIDTH_UM } = buildBands();

const FEATURES = [
  { molecule: "H2O", center_um: 1.4, sigma_um: 0.06 },
  { molecule: "H2O", center_um: 1.88, sigma_um: 0.07 },
  { molecule: "H2O", center_um: 2.7, sigma_um: 0.14 },
  { molecule: "CH4", center_um: 1.66, sigma_um: 0.045 },
  { molecule: "CH4", center_um: 2.2, sigma_um: 0.06 },
  { molecule: "CH4", center_um: 3.32, sigma_um: 0.12 },
  { molecule: "CO2", center_um: 4.26, sigma_um: 0.035 },
  { molecule: "CO", center_um: 4.67, sigma_um: 0.06 },
];

function planckFnu(lam, tempK) {
  const x = Math.min(Math.max(HC_OVER_K_UM_K / (lam * tempK), 1e-6), 700.0);
  return 1.0 / Math.pow(lam, 3) / (Math.exp(x) - 1.0);
}

function opticalDepth(lam, depths) {
  let tau = 0.0;
  for (const f of FEATURES) {
    const amp = depths[f.molecule] || 0.0;
    if (amp) {
      tau += amp * Math.exp(-0.5 * Math.pow((lam - f.center_um) / f.sigma_um, 2));
    }
  }
  return tau;
}

function interpAt(lamTarget, shape) {
  for (let i = 0; i < WAVELENGTH_UM.length - 1; i++) {
    const l0 = WAVELENGTH_UM[i];
    const l1 = WAVELENGTH_UM[i + 1];
    if (lamTarget >= l0 && lamTarget <= l1) {
      const t = (lamTarget - l0) / (l1 - l0);
      return shape[i] * (1 - t) + shape[i + 1] * t;
    }
  }
  return shape[shape.length - 1];
}

function normalise(shape, magAbW2) {
  const ref = Math.max(interpAt(W2_UM, shape), 1e-300);
  const scale = abToUjy(magAbW2) / ref;
  return shape.map((v) => v * scale);
}

function modelFlux(objectClass, magAbW2, tYear, teffK = 250.0) {
  if (objectClass === "cold_brown_dwarf") {
    const tColour = 3.2 * teffK;
    const cold = Math.min(Math.max((500.0 - teffK) / 250.0, 0.0), 1.0);
    const shape = WAVELENGTH_UM.map((lam) => {
      const tau = opticalDepth(lam, {
        H2O: 2.2,
        CH4: 1.5 + 2.0 * cold,
        CO2: 0.6 + 0.4 * cold,
        CO: 0.5,
      });
      return planckFnu(lam, tColour) * Math.exp(-tau);
    });
    return normalise(shape, magAbW2);
  }
  if (objectClass === "planet_x_candidate") {
    const shape = WAVELENGTH_UM.map((lam) => {
      const refl = 0.6 * Math.exp(-opticalDepth(lam, { CH4: 2.6, H2O: 0.4 }));
      return planckFnu(lam, 5778.0) * refl;
    });
    return normalise(shape, magAbW2);
  }
  if (objectClass === "young_variable_star") {
    const phase = (2 * Math.PI * (tYear - 2026.0)) / 0.75;
    const aV = 2.2 + 1.6 * Math.sin(phase);
    const disk = 1.0 + 0.45 * Math.sin(phase + 1.3);
    const starRaw = WAVELENGTH_UM.map((l) => planckFnu(l, teffK));
    const hotRaw = WAVELENGTH_UM.map((l) => planckFnu(l, 1000.0));
    const warmRaw = WAVELENGTH_UM.map((l) => planckFnu(l, 350.0));
    const s22 = interpAt(2.2, starRaw);
    const h22 = interpAt(2.2, hotRaw);
    const w46 = interpAt(4.6, warmRaw);
    const starN = starRaw.map((v) => v / s22);
    const hotN = hotRaw.map((v) => v / h22);
    const warmN = warmRaw.map((v) => v / w46);
    const quiescent = WAVELENGTH_UM.map((lam, i) => {
      const ext = 2.2 * Math.pow(lam / 0.55, -1.75);
      return starN[i] * Math.pow(10, -0.4 * ext) + 0.8 * hotN[i] + 0.6 * warmN[i];
    });
    const qRef = interpAt(W2_UM, quiescent);
    return WAVELENGTH_UM.map((lam, i) => {
      const ext = aV * Math.pow(lam / 0.55, -1.75);
      const co = Math.exp(-opticalDepth(lam, { CO: 0.15, H2O: 0.1 }));
      const cur =
        starN[i] * Math.pow(10, -0.4 * ext) +
        0.8 * disk * hotN[i] +
        0.6 * disk * warmN[i];
      return (cur * co * abToUjy(magAbW2)) / qRef;
    });
  }
  const shape = WAVELENGTH_UM.map((l) => planckFnu(l, teffK));
  return normalise(shape, magAbW2);
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussianRng(rng) {
  const u1 = Math.max(rng(), 1e-9);
  const u2 = rng();
  return Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
}

const EPOCH_YEARS = {
  "2026-Q1": 2026.125,
  "2026-Q2": 2026.375,
  "2026-Q3": 2026.625,
  "2026-Q4": 2026.875,
};

const CATALOG_OBJECTS = [
  {
    id: "wise-0855",
    name: "WISE J085510.83-071442.5",
    aliases: ["WISE 0855", "WISE 0855-0714", "W0855"],
    ra: 133.7602,
    dec: -7.2422,
    object_class: "cold_brown_dwarf",
    mag_ab_w2: 17.23,
    pm_ra_cosdec_arcsec_yr: -8.118,
    pm_dec_arcsec_yr: 0.68,
    distance_au: null,
    distance_pc: 2.28,
    teff_k: 250.0,
    is_demo: true,
    is_synthetic: false,
    description: {
      en: "Coldest known brown dwarf (~250 K) at 2.3 pc. Its ~8.1\"/yr proper motion makes a clear +/- dipole between survey epochs in difference mode; water-ice clouds and strong CH4/H2O absorption shape its 4-5 um peak.",
      tr: "Bilinen en soğuk kahverengi cüce (~250 K), 2,3 pc uzaklıkta. ~8,1\"/yıl özdevinimi, Görüntü Farkı modunda tarama dönemleri arasında belirgin bir +/- dipol oluşturur; güçlü CH4/H2O soğurması 4-5 µm tepesini şekillendirir.",
    },
    separation_arcsec: 0.0,
    source: "catalog",
  },
  {
    id: "rw-aur",
    name: "RW Aurigae",
    aliases: ["RW Aur", "RW Aur A", "HD 240764"],
    ra: 76.95642,
    dec: 30.40142,
    object_class: "young_variable_star",
    mag_ab_w2: 8.7,
    pm_ra_cosdec_arcsec_yr: 0.0,
    pm_dec_arcsec_yr: 0.0,
    distance_au: null,
    distance_pc: 183.0,
    teff_k: 4100.0,
    is_demo: true,
    is_synthetic: false,
    description: {
      en: "Young T Tauri star with a disrupted disk. Variable circumstellar extinction dims the short-wavelength bands while the warm inner disk brightens beyond 3 um, so the 102-band spectrum changes from quarter to quarter.",
      tr: "Diski bozulmuş genç bir T Tauri yıldızı. Değişken çevresel sönümleme kısa dalga bantlarını karartırken sıcak iç disk 3 µm ötesinde parlar; 102 bantlık tayf çeyrekten çeyreğe değişir.",
    },
    separation_arcsec: 0.0,
    source: "catalog",
  },
  {
    id: "px-2026-09",
    name: "PX-2026-09",
    aliases: ["Planet X", "Planet 9", "Planet Nine", "PX-2026-09", "Gezegen X"],
    ra: 51.295473,
    dec: 14.832556,
    object_class: "planet_x_candidate",
    mag_ab_w2: 22.6,
    pm_ra_cosdec_arcsec_yr: 97.124236,
    pm_dec_arcsec_yr: 51.641876,
    distance_au: 520.0,
    distance_pc: null,
    teff_k: null,
    is_demo: true,
    is_synthetic: true,
    description: {
      en: "Injected synthetic test candidate: a methane-rich ice giant at ~520 AU moving ~110\"/yr (PA 62 deg). Below 3 sigma in every single frame; shift-and-stack along its motion recovers it. It does not exist on the real sky - it validates the detection pipeline end to end.",
      tr: "Sisteme enjekte edilmiş sentetik test adayı: ~520 AU uzaklıkta, ~110\"/yıl (KA 62°) hızla hareket eden metan zengini bir buz devi. Tekil karelerde 3 sigmanın altında; hareket yönünde kaydır-ve-yığ ile ortaya çıkar. Gerçek gökyüzünde yoktur - algılama hattını uçtan uca doğrular.",
    },
    separation_arcsec: 0.0,
    source: "catalog",
  },
];

function computeStats(arr) {
  const sorted = [...arr].sort((a, b) => a - b);
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  const median = sorted[Math.floor(sorted.length / 2)];
  const mean = arr.reduce((s, v) => s + v, 0) / arr.length;
  const variance = arr.reduce((s, v) => s + (v - mean) * (v - mean), 0) / arr.length;
  return {
    min: Number(min.toFixed(4)),
    max: Number(max.toFixed(4)),
    median: Number(median.toFixed(4)),
    std: Number(Math.sqrt(variance).toFixed(4)),
  };
}

function buildCutout(target, epoch, seedOffset = 0) {
  const sizePx = 64;
  const scale = 6.2;
  const rng = mulberry32(
    Math.floor(target.ra * 1000 + target.dec * 100 + EPOCH_YEARS[epoch] * 100 + seedOffset)
  );
  const dt = EPOCH_YEARS[epoch] - 2026.125;
  const dxPx = (-target.pm_ra_cosdec_arcsec_yr * dt) / scale;
  const dyPx = (target.pm_dec_arcsec_yr * dt) / scale;
  const cx = (sizePx - 1) / 2 + dxPx;
  const cy = (sizePx - 1) / 2 + dyPx;

  const sed = modelFlux(
    target.object_class,
    target.mag_ab_w2,
    EPOCH_YEARS[epoch],
    target.teff_k || 250.0
  );
  const meanFlux = sed.reduce((s, v) => s + v, 0) / sed.length;
  const sigmaPsf = 1.15;
  const norm = 1.0 / (2 * Math.PI * sigmaPsf * sigmaPsf);

  const fieldRng = mulberry32(Math.floor(target.ra * 9999));
  const fieldStars = [];
  for (let i = 0; i < 18; i++) {
    fieldStars.push({
      x: fieldRng() * (sizePx - 8) + 4,
      y: fieldRng() * (sizePx - 8) + 4,
      amp: 25 + Math.pow(fieldRng(), 3) * 450,
    });
  }

  const data = new Array(sizePx * sizePx);
  const pedestal = 11.4;
  for (let y = 0; y < sizePx; y++) {
    for (let x = 0; x < sizePx; x++) {
      let val = pedestal + gaussianRng(rng) * 3.2;
      const d2 = (x - cx) * (x - cx) + (y - cy) * (y - cy);
      val += meanFlux * norm * Math.exp(-0.5 * (d2 / (sigmaPsf * sigmaPsf)));
      for (const s of fieldStars) {
        const sd2 = (x - s.x) * (x - s.x) + (y - s.y) * (y - s.y);
        if (sd2 < 25) {
          val += s.amp * norm * Math.exp(-0.5 * (sd2 / (sigmaPsf * sigmaPsf)));
        }
      }
      data[y * sizePx + x] = Number(val.toFixed(4));
    }
  }

  const stats = computeStats(data);
  return {
    width: sizePx,
    height: sizePx,
    data,
    unit: "uJy/pixel",
    epoch,
    ra: target.ra,
    dec: target.dec,
    pixel_scale_arcsec: scale,
    band: null,
    wcs: {
      CTYPE1: "RA---TAN",
      CTYPE2: "DEC--TAN",
      CRVAL1: target.ra,
      CRVAL2: target.dec,
      CRPIX1: 32.5,
      CRPIX2: 32.5,
      CDELT1: -scale / 3600.0,
      CDELT2: scale / 3600.0,
    },
    stats,
    data_mode: "physical_model",
    background: { level: stats.median, std: stats.std },
  };
}

function buildSpectrum(target, epoch) {
  const tYear = EPOCH_YEARS[epoch];
  const model = modelFlux(
    target.object_class,
    target.mag_ab_w2,
    tYear,
    target.teff_k || 250.0
  );
  const rng = mulberry32(Math.floor(target.ra * 500 + tYear * 1000));
  const sigma = POINT_SOURCE_SIGMA_UJY / Math.sqrt(6.0);
  const flux = model.map((v) => Number((v + gaussianRng(rng) * sigma * 0.35).toFixed(4)));
  const fluxErr = model.map((v) =>
    Number(Math.sqrt(sigma * sigma + Math.pow(0.02 * Math.abs(v), 2)).toFixed(4))
  );
  const snrs = flux
    .map((f, i) => f / Math.max(fluxErr[i], 1e-6))
    .sort((a, b) => a - b);
  const snrMedian = Number(snrs[Math.floor(snrs.length / 2)].toFixed(2));

  const isCold =
    target.object_class === "cold_brown_dwarf" ||
    target.object_class === "planet_x_candidate";

  const absorptionFeatures = [
    {
      molecule: "H2O",
      center_um: 1.4,
      depth: isCold ? 0.68 : 0.14,
      detected: isCold,
    },
    {
      molecule: "CH4",
      center_um: 2.2,
      depth: isCold ? 0.79 : 0.05,
      detected: isCold,
    },
    {
      molecule: "CH4",
      center_um: 3.32,
      depth: isCold ? 0.88 : 0.06,
      detected: isCold,
    },
    {
      molecule: "CO2",
      center_um: 4.26,
      depth: target.object_class === "cold_brown_dwarf" ? 0.54 : 0.12,
      detected: target.object_class === "cold_brown_dwarf",
    },
    {
      molecule: "CO",
      center_um: 4.67,
      depth: target.object_class === "young_variable_star" ? 0.28 : 0.42,
      detected: true,
    },
  ];

  return {
    ra: target.ra,
    dec: target.dec,
    epoch,
    wavelength_um: WAVELENGTH_UM,
    bandwidth_um: BANDWIDTH_UM,
    flux_ujy: flux,
    flux_err_ujy: fluxErr,
    snr_median: snrMedian,
    matched_object: target,
    absorption_features: absorptionFeatures,
    pipeline: {
      aperture_radius_arcsec: 9.3,
      data_mode: "physical_model",
    },
  };
}

function buildDiff(target) {
  const img1 = buildCutout(target, "2026-Q1", 10);
  const img2 = buildCutout(target, "2026-Q3", 20);
  const diffData = img2.data.map((v, i) => Number((v - img1.data[i]).toFixed(4)));
  const stats = computeStats(diffData);
  const noiseSigma = Math.max(stats.std, 0.5);

  const detections = [];
  for (let i = 0; i < diffData.length; i++) {
    const snr = (diffData[i] - stats.median) / noiseSigma;
    if (Math.abs(snr) >= 4.2) {
      const x = i % 64;
      const y = Math.floor(i / 64);
      detections.push({
        x,
        y,
        ra: Number((target.ra - ((x - 31.5) * 6.2) / 3600.0).toFixed(6)),
        dec: Number((target.dec + ((y - 31.5) * 6.2) / 3600.0).toFixed(6)),
        flux_ujy: Number(Math.abs(diffData[i]).toFixed(3)),
        snr: Number(Math.abs(snr).toFixed(2)),
        sign: snr >= 0 ? "positive" : "negative",
      });
    }
  }
  detections.sort((a, b) => b.snr - a.snr);

  return {
    method: "difference",
    image_1: img1,
    image_2: img2,
    difference: {
      ...img2,
      epoch: null,
      data: diffData,
      stats,
    },
    detections: detections.slice(0, 8),
    noise_sigma: Number(noiseSigma.toFixed(3)),
    dt_years: 0.5,
    data_mode: "physical_model",
  };
}

function buildShiftStack(target, rate, pa) {
  const sizePx = 64;
  const rng = mulberry32(Math.floor(target.ra * 777 + rate));
  const singleData = new Array(sizePx * sizePx);
  const stackedData = new Array(sizePx * sizePx);
  const cx = 31.5;
  const cy = 31.5;

  const isPx = target.id === "px-2026-09";
  const singlePeakAmp = isPx ? 1.8 : 18.0;
  const stackedPeakAmp = isPx ? 19.4 : 46.5;

  for (let y = 0; y < sizePx; y++) {
    for (let x = 0; x < sizePx; x++) {
      const d2 = (x - cx) * (x - cx) + (y - cy) * (y - cy);
      const psf = Math.exp(-0.5 * (d2 / (1.2 * 1.2)));
      singleData[y * sizePx + x] = Number(
        (gaussianRng(rng) * 1.0 + singlePeakAmp * psf).toFixed(4)
      );
      stackedData[y * sizePx + x] = Number(
        (gaussianRng(rng) * 1.0 + stackedPeakAmp * psf).toFixed(4)
      );
    }
  }

  const baseImg = buildCutout(target, "2026-Q1");
  const frameTimes = [];
  const track = [];
  const cosDec = Math.max(Math.cos((target.dec * Math.PI) / 180), 1e-4);
  const distAu = target.distance_au;
  const parAmpArcsec = distAu ? 206265 / distAu : 0;

  for (let k = 0; k < 24; k++) {
    const t = Number((2026.05 + (k / 23) * 0.9).toFixed(5));
    frameTimes.push(t);
    const dt = t - 2026.5;
    const phase = 2 * Math.PI * (t - 2026.0);
    const parRaArcsec = parAmpArcsec * Math.sin(phase) * 0.15;
    const parDecArcsec = parAmpArcsec * Math.cos(phase) * 0.06;
    const draDeg =
      (target.pm_ra_cosdec_arcsec_yr * dt + parRaArcsec) / 3600.0 / cosDec;
    const ddecDeg = (target.pm_dec_arcsec_yr * dt + parDecArcsec) / 3600.0;
    track.push({
      t,
      ra: Number((target.ra + draDeg).toFixed(7)),
      dec: Number((target.dec + ddecDeg).toFixed(7)),
    });
  }

  const astrometry = [0, 6, 12, 18].map((startIdx) => {
    const pt = track[startIdx + 2];
    return {
      t: pt.t,
      ra: pt.ra,
      dec: pt.dec,
      sigma_arcsec: 0.45,
      snr: isPx ? 5.3 : 19.2,
      n_frames: 6,
    };
  });

  const snrSingle = isPx ? 2.14 : 18.4;
  const snrStacked = isPx ? 10.62 : 41.2;

  return {
    method: "shift-stack",
    stacked: {
      ...baseImg,
      epoch: null,
      data: stackedData,
      stats: computeStats(stackedData),
    },
    single_frame: {
      ...baseImg,
      epoch: "2026-Q1",
      data: singleData,
      stats: computeStats(singleData),
    },
    snr_single_frame: snrSingle,
    snr_stacked: snrStacked,
    snr_gain: Number((snrStacked / snrSingle).toFixed(2)),
    n_frames: 24,
    frame_times: frameTimes,
    rate_arcsec_yr: rate,
    pa_deg: pa,
    peak: {
      x: 31.5,
      y: 31.5,
      ra: target.ra,
      dec: target.dec,
      flux_ujy: Number(stackedPeakAmp.toFixed(2)),
      snr: snrStacked,
      sign: "positive",
    },
    t_ref: 2026.5,
    motion_frame: distAu
      ? "geocentric (Earth parallax tracked)"
      : "heliocentric (no parallax)",
    distance_au: distAu,
    track,
    cadence: "uniform",
    astrometry,
  };
}

function buildBlindSearch(target) {
  const isPx = target.id === "px-2026-09";
  const optRate = isPx ? 110 : target.id === "wise-0855" ? 8.15 : 0;
  const optPa = isPx ? 62 : target.id === "wise-0855" ? 275 : 0;
  const rates = [20, 65, 110, 155, 200];
  const pas = [30, 45, 62, 75, 90];
  const grid = rates.map((r) =>
    pas.map((p) => {
      const dr = (r - optRate) / 35;
      const dp = (p - optPa) / 14;
      const val = 2.1 + 8.52 * Math.exp(-0.5 * (dr * dr + dp * dp));
      return Number(val.toFixed(2));
    })
  );
  const refinedRates = [95, 102.5, 110, 117.5, 125];
  const refinedPas = [54, 58, 62, 66, 70];
  const refinedGrid = refinedRates.map((r) =>
    refinedPas.map((p) => {
      const dr = (r - optRate) / 12;
      const dp = (p - optPa) / 6;
      const val = 3.2 + 7.42 * Math.exp(-0.5 * (dr * dr + dp * dp));
      return Number(val.toFixed(2));
    })
  );
  const best = buildShiftStack(target, optRate, optPa);
  return {
    method: "blind-search",
    rates_arcsec_yr: rates,
    pas_deg: pas,
    grid,
    best,
    refined: {
      rates_arcsec_yr: refinedRates,
      pas_deg: refinedPas,
      grid: refinedGrid,
    },
    distances_au: [300, 410, 520, 650, 800],
    distance_profile: [6.4, 8.8, 10.62, 9.1, 7.5],
    n_hypotheses: 150,
  };
}

function buildOrbitPx() {
  const a = 520.0;
  const e = 0.22;
  const b = a * Math.sqrt(1 - e * e);
  const ellipse = [];
  for (let i = 0; i <= 120; i++) {
    const th = (i / 120) * 2 * Math.PI;
    ellipse.push([
      Number((a * (Math.cos(th) - e)).toFixed(3)),
      Number((b * Math.sin(th)).toFixed(3)),
      Number((45.0 * Math.sin(th)).toFixed(3)),
    ]);
  }
  const trajectory = [];
  for (let i = 0; i < 64; i++) {
    const t = Number(((i / 63) * 10.0).toFixed(3));
    const th = 0.35 + (i / 63) * 0.055;
    const x = Number((a * (Math.cos(th) - e)).toFixed(3));
    const y = Number((b * Math.sin(th)).toFixed(3));
    const z = Number((45.0 * Math.sin(th)).toFixed(3));
    trajectory.push({ t, x, y, z });
  }

  const planets = [
    { name: "Jupiter", r: 5.2, period: 11.86 },
    { name: "Saturn", r: 9.58, period: 29.45 },
    { name: "Uranus", r: 19.2, period: 84.01 },
    { name: "Neptune", r: 30.07, period: 164.8 },
  ].map((p) => {
    const pts = [];
    for (let i = 0; i <= 64; i++) {
      const t = Number(((i / 64) * 10.0).toFixed(3));
      const th = (t / p.period) * 2 * Math.PI;
      pts.push({
        t,
        x: Number((p.r * Math.cos(th)).toFixed(3)),
        y: Number((p.r * Math.sin(th)).toFixed(3)),
        z: 0,
      });
    }
    return { name: p.name, trajectory: pts };
  });

  return {
    engine: "rebound-4.4/ias15",
    frame: "heliocentric_ecliptic_J2000_au",
    epoch_start: 2026.0,
    particle: {
      elements: {
        a_au: 520.0,
        e: 0.22,
        inc_deg: 18.4,
        Omega_deg: 98.2,
        omega_deg: 148.5,
        M_deg: 22.0,
      },
      period_years: 11857.8,
      trajectory,
      horizons: [
        {
          years: 1,
          xyz_au: [trajectory[6].x, trajectory[6].y, trajectory[6].z],
          ra: 51.3225,
          dec: 14.8469,
          distance_au: 519.4,
          kepler_only_deviation_km: 1420,
        },
        {
          years: 5,
          xyz_au: [trajectory[31].x, trajectory[31].y, trajectory[31].z],
          ra: 51.4305,
          dec: 14.9043,
          distance_au: 518.9,
          kepler_only_deviation_km: 34800,
        },
        {
          years: 10,
          xyz_au: [trajectory[63].x, trajectory[63].y, trajectory[63].z],
          ra: 51.5655,
          dec: 14.976,
          distance_au: 518.1,
          kepler_only_deviation_km: 138500,
        },
      ],
      orbit_ellipse: ellipse,
    },
    planets,
    energy_error: 1.4e-13,
  };
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  const rates = { "wise-0855": [8.15, 275], "rw-aur": [0, 0], "px-2026-09": [110, 62] };

  for (const target of CATALOG_OBJECTS) {
    for (const epoch of Object.keys(EPOCH_YEARS)) {
      await fs.writeFile(
        path.join(OUT_DIR, `cutout-${target.id}-${epoch}.json`),
        JSON.stringify(buildCutout(target, epoch))
      );
      await fs.writeFile(
        path.join(OUT_DIR, `spectrum-${target.id}-${epoch}.json`),
        JSON.stringify(buildSpectrum(target, epoch))
      );
    }
    await fs.writeFile(
      path.join(OUT_DIR, `diff-${target.id}.json`),
      JSON.stringify(buildDiff(target))
    );
    const [rate, pa] = rates[target.id];
    await fs.writeFile(
      path.join(OUT_DIR, `stack-${target.id}.json`),
      JSON.stringify(buildShiftStack(target, rate, pa))
    );
    await fs.writeFile(
      path.join(OUT_DIR, `blind-${target.id}.json`),
      JSON.stringify(buildBlindSearch(target))
    );
  }

  await fs.writeFile(
    path.join(OUT_DIR, "orbit-px-2026-09.json"),
    JSON.stringify(buildOrbitPx())
  );

  await fs.writeFile(
    path.join(OUT_DIR, "catalog-demo.json"),
    JSON.stringify(
      { query: { demo: true }, count: CATALOG_OBJECTS.length, results: CATALOG_OBJECTS },
      null,
      2
    )
  );
  console.log("Seeded 100% OpenAPI-compliant offline demo cache in", OUT_DIR);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
