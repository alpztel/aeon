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

async function fetchDemoCache<T>(filename: string): Promise<T | null> {
  try {
    const res = await fetch(`/demo-cache/${filename}`);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export function matchDemoId(ra: number, dec: number): string | null {
  const candidates = [
    { id: "wise-0855", ra: 133.79513, dec: -7.24514 },
    { id: "rw-aur", ra: 76.9564, dec: 30.4013 },
    { id: "px-2026-09", ra: 51.2, dec: 14.8 },
  ];
  const match = candidates.find(
    (c) => Math.abs(c.ra - ra) < 0.25 && Math.abs(c.dec - dec) < 0.25
  );
  return match?.id ?? null;
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
      if (params.q) {
        const needle = params.q.trim().toLowerCase();
        const filtered = cached.results.filter(
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
      return { data: cached, fromCache: true };
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
      const cached =
        (await fetchDemoCache<SpectrumResponse>(`spectrum-${id}-${epoch}.json`)) ??
        (await fetchDemoCache<SpectrumResponse>(`spectrum-${id}.json`));
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
  } catch {
    const id = matchDemoId(params.ra, params.dec);
    if (id) {
      const cached = await fetchDemoCache<CrossmatchResult>(`crossmatch-${id}.json`);
      if (cached) return { data: cached, fromCache: true };
    }

    // Build scientifically consistent fallback from core spectrum + archival catalog parameters
    const sed: NonNullable<CrossmatchResult["sed"]> = [];
    try {
      const { data: spec } = await getSpectrum({ ra: params.ra, dec: params.dec });
      spec.wavelength_um.forEach((wl, i) => {
        if (i % 3 === 0) {
          sed.push({
            wavelength_um: wl,
            flux_ujy: spec.flux_ujy[i] ?? 0,
            flux_err_ujy: spec.flux_err_ujy[i],
            survey: "SPHEREx",
          });
        }
      });
    } catch {
      // Ignore spectrum fallback failure
    }

    if (id === "wise-0855") {
      sed.push(
        { wavelength_um: 3.35, flux_ujy: 1.9, flux_err_ujy: 0.4, survey: "WISE" },
        { wavelength_um: 4.6, flux_ujy: 87.1, flux_err_ujy: 2.4, survey: "WISE" },
        { wavelength_um: 11.56, flux_ujy: 260.0, flux_err_ujy: 18.0, survey: "WISE" },
        { wavelength_um: 22.09, flux_ujy: 410.0, flux_err_ujy: 45.0, survey: "WISE" }
      );
      return {
        fromCache: true,
        data: {
          gaia: [],
          wise: [
            {
              designation: "WISE J085510.83-071442.5",
              w1_ab: 18.4,
              w2_ab: 14.05,
              w3_ab: 11.85,
              pm_total_arcsec_yr: 8.15,
            },
          ],
          sed,
          unmatched_ir_candidate: true,
          mast_overlap: [
            {
              mission: "JWST",
              obs_id: "jw01902-o001_t001_nirspec",
              instrument: "NIRSpec / G395M",
              filter: "F290LP (2.87–5.10 µm)",
            },
            {
              mission: "HST",
              obs_id: "hst_13869_01_wfc3_ir_f127m",
              instrument: "WFC3/IR",
              filter: "F127M",
            },
          ],
        },
      };
    }

    if (id === "rw-aur") {
      sed.unshift(
        { wavelength_um: 0.504, flux_ujy: 1850, flux_err_ujy: 40, survey: "Gaia" },
        { wavelength_um: 0.623, flux_ujy: 2940, flux_err_ujy: 55, survey: "Gaia" },
        { wavelength_um: 0.773, flux_ujy: 4120, flux_err_ujy: 65, survey: "Gaia" }
      );
      sed.push(
        { wavelength_um: 3.35, flux_ujy: 8400, flux_err_ujy: 190, survey: "WISE" },
        { wavelength_um: 4.6, flux_ujy: 9850, flux_err_ujy: 210, survey: "WISE" },
        { wavelength_um: 11.56, flux_ujy: 14200, flux_err_ujy: 450, survey: "WISE" },
        { wavelength_um: 22.09, flux_ujy: 19600, flux_err_ujy: 780, survey: "WISE" }
      );
      return {
        fromCache: true,
        data: {
          gaia: [
            {
              source_id: "Gaia DR3 156431440590447744",
              phot_g_mean_mag: 10.48,
              bp_rp: 1.18,
              parallax_mas: 6.12,
            },
          ],
          wise: [
            {
              designation: "J050749.54+302405.1",
              w1_ab: 7.02,
              w2_ab: 6.45,
              w3_ab: 4.82,
            },
          ],
          sed,
          unmatched_ir_candidate: false,
          mast_overlap: [
            {
              mission: "HST",
              obs_id: "hst_14181_02_stis_fuv",
              instrument: "STIS / FUV-MAMA",
              filter: "G140L",
            },
          ],
        },
      };
    }

    return {
      fromCache: true,
      data: {
        gaia: [],
        wise: [],
        sed,
        unmatched_ir_candidate: true,
        mast_overlap: [],
      },
    };
  }
}
