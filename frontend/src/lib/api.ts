import type { components } from "./api-types";

export type HealthResponse = components["schemas"]["Health"];
export type Epoch = components["schemas"]["Epoch"];
export type ObjectClass = components["schemas"]["ObjectClass"];
export type CatalogObject = components["schemas"]["CatalogObject"];
export type CatalogResponse = components["schemas"]["CatalogResponse"];
export type SkyImage = components["schemas"]["Image"];

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
    const candidates = [
      { id: "wise-0855", ra: 133.79513, dec: -7.24514 },
      { id: "rw-aur", ra: 76.9564, dec: 30.4013 },
      { id: "px-2026-09", ra: 51.2, dec: 14.8 },
    ];
    const match = candidates.find(
      (c) => Math.abs(c.ra - params.ra) < 0.25 && Math.abs(c.dec - params.dec) < 0.25
    );
    if (match) {
      const cached = await fetchDemoCache<SkyImage>(`cutout-${match.id}-${epoch}.json`);
      if (cached) {
        return { data: cached, fromCache: true };
      }
    }
    throw err;
  }
}
