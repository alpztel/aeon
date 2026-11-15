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
export type AiCommandResponse =
  operations["aiCommand"]["responses"]["200"]["content"]["application/json"];
export type AiClassifyResponse =
  operations["aiClassify"]["responses"]["200"]["content"]["application/json"];
export type CrossmatchResult =
  operations["missionsCrossmatch"]["responses"]["200"]["content"]["application/json"];
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

/** FastAPI sends `detail` as a string (HTTPException) or as a list of validation errors. */
function describeErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail) return detail.slice(0, 300);
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && typeof (d as { msg?: unknown }).msg === "string" ? (d as { msg: string }).msg : null))
      .filter((m): m is string => Boolean(m));
    if (msgs.length) return msgs.join("; ").slice(0, 300);
  }
  return null;
}

/** True when the service itself could not answer (network error, timeout, gateway/5xx), not when it rejected the request. */
export function isServiceDown(err: unknown): boolean {
  if (!(err instanceof ApiError)) return true;
  return err.status === 0 || err.status === 408 || err.status >= 500;
}

// Worth one automatic retry: the request never reached the service or the gateway had no upstream.
const TRANSIENT_STATUS = new Set([0, 502, 503, 504]);
const RETRY_DELAY_MS = 1_200;

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
        const body = (await res.json()) as { detail?: unknown };
        detail = describeErrorDetail(body?.detail) ?? detail;
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
    epoch: "2026-Q2", // SPHEREx visited WISE 0855 in Q2 and Q4: open on real data
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
  // No offline substitute: class probabilities and anomaly scores only come from the ai-engine.
  // The engine needs a spectrum, an image or a sky position; given only (ra, dec) it reads the
  // spectrum from the archive itself. Leaving ra/dec out of the body made every call a 422.
  const body = JSON.stringify({
    flux_ujy: params.flux_ujy,
    image: params.image,
    ra: params.ra,
    dec: params.dec,
  });
  const call = async () => {
    const data = await fetchJson<AiClassifyResponse>("/api/v1/ai/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    // A 200 that is not a classification (proxy error page parsed as JSON, null, ...) is a broken service.
    const probs = (data as { probabilities?: unknown } | null)?.probabilities;
    if (!probs || typeof probs !== "object" || Array.isArray(probs)) {
      throw new ApiError("Malformed classification response", 502);
    }
    return data;
  };
  try {
    return { data: await call(), fromCache: false };
  } catch (err) {
    if (!(err instanceof ApiError) || !TRANSIENT_STATUS.has(err.status)) throw err;
    await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
    return { data: await call(), fromCache: false };
  }
}

// ------------------------------------------------------------------ provenance readers
// openapi types `Spectrum.pipeline` and `Image.provenance` as open objects; these readers give the
// fields the backend documents a type, and drop anything malformed instead of trusting it.

export interface SpectrumPipelineInfo {
  data_mode?: "fits_archive" | "physical_model";
  source?: string;
  measured?: boolean[];
  n_bands_measured?: number;
  n_frames?: number;
  n_frames_used?: number;
  n_frames_rejected?: number;
  obs_date_range?: [string, string] | null;
  observed_quarter?: string | null;
  epoch_folded?: boolean;
  archive_fallback_reason?: string;
  aperture_px?: number | null;
  epoch_selection?: { chosen?: string; candidates?: Record<string, unknown> };
  blended?: boolean[];
  n_bands_blended?: number;
  blend_offset_arcsec?: number | null;
}

export interface ImageProvenanceInfo {
  source?: string;
  n_frames?: number;
  obs_date_range?: [string, string] | null;
  observed_quarter?: string | null;
  epoch_folded?: boolean;
  wavelength_range_um?: [number, number] | null;
  coverage?: number;
  filled_pixels?: number;
  native_pixel_scale_arcsec?: number;
}

function asObject(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

export function spectrumPipeline(s: SpectrumResponse | null | undefined): SpectrumPipelineInfo {
  const p = asObject(s?.pipeline);
  const measured = Array.isArray(p.measured) && p.measured.every((b) => typeof b === "boolean") ? (p.measured as boolean[]) : undefined;
  const blended = Array.isArray(p.blended) && p.blended.every((b) => typeof b === "boolean") ? (p.blended as boolean[]) : undefined;
  return { ...(p as SpectrumPipelineInfo), measured, blended };
}

export function imageProvenance(img: SkyImage | null | undefined): ImageProvenanceInfo {
  return asObject((img as { provenance?: unknown } | null | undefined)?.provenance) as ImageProvenanceInfo;
}

// ------------------------------------------------------------------ example gallery
/** Catalog ids shown in the example gallery (grouped by class there). Ids the backend does not
 * know (older deployment) are simply not shown. */
export const EXAMPLE_TARGET_IDS: readonly string[] = [
  "wise-0855",
  "wise-1828",
  "wise-1738",
  "luhman-16",
  "px-2026-09",
  "tw-hya",
  "rw-aur",
  "trappist-1",
  "lhs-1140",
  "barnard",
  "18-sco",
  "apm-08279",
  "cloverleaf",
  "sdss-1148",
];

/** Spectrum without an epoch: the backend picks the quarter with the best real SPHEREx data and
 * lists every quarter it compared in pipeline.epoch_selection. */
export async function getBestEpochSpectrum(ra: number, dec: number): Promise<SpectrumResponse> {
  const qs = new URLSearchParams({ ra: String(ra), dec: String(dec) });
  return fetchJson<SpectrumResponse>(`/api/v1/spectrum?${qs.toString()}`);
}

// ------------------------------------------------------------------ stage 2-4: age, orbit, validation
// Optional blocks of the cross-match answer (openapi: age_mass, kinematics.galactic, galactic_orbit,
// validation) and the Galactic regime of /orbit/simulate. Typed here; read through stage24().

export interface AgeChannel {
  status?: string;
  median_gyr?: number | null;
  lo_gyr?: number | null;
  hi_gyr?: number | null;
  constraint?: "constrained" | "weak" | "unconstrained";
  pdf?: number[] | null;
  method?: string;
  reason?: string | null;
  channels?: string[];
}

export interface ModelRange {
  median: number;
  lo: number;
  hi: number;
}

export interface MassEstimate {
  median_msun: number;
  lo_msun: number;
  hi_msun: number;
  median_mjup: number;
  lo_mjup: number;
  hi_mjup: number;
  from?: string;
  model_teff_k?: ModelRange;
  model_log_g_cgs?: ModelRange;
  model_radius_rjup?: ModelRange;
  model_log_l_lsun?: ModelRange;
}

export interface AgeMass {
  status?: "ok" | "partial" | "unmeasured" | "not_applicable";
  reason?: string | null;
  mode?: "substellar_w2" | "stellar_hr" | "none";
  inputs?: Record<string, unknown>;
  assumptions?: Record<string, string>;
  age_grid_gyr?: number[];
  spectral?: AgeChannel;
  kinematic?: AgeChannel;
  joint?: AgeChannel;
  mass?: MassEstimate | null;
  mass_spectral_only?: MassEstimate | null;
  degeneracy_track?: Array<{ age_gyr: number; mass_mjup: number; teff_k: number; log_g_cgs: number }>;
  references?: Record<string, string>;
}

export interface GalacticSolution {
  rv_km_s: number;
  u_lsr_km_s: number;
  v_lsr_km_s: number;
  w_lsr_km_s: number;
  v_tot_km_s: number;
  membership?: { probabilities?: Record<string, number> | null; most_likely?: string | null };
}

export interface GalacticKinematics {
  status?: "ok" | "unmeasured" | "not_applicable";
  reason?: string | null;
  rv_status?: "measured" | "marginalized_envelope";
  inputs?: Record<string, unknown> | null;
  solutions?: GalacticSolution[];
  envelope?: Record<string, number[]>;
}

/** A number when the radial velocity is measured, a [min, max] envelope otherwise. */
export type MaybeRange = number | number[];

export interface GalacticSummary {
  r_peri_kpc?: MaybeRange;
  r_apo_kpc?: MaybeRange;
  z_max_kpc?: MaybeRange;
  eccentricity?: MaybeRange;
  t_min_kyr?: MaybeRange;
  d_min_pc?: MaybeRange;
  encounter_status?: string;
}

export interface ScorecardRow {
  key: string;
  label?: { en: string; tr: string };
  unit?: string;
  aeon_text?: string;
  reference_text?: string;
  aeon_source?: string | null;
  reference_source?: string | null;
  agreement: "consistent" | "partial" | "discrepant" | "not_comparable";
  explanation?: { en: string; tr: string } | null;
  not_comparable_reason?: string | null;
}

export interface Validation {
  status?: "ok" | "no_reference" | "not_applicable";
  reason?: string | null;
  simbad?: { status?: string; source?: string; reason?: string | null; object?: Record<string, unknown> | null };
  literature?: { sources?: Array<{ ref: string; bibcode: string; arxiv?: string; doi?: string | null }> } | null;
  rows?: ScorecardRow[];
  counts?: Record<string, number>;
  rule?: string;
  synthesis?: { en: string; tr: string; method?: string };
}

export interface Stage24 {
  ageMass: AgeMass | null;
  galactic: GalacticKinematics | null;
  validation: Validation | null;
}

export function stage24(data: CrossmatchResult | null | undefined): Stage24 {
  const d = (data ?? {}) as Record<string, unknown>;
  const kin = (d.kinematics ?? {}) as Record<string, unknown>;
  return {
    ageMass: (d.age_mass as AgeMass | undefined) ?? null,
    galactic: (kin.galactic as GalacticKinematics | undefined) ?? null,
    validation: (d.validation as Validation | undefined) ?? null,
  };
}

// Several panels read the same cross-match answer: one request per position.
const crossmatchInflight = new Map<string, Promise<{ data: CrossmatchResult; fromCache: boolean }>>();

export function getCrossmatchShared(ra: number, dec: number): Promise<{ data: CrossmatchResult; fromCache: boolean }> {
  const key = `${ra.toFixed(5)}:${dec.toFixed(5)}`;
  const hit = crossmatchInflight.get(key);
  if (hit) return hit;
  const p = getCrossmatch({ ra, dec, radius_arcsec: 10 });
  crossmatchInflight.set(key, p);
  p.catch(() => crossmatchInflight.delete(key));
  if (crossmatchInflight.size > 24) {
    const first = crossmatchInflight.keys().next().value;
    if (first !== undefined && first !== key) crossmatchInflight.delete(first);
  }
  return p;
}

export interface GalacticTrajectory {
  t_myr: number[];
  x_kpc: number[];
  y_kpc: number[];
  z_kpc: number[];
  r_kpc: number[];
}

export interface GalacticOrbitResult {
  engine: string;
  rv_status: "measured" | "marginalized_envelope";
  span_myr: number;
  encounter_window_kyr: number;
  orbits: Array<{
    rv_km_s: number;
    r_peri_kpc: number;
    r_apo_kpc: number;
    z_max_kpc: number;
    eccentricity: number;
    trajectory: GalacticTrajectory;
  }>;
  encounters: Array<{
    rv_km_s: number;
    status: "found" | "beyond_window";
    t_min_kyr: number;
    d_min_pc: number;
    d_now_pc: number;
    curve: { t_kyr: number[]; distance_pc: number[] };
  }>;
  sun: GalacticTrajectory;
  summary: GalacticSummary;
}

export interface GalacticAstrometry {
  ra: number;
  dec: number;
  distance_pc: number;
  pm_ra_cosdec_mas_yr: number;
  pm_dec_mas_yr: number;
  radial_velocity_km_s?: number | null;
}

/** Galactic orbit (galpy, MWPotential2014) and solar encounter for explicit astrometry or a catalog target. */
export async function simulateGalacticOrbit(req: { target_id?: string; galactic?: GalacticAstrometry }): Promise<GalacticOrbitResult> {
  const res = await fetchJson<{ galactic?: GalacticOrbitResult }>("/api/v1/orbit/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...req, regime: "galactic" }),
  });
  if (!res.galactic || !Array.isArray(res.galactic.orbits)) throw new ApiError("No Galactic orbit in the answer", 502);
  return res.galactic;
}
