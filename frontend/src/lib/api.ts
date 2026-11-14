import type { components, operations } from "./api-types";

export type HealthResponse = components["schemas"]["Health"];
export type Epoch = components["schemas"]["Epoch"];
export type ObjectClass = components["schemas"]["ObjectClass"];
export type CatalogObject = components["schemas"]["CatalogObject"];
export type CatalogResponse = components["schemas"]["CatalogResponse"];
export type SkyImage = components["schemas"]["Image"];
export type SpectrumResponse = components["schemas"]["Spectrum"];
export type AnalysisRequest = components["schemas"]["AnalysisRequest"];
export type DifferenceResult = components["schemas"]["DifferenceResult"];
export type ShiftStackResult = components["schemas"]["ShiftStackResult"];
export type BlindSearchResult = components["schemas"]["BlindSearchResult"];
export type Detection = components["schemas"]["Detection"];
export type AstrometryPoint = components["schemas"]["Astrometry"];
export type OrbitRequest = components["schemas"]["OrbitRequest"];
export type OrbitResult = components["schemas"]["OrbitResult"];
export type UiAction = components["schemas"]["UiAction"];
export type Candidate = components["schemas"]["Candidate"];
export type AiCommandResponse =
  operations["aiCommand"]["responses"]["200"]["content"]["application/json"];
export type AiClassifyResponse =
  operations["aiClassify"]["responses"]["200"]["content"]["application/json"];
export type CrossmatchResult =
  operations["missionsCrossmatch"]["responses"]["200"]["content"]["application/json"];
export type GcnAlert =
  operations["gcnAlerts"]["responses"]["200"]["content"]["application/json"][number];

export type DataMode = "fits_archive" | "physical_model" | "offline_cache";

export const EPOCHS: Epoch[] = ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"];

export const EPOCH_DECIMAL: Record<Epoch, number> = {
  "2026-Q1": 2026.125,
  "2026-Q2": 2026.375,
  "2026-Q3": 2026.625,
  "2026-Q4": 2026.875,
};

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000").replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...init?.headers,
      },
    });

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = (await res.json()) as { detail?: string };
        if (body?.detail) detail = body.detail;
      } catch {
        // Ignore JSON parse failure on error body
      }
      throw new ApiError(detail, res.status);
    }

    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("Request timed out", 408);
    }
    throw new ApiError(err instanceof Error ? err.message : "Network error", 0);
  } finally {
    clearTimeout(timer);
  }
}

export interface DemoTargetMeta {
  id: "wise-0855" | "rw-aur" | "px-2026-09";
  label: string;
  ra: number;
  dec: number;
  refRa: number;
  refDec: number;
  epoch: Epoch;
  epochCoords: Record<Epoch, { ra: number; dec: number }>;
  synthetic?: boolean;
}

export const DEMO_TARGETS: readonly DemoTargetMeta[] = [
  {
    id: "wise-0855",
    label: "WISE 0855",
    ra: 133.7595813,
    dec: -7.2422291,
    refRa: 133.7586977,
    refDec: -7.2420576,
    epoch: "2026-Q1",
    epochCoords: {
      "2026-Q1": { ra: 133.7595813, dec: -7.2422291 },
      "2026-Q2": { ra: 133.7589286, dec: -7.2420981 },
      "2026-Q3": { ra: 133.7585015, dec: -7.2420507 },
      "2026-Q4": { ra: 133.7580213, dec: -7.2420871 },
    },
  },
  {
    id: "rw-aur",
    label: "RW Aur",
    ra: 76.9564216,
    dec: 30.40142,
    refRa: 76.9564207,
    refDec: 30.4014199,
    epoch: "2026-Q3",
    epochCoords: {
      "2026-Q1": { ra: 76.9564184, dec: 30.4014199 },
      "2026-Q2": { ra: 76.9564194, dec: 30.4014198 },
      "2026-Q3": { ra: 76.9564216, dec: 30.40142 },
      "2026-Q4": { ra: 76.9564207, dec: 30.4014202 },
    },
  },
  {
    id: "px-2026-09",
    label: "PX-2026-09",
    ra: 51.094637,
    dec: 14.7751279,
    refRa: 51.295473,
    refDec: 14.8325559,
    epoch: "2026-Q1",
    epochCoords: {
      "2026-Q1": { ra: 51.094637, dec: 14.7751279 },
      "2026-Q2": { ra: 51.2163064, dec: 14.814313 },
      "2026-Q3": { ra: 51.3292136, dec: 14.8366317 },
      "2026-Q4": { ra: 51.2243498, dec: 14.8051862 },
    },
    synthetic: true,
  },
];

export function angularSeparationDeg(
  ra1: number,
  dec1: number,
  ra2: number,
  dec2: number
): number {
  const toRad = Math.PI / 180;
  const r1 = ra1 * toRad;
  const d1 = dec1 * toRad;
  const r2 = ra2 * toRad;
  const d2 = dec2 * toRad;
  const sinD = Math.sin((d2 - d1) * 0.5);
  const sinR = Math.sin((r2 - r1) * 0.5);
  const h = sinD * sinD + Math.cos(d1) * Math.cos(d2) * sinR * sinR;
  return (2 * Math.asin(Math.min(1, Math.sqrt(Math.max(0, h))))) / toRad;
}

const demoCacheMemo = new Map<string, unknown>();

async function fetchDemoCache<T>(filename: string): Promise<T | null> {
  if (demoCacheMemo.has(filename)) {
    return demoCacheMemo.get(filename) as T;
  }
  try {
    const res = await fetch(`/demo-cache/${filename}`);
    if (!res.ok) return null;
    const parsed = (await res.json()) as T;
    demoCacheMemo.set(filename, parsed);
    return parsed;
  } catch {
    return null;
  }
}

export function matchDemoId(ra: number, dec: number): DemoTargetMeta["id"] | null {
  let bestId: DemoTargetMeta["id"] | null = null;
  let bestSep = 0.35;
  for (const c of DEMO_TARGETS) {
    const epochSeps = EPOCHS.map((ep) =>
      angularSeparationDeg(ra, dec, c.epochCoords[ep].ra, c.epochCoords[ep].dec)
    );
    const sep = Math.min(
      angularSeparationDeg(ra, dec, c.ra, c.dec),
      angularSeparationDeg(ra, dec, c.refRa, c.refDec),
      ...epochSeps
    );
    if (sep <= bestSep) {
      bestSep = sep;
      bestId = c.id;
    }
  }
  return bestId;
}

export async function getHealth(): Promise<{ health: HealthResponse; mode: DataMode }> {
  try {
    const health = await fetchJson<HealthResponse>("/api/v1/health");
    const mode: DataMode = health.data_mode ?? "physical_model";
    return { health, mode };
  } catch {
    return {
      health: {
        status: "degraded",
        version: "offline",
        engines: {},
      },
      mode: "offline_cache",
    };
  }
}

export interface SearchCatalogParams {
  q?: string;
  ra?: number;
  dec?: number;
  radius_arcmin?: number;
  include_field?: boolean;
  limit?: number;
  epoch?: Epoch;
}

export async function searchCatalog(
  params: SearchCatalogParams
): Promise<{ data: CatalogResponse; fromCache: boolean }> {
  const qs = new URLSearchParams();
  if (params.q !== undefined && params.q.trim() !== "") qs.set("q", params.q.trim());
  if (params.ra !== undefined) qs.set("ra", String(params.ra));
  if (params.dec !== undefined) qs.set("dec", String(params.dec));
  if (params.radius_arcmin !== undefined) qs.set("radius_arcmin", String(params.radius_arcmin));
  if (params.include_field !== undefined) qs.set("include_field", String(params.include_field));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.epoch !== undefined) qs.set("epoch", params.epoch);

  try {
    const data = await fetchJson<CatalogResponse>(`/api/v1/catalog/search?${qs.toString()}`);
    return { data, fromCache: false };
  } catch (err) {
    const cached = await fetchDemoCache<CatalogResponse>("catalog-demo.json");
    if (cached) {
      const applyEpochCoords = (item: CatalogObject): CatalogObject => {
        const meta = DEMO_TARGETS.find((d) => d.id === item.id);
        if (!meta) return item;
        if (params.epoch && meta.epochCoords[params.epoch]) {
          return {
            ...item,
            ra: meta.epochCoords[params.epoch].ra,
            dec: meta.epochCoords[params.epoch].dec,
          };
        }
        return { ...item, ra: meta.refRa, dec: meta.refDec };
      };
      const items = cached.results.map(applyEpochCoords);
      if (params.q) {
        const needle = params.q.trim().toLowerCase();
        const filtered = items.filter(
          (item) =>
            item.id.toLowerCase().includes(needle) ||
            item.name.toLowerCase().includes(needle) ||
            item.aliases?.some((a) => a.toLowerCase().includes(needle))
        );
        return {
          data: { query: cached.query, count: filtered.length, results: filtered },
          fromCache: true,
        };
      }
      if (params.ra !== undefined && params.dec !== undefined) {
        const radiusDeg = (params.radius_arcmin ?? 5) / 60;
        const matched = items
          .map((item) => {
            const sepDeg = angularSeparationDeg(params.ra!, params.dec!, item.ra, item.dec);
            return {
              ...item,
              separation_arcsec: Number((sepDeg * 3600).toFixed(3)),
            };
          })
          .filter((item) => (item.separation_arcsec ?? Infinity) <= radiusDeg * 3600)
          .sort((a, b) => (a.separation_arcsec ?? 0) - (b.separation_arcsec ?? 0));
        return {
          data: { query: { ra: params.ra, dec: params.dec }, count: matched.length, results: matched },
          fromCache: true,
        };
      }
      return { data: { ...cached, results: items }, fromCache: true };
    }
    throw err;
  }
}

export interface CutoutParams {
  ra: number;
  dec: number;
  epoch?: Epoch;
  size_px?: number;
  pixel_scale_arcsec?: number;
  band?: number;
}

export async function getSkyCutout(
  params: CutoutParams
): Promise<{ data: SkyImage; fromCache: boolean }> {
  const qs = new URLSearchParams({
    ra: String(params.ra),
    dec: String(params.dec),
    epoch: params.epoch ?? "2026-Q1",
    size_px: String(params.size_px ?? 64),
    pixel_scale_arcsec: String(params.pixel_scale_arcsec ?? 6.2),
    format: "json",
  });
  if (params.band !== undefined) {
    qs.set("band", String(params.band));
  }

  try {
    const data = await fetchJson<SkyImage>(`/api/v1/sky/cutout?${qs.toString()}`);
    return { data, fromCache: false };
  } catch (err) {
    const epoch = params.epoch ?? "2026-Q1";
    const id = matchDemoId(params.ra, params.dec);
    if (id) {
      const cached = await fetchDemoCache<SkyImage>(`cutout-${id}-${epoch}.json`);
      if (cached) {
        return { data: cached, fromCache: true };
      }
    }
    throw err;
  }
}

export interface SpectrumParams {
  ra: number;
  dec: number;
  epoch?: Epoch;
  aperture_arcsec?: number;
}

export async function getSpectrum(
  params: SpectrumParams
): Promise<{ data: SpectrumResponse; fromCache: boolean }> {
  const qs = new URLSearchParams({
    ra: String(params.ra),
    dec: String(params.dec),
    epoch: params.epoch ?? "2026-Q1",
  });
  if (params.aperture_arcsec !== undefined) {
    qs.set("aperture_arcsec", String(params.aperture_arcsec));
  }

  try {
    const data = await fetchJson<SpectrumResponse>(`/api/v1/spectrum?${qs.toString()}`);
    return { data, fromCache: false };
  } catch (err) {
    const epoch = params.epoch ?? "2026-Q1";
    const id = matchDemoId(params.ra, params.dec);
    if (id) {
      const cached = await fetchDemoCache<SpectrumResponse>(`spectrum-${id}-${epoch}.json`);
      if (cached) {
        return { data: cached, fromCache: true };
      }
    }
    throw err;
  }
}

function buildAnalysisBody(
  partial: Partial<AnalysisRequest> & { ra: number; dec: number }
): AnalysisRequest {
  return {
    ra: partial.ra,
    dec: partial.dec,
    size_px: partial.size_px ?? 64,
    pixel_scale_arcsec: partial.pixel_scale_arcsec ?? 6.2,
    band: partial.band ?? null,
    epoch_1: partial.epoch_1 ?? "2026-Q1",
    epoch_2: partial.epoch_2 ?? "2026-Q3",
    rate_arcsec_yr: partial.rate_arcsec_yr ?? 0,
    pa_deg: partial.pa_deg ?? 0,
    n_frames: partial.n_frames ?? 24,
    combine: partial.combine ?? "mean",
    rate_range_arcsec_yr: partial.rate_range_arcsec_yr ?? [20, 200],
    pa_range_deg: partial.pa_range_deg ?? [30, 90],
    grid: partial.grid ?? 5,
    distance_au: partial.distance_au === undefined ? null : partial.distance_au,
    distance_range_au:
      partial.distance_range_au === undefined ? [250, 1000] : partial.distance_range_au,
    cadence: partial.cadence ?? "uniform",
  };
}

export async function runDifference(
  params: Partial<AnalysisRequest> & { ra: number; dec: number }
): Promise<{ data: DifferenceResult; fromCache: boolean }> {
  const body = buildAnalysisBody(params);
  try {
    const data = await fetchJson<DifferenceResult>("/api/v1/analysis/difference", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { data, fromCache: false };
  } catch (err) {
    const id = matchDemoId(params.ra, params.dec);
    if (id) {
      const cached = await fetchDemoCache<DifferenceResult>(`diff-${id}.json`);
      if (cached) return { data: cached, fromCache: true };
    }
    throw err;
  }
}

export async function runShiftStack(
  params: Partial<AnalysisRequest> & { ra: number; dec: number }
): Promise<{ data: ShiftStackResult; fromCache: boolean }> {
  const body = buildAnalysisBody(params);
  try {
    const data = await fetchJson<ShiftStackResult>("/api/v1/analysis/shift-stack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { data, fromCache: false };
  } catch (err) {
    const id = matchDemoId(params.ra, params.dec);
    if (id) {
      const cached = await fetchDemoCache<ShiftStackResult>(`stack-${id}.json`);
      if (cached) return { data: cached, fromCache: true };
    }
    throw err;
  }
}

export async function runBlindSearch(
  params: Partial<AnalysisRequest> & { ra: number; dec: number }
): Promise<{ data: BlindSearchResult; fromCache: boolean }> {
  const body = buildAnalysisBody(params);
  try {
    const data = await fetchJson<BlindSearchResult>("/api/v1/analysis/blind-search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { data, fromCache: false };
  } catch (err) {
    const id = matchDemoId(params.ra, params.dec);
    if (id) {
      const cached = await fetchDemoCache<BlindSearchResult>(`blind-${id}.json`);
      if (cached) return { data: cached, fromCache: true };
    }
    throw err;
  }
}

export async function simulateOrbit(
  req: Partial<OrbitRequest>
): Promise<{ data: OrbitResult; fromCache: boolean }> {
  const body: OrbitRequest = {
    horizons_years: req.horizons_years ?? [1, 5, 10],
    samples_per_year: req.samples_per_year ?? 24,
    ...(req.target_id ? { target_id: req.target_id } : {}),
    ...(req.observation ? { observation: req.observation } : {}),
    ...(req.elements ? { elements: req.elements } : {}),
    ...(req.detections ? { detections: req.detections } : {}),
  };

  try {
    const data = await fetchJson<OrbitResult>("/api/v1/orbit/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { data, fromCache: false };
  } catch (err) {
    const cached = await fetchDemoCache<OrbitResult>("orbit-px-2026-09.json");
    if (cached) return { data: cached, fromCache: true };
    throw err;
  }
}

export async function getCrossmatch(params: {
  ra: number;
  dec: number;
  radius_arcsec?: number;
}): Promise<{ data: CrossmatchResult; fromCache: boolean }> {
  const qs = new URLSearchParams({
    ra: String(params.ra),
    dec: String(params.dec),
    radius_arcsec: String(params.radius_arcsec ?? 10),
  });

  try {
    const data = await fetchJson<CrossmatchResult>(`/api/v1/missions/crossmatch?${qs.toString()}`);
    return { data, fromCache: false };
  } catch (err) {
    const id = matchDemoId(params.ra, params.dec);
    if (id) {
      const cached = await fetchDemoCache<CrossmatchResult>(`crossmatch-${id}.json`);
      if (cached) return { data: cached, fromCache: true };
    }
    throw err;
  }
}

export async function sendAiCommand(params: {
  message: string;
  lang: "tr" | "en";
  context?: Record<string, unknown>;
}): Promise<{ data: AiCommandResponse; fromCache: boolean }> {
  try {
    const data = await fetchJson<AiCommandResponse>("/api/v1/ai/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return { data, fromCache: false };
  } catch {
    const lower = params.message.toLocaleLowerCase("tr-TR");
    const actions: UiAction[] = [];

    if (/\b(wise[\s-]*0855|0855|w0855)\b/i.test(lower)) {
      actions.push({
        type: "FLY_TO",
        params: { target_id: "wise-0855", ra: 133.7602, dec: -7.2422 },
      });
    } else if (/\b(rw[\s-]*aur(?:igae)?|hd\s*240764)\b/i.test(lower)) {
      actions.push({
        type: "FLY_TO",
        params: { target_id: "rw-aur", ra: 76.95642, dec: 30.40142 },
      });
    } else if (/\b(px[\s-]*2026[\s-]*09|planet\s*(?:x|9|nine)|gezegen\s*x)\b/i.test(lower)) {
      actions.push({
        type: "FLY_TO",
        params: { target_id: "px-2026-09", ra: 51.29547, dec: 14.83256 },
      });
    } else {
      const coordMatch = lower.match(
        /(?:ra\s*[:=]?\s*)?([+-]?\d+(?:\.\d+)?)\s*(?:[,;]\s*|\s+dec\s*[:=]?\s*|\s+)([+-]?\d+(?:\.\d+)?)/i
      );
      if (coordMatch) {
        const ra = Number(coordMatch[1]);
        const dec = Number(coordMatch[2]);
        if (ra >= 0 && ra <= 360 && dec >= -90 && dec <= 90) {
          actions.push({ type: "FLY_TO", params: { ra, dec } });
        }
      }
    }

    for (const ep of EPOCHS) {
      const qTag = ep.slice(-2).toLowerCase();
      if (lower.includes(ep.toLowerCase()) || new RegExp(`\\b${qTag}\\b`, "i").test(lower)) {
        actions.push({ type: "SET_EPOCH", params: { epoch: ep } });
      }
    }

    if (/\b(fark|diff(?:erence)?)\b/i.test(lower)) {
      actions.push({ type: "TOGGLE_DIFF", params: { open: true } });
    }
    if (/\b(kör|kor|blind)\b/i.test(lower)) {
      actions.push({ type: "RUN_BLIND_SEARCH", params: {} });
    } else if (/\b(shift|stack|yığ|yig|kaydır)\b/i.test(lower)) {
      actions.push({
        type: "RUN_SHIFT_STACK",
        params: { rate_arcsec_yr: 110, pa_deg: 62 },
      });
    }
    if (/\b(tayf|spektrum|spectr(?:um)?)\b/i.test(lower)) {
      actions.push({ type: "OPEN_SPECTRUM", params: {} });
    }
    if (/\b(3d|3b|yörünge|yorunge|orbit|rebound)\b/i.test(lower)) {
      actions.push({ type: "OPEN_3D_ORBIT", params: {} });
    }
    if (/\b(jwst|hubble|hst|pip)\b/i.test(lower)) {
      actions.push({ type: "OPEN_JWST", params: {} });
    }
    if (/\b(sed|crossmatch|eşleş|esles)\b/i.test(lower)) {
      actions.push({ type: "OPEN_CROSSMATCH", params: {} });
    }
    if (/\b(inferno|viridis|magma|grayscale)\b/i.test(lower)) {
      const cmap = lower.match(/\b(inferno|viridis|magma|grayscale)\b/i)?.[1]?.toLowerCase();
      if (cmap) actions.push({ type: "SET_COLORMAP", params: { colormap: cmap } });
    }
    if (/\b(türkçe|turkce)\b/i.test(lower)) {
      actions.push({ type: "SET_LANG", params: { lang: "tr" } });
    } else if (/\b(english|ingilizce)\b/i.test(lower)) {
      actions.push({ type: "SET_LANG", params: { lang: "en" } });
    }
    if (/\b(pdf|rapor|report)\b/i.test(lower)) {
      actions.push({ type: "GENERATE_PDF", params: {} });
    }
    if (/\b(demo|tur|tour)\b/i.test(lower)) {
      actions.push({ type: "START_DEMO_TOUR", params: {} });
    }

    const reply =
      params.lang === "tr"
        ? `Komut ayrıştırıldı (${actions.length} aksiyon uygulandı — yerel kural motoru).`
        : `Command parsed (${actions.length} action(s) executed — local rule parser).`;

    return {
      fromCache: true,
      data: {
        reply,
        lang: params.lang,
        actions,
      },
    };
  }
}

export async function classifyTarget(params: {
  flux_ujy?: number[];
  image?: SkyImage;
  ra?: number;
  dec?: number;
}): Promise<{ data: AiClassifyResponse; fromCache: boolean }> {
  try {
    const data = await fetchJson<AiClassifyResponse>("/api/v1/ai/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ flux_ujy: params.flux_ujy, image: params.image }),
    });
    return { data, fromCache: false };
  } catch {
    const id =
      params.ra !== undefined && params.dec !== undefined
        ? matchDemoId(params.ra, params.dec)
        : null;

    if (id === "wise-0855") {
      return {
        fromCache: true,
        data: {
          top_class: "cold_brown_dwarf",
          anomaly_score: 0.88,
          probabilities: {
            cold_brown_dwarf: 0.91,
            planet_x_candidate: 0.05,
            young_variable_star: 0.01,
            main_sequence_star: 0.01,
            high_z_galaxy: 0.02,
          },
          model_versions: {
            "1d_cnn": "aeon-spec-cnn-v1.0-fallback",
            patch_vit: "aeon-patch-vit-v1.0-fallback",
          },
        },
      };
    }

    if (id === "rw-aur") {
      return {
        fromCache: true,
        data: {
          top_class: "young_variable_star",
          anomaly_score: 0.72,
          probabilities: {
            young_variable_star: 0.89,
            main_sequence_star: 0.07,
            high_z_galaxy: 0.02,
            cold_brown_dwarf: 0.01,
            planet_x_candidate: 0.01,
          },
          model_versions: {
            "1d_cnn": "aeon-spec-cnn-v1.0-fallback",
            patch_vit: "aeon-patch-vit-v1.0-fallback",
          },
        },
      };
    }

    if (id === "px-2026-09") {
      return {
        fromCache: true,
        data: {
          top_class: "planet_x_candidate",
          anomaly_score: 0.96,
          probabilities: {
            planet_x_candidate: 0.87,
            cold_brown_dwarf: 0.09,
            high_z_galaxy: 0.02,
            young_variable_star: 0.01,
            main_sequence_star: 0.01,
          },
          model_versions: {
            "1d_cnn": "aeon-spec-cnn-v1.0-fallback",
            patch_vit: "aeon-patch-vit-v1.0-fallback",
          },
        },
      };
    }

    return {
      fromCache: true,
      data: {
        top_class: "main_sequence_star",
        anomaly_score: 0.24,
        probabilities: {
          main_sequence_star: 0.72,
          young_variable_star: 0.12,
          high_z_galaxy: 0.08,
          cold_brown_dwarf: 0.05,
          planet_x_candidate: 0.03,
        },
        model_versions: {
          "1d_cnn": "aeon-spec-cnn-v1.0-fallback",
          patch_vit: "aeon-patch-vit-v1.0-fallback",
        },
      },
    };
  }
}

const FALLBACK_GCN_ALERTS: GcnAlert[] = [
  {
    id: "GCN-2026-40112",
    kind: "GRB",
    time_utc: "2026-04-19T14:22:10Z",
    ra: 133.82,
    dec: -7.21,
    error_radius_deg: 0.08,
    title: "Fermi-GBM & Swift-BAT GRB 260419A Localization (Archived Notice)",
    url: "https://gcn.nasa.gov/circulars",
  },
  {
    id: "GCN-2026-40098",
    kind: "Neutrino",
    time_utc: "2026-04-18T21:05:44Z",
    ra: 77.04,
    dec: 30.38,
    error_radius_deg: 0.45,
    title: "IceCube-260418A High-Energy Track Alert near Auriga (Archived Notice)",
    url: "https://gcn.nasa.gov/circulars",
  },
  {
    id: "GCN-2026-40071",
    kind: "SN",
    time_utc: "2026-04-17T08:14:00Z",
    ra: 51.18,
    dec: 14.82,
    error_radius_deg: 0.02,
    title: "ZTF26aakq Transient Counterpart Candidate Follow-up (Archived Notice)",
    url: "https://gcn.nasa.gov/circulars",
  },
];

export async function getGcnAlerts(
  limit = 10
): Promise<{ data: GcnAlert[]; fromCache: boolean }> {
  try {
    const data = await fetchJson<GcnAlert[]>(`/api/v1/alerts/gcn?limit=${limit}`);
    return { data, fromCache: false };
  } catch {
    return { data: FALLBACK_GCN_ALERTS.slice(0, limit), fromCache: true };
  }
}

const CANDIDATES_STORAGE_KEY = "aeon_candidates_pool";

const INITIAL_CANDIDATES: Candidate[] = [
  {
    id: "cand-wise-0855",
    ra: 133.79513,
    dec: -7.24514,
    object_class: "cold_brown_dwarf",
    anomaly_score: 0.88,
    snr: 18.4,
    votes: 14,
    submitted_by: "IMU-AstroTeam",
    created_utc: "2026-04-19T10:00:00Z",
    notes: "High proper-motion (8.1 arcsec/yr) Y-dwarf dipole + deep 3.3 um CH4 band.",
  },
  {
    id: "cand-px-2026-09",
    ra: 51.2,
    dec: 14.8,
    object_class: "planet_x_candidate",
    anomaly_score: 0.96,
    snr: 7.4,
    votes: 23,
    submitted_by: "AEON-ShiftStack-Bot",
    created_utc: "2026-04-19T11:30:00Z",
    github_issue_url: "https://github.com/alpztel/aeon/issues",
    notes: "[SYNTHETIC TEST] Recovered at 110 arcsec/yr, PA 62 deg, d = 520 AU.",
  },
  {
    id: "cand-rw-aur",
    ra: 76.9564,
    dec: 30.4013,
    object_class: "young_variable_star",
    anomaly_score: 0.72,
    snr: 42.1,
    votes: 9,
    submitted_by: "T-Tauri-Patrol",
    created_utc: "2026-04-18T19:15:00Z",
    notes: "Strong 102-band continuum variability across 2026-Q1..Q4.",
  },
];

function loadLocalCandidates(): Candidate[] {
  try {
    const raw = window.sessionStorage.getItem(CANDIDATES_STORAGE_KEY);
    if (raw) return JSON.parse(raw) as Candidate[];
  } catch {
    // Ignore storage error
  }
  return INITIAL_CANDIDATES;
}

function saveLocalCandidates(list: Candidate[]): void {
  try {
    window.sessionStorage.setItem(CANDIDATES_STORAGE_KEY, JSON.stringify(list));
  } catch {
    // Ignore storage error
  }
}

export async function getCandidates(
  sort: "votes" | "recent" | "anomaly" = "votes",
  limit = 20
): Promise<{ data: Candidate[]; fromCache: boolean }> {
  try {
    const data = await fetchJson<Candidate[]>(
      `/api/v1/candidates?sort=${sort}&limit=${limit}`
    );
    return { data, fromCache: false };
  } catch {
    const list = [...loadLocalCandidates()];
    if (sort === "votes") {
      list.sort((a, b) => (b.votes ?? 0) - (a.votes ?? 0));
    } else if (sort === "anomaly") {
      list.sort((a, b) => (b.anomaly_score ?? 0) - (a.anomaly_score ?? 0));
    } else {
      list.sort((a, b) =>
        String(b.created_utc ?? "").localeCompare(String(a.created_utc ?? ""))
      );
    }
    return { data: list.slice(0, limit), fromCache: true };
  }
}

export async function submitOrVoteCandidate(body: {
  action: "submit" | "vote";
  candidate_id?: string;
  candidate?: Candidate;
}): Promise<{ data: Candidate; fromCache: boolean }> {
  try {
    const data = await fetchJson<Candidate>("/api/v1/candidates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { data, fromCache: false };
  } catch {
    const list = [...loadLocalCandidates()];
    if (body.action === "vote" && body.candidate_id) {
      const idx = list.findIndex((c) => c.id === body.candidate_id);
      if (idx >= 0) {
        const updated: Candidate = {
          ...list[idx],
          votes: (list[idx].votes ?? 0) + 1,
        };
        list[idx] = updated;
        saveLocalCandidates(list);
        return { data: updated, fromCache: true };
      }
    }

    if (body.action === "submit" && body.candidate) {
      const created: Candidate = {
        ...body.candidate,
        id: body.candidate.id ?? `cand-${Date.now()}`,
        votes: body.candidate.votes ?? 1,
        created_utc: new Date().toISOString(),
      };
      list.unshift(created);
      saveLocalCandidates(list);
      return { data: created, fromCache: true };
    }

    throw new ApiError("Candidate operation failed", 400);
  }
}
