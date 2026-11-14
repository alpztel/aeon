"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Crosshair,
  Globe,
  Loader2,
  MapPin,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import { useI18n } from "@/i18n/context";
import {
  DEMO_TARGETS,
  EPOCHS,
  EPOCH_DECIMAL,
  getSkyCutout,
  searchCatalog,
  type CatalogObject,
  type Epoch,
  type SkyImage,
} from "@/lib/api";
import {
  COLORMAP_OPTIONS,
  renderSkyArrayToCanvas,
  type ColormapName,
} from "@/lib/colormaps";

interface SkyMapPanelProps {
  selectedObject: CatalogObject | null;
  onSelectObject: (
    obj: CatalogObject | null,
    coords: { ra: number; dec: number },
    refCoords?: { ra: number; dec: number }
  ) => void;
  epoch: Epoch;
  onEpochChange: (epoch: Epoch) => void;
  coords: { ra: number; dec: number };
}

const ALADIN_SCRIPT_URL =
  "https://aladin.cds.unistra.fr/AladinLite/api/v3/3.5.1/aladin.js";

interface AladinInstance {
  gotoRaDec: (ra: number, dec: number) => void;
  setFoV: (fovDeg: number) => void;
}

declare global {
  interface Window {
    A?: {
      init: Promise<void>;
      aladin: (selector: string | HTMLElement, options: Record<string, unknown>) => AladinInstance;
    };
  }
}

export function SkyMapPanel({
  selectedObject,
  onSelectObject,
  epoch,
  onEpochChange,
  coords,
}: SkyMapPanelProps) {
  const { dict, bilingual } = useI18n();

  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [cutout, setCutout] = useState<SkyImage | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [cutoutError, setCutoutError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [colormap, setColormap] = useState<ColormapName>("inferno");
  const [renderer, setRenderer] = useState<"canvas" | "aladin">("canvas");
  const [aladinFailed, setAladinFailed] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const aladinContainerRef = useRef<HTMLDivElement | null>(null);
  const aladinInstanceRef = useRef<AladinInstance | null>(null);
  const searchSeqRef = useRef(0);

  const sizePx = 64;
  const pixelScaleArcsec = 6.2;
  const fovArcmin = ((sizePx * pixelScaleArcsec) / 60).toFixed(1);
  const requestKey = `${coords.ra}:${coords.dec}:${epoch}`;
  const loadingCutout = loadedKey !== requestKey;

  useEffect(() => {
    let active = true;
    getSkyCutout({
      ra: coords.ra,
      dec: coords.dec,
      epoch,
      size_px: sizePx,
      pixel_scale_arcsec: pixelScaleArcsec,
    })
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setCutout(data);
        setFromCache(cached);
        setCutoutError(null);
        setLoadedKey(`${coords.ra}:${coords.dec}:${epoch}`);
      })
      .catch(() => {
        if (!active) return;
        setCutoutError(dict.sky.cutoutError);
        setLoadedKey(`${coords.ra}:${coords.dec}:${epoch}`);
      });
    return () => {
      active = false;
    };
  }, [coords.ra, coords.dec, epoch, dict.sky.cutoutError]);

  useEffect(() => {
    if (!cutout || !canvasRef.current) return;
    renderSkyArrayToCanvas(
      canvasRef.current,
      cutout.data,
      cutout.width,
      cutout.height,
      colormap
    );
  }, [cutout, colormap]);

  // Optional Aladin Lite v3 loader with automatic fallback to Canvas
  useEffect(() => {
    if (renderer !== "aladin" || aladinFailed) return;
    let cancelled = false;

    const mountAladin = async () => {
      try {
        if (!window.A) {
          await new Promise<void>((resolve, reject) => {
            const script = document.createElement("script");
            script.src = ALADIN_SCRIPT_URL;
            script.async = true;
            script.onload = () => resolve();
            script.onerror = () => reject(new Error("Aladin script load failed"));
            document.head.appendChild(script);
          });
        }
        if (cancelled || !window.A || !aladinContainerRef.current) return;
        await window.A.init;
        if (cancelled || !aladinContainerRef.current) return;

        if (!aladinInstanceRef.current) {
          aladinInstanceRef.current = window.A.aladin(aladinContainerRef.current, {
            survey: "P/allWISE/color",
            fov: Number(fovArcmin) / 60,
            target: `${coords.ra} ${coords.dec}`,
            showReticle: true,
            showZoomControl: true,
            showLayersControl: false,
          });
        } else {
          aladinInstanceRef.current.gotoRaDec(coords.ra, coords.dec);
        }
      } catch {
        if (!cancelled) {
          setAladinFailed(true);
          setRenderer("canvas");
        }
      }
    };

    mountAladin();
    return () => {
      cancelled = true;
    };
  }, [renderer, aladinFailed, coords.ra, coords.dec, fovArcmin]);

  const handleSelectTargetId = async (
    targetId: string,
    fallbackRa: number,
    fallbackDec: number,
    fallbackRefRa?: number,
    fallbackRefDec?: number
  ) => {
    const seq = ++searchSeqRef.current;
    setSearchError(null);
    setSearching(true);
    try {
      const [epochRes, refRes] = await Promise.all([
        searchCatalog({ q: targetId, epoch }),
        searchCatalog({ q: targetId }),
      ]);
      if (seq !== searchSeqRef.current) return;
      const hit = epochRes.data.results[0];
      const refHit = refRes.data.results[0];
      if (hit) {
        onSelectObject(
          hit,
          { ra: hit.ra, dec: hit.dec },
          {
            ra: refHit?.ra ?? fallbackRefRa ?? hit.ra,
            dec: refHit?.dec ?? fallbackRefDec ?? hit.dec,
          }
        );
      } else {
        onSelectObject(
          null,
          { ra: fallbackRa, dec: fallbackDec },
          {
            ra: fallbackRefRa ?? fallbackRa,
            dec: fallbackRefDec ?? fallbackDec,
          }
        );
      }
    } catch {
      if (seq !== searchSeqRef.current) return;
      onSelectObject(
        null,
        { ra: fallbackRa, dec: fallbackDec },
        {
          ra: fallbackRefRa ?? fallbackRa,
          dec: fallbackRefDec ?? fallbackDec,
        }
      );
    } finally {
      if (seq === searchSeqRef.current) {
        setSearching(false);
      }
    }
  };

  const handleSearchSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const raw = query.trim();
    if (!raw) return;

    const seq = ++searchSeqRef.current;
    setSearchError(null);
    setSearching(true);

    // Check if user entered numeric "RA Dec" or "RA, Dec"
    const coordMatch = raw.match(/^\s*([+-]?\d+(?:\.\d+)?)\s*[,;\s]\s*([+-]?\d+(?:\.\d+)?)\s*$/);
    if (coordMatch) {
      const ra = Number(coordMatch[1]);
      const dec = Number(coordMatch[2]);
      if (ra < 0 || ra > 360 || dec < -90 || dec > 90) {
        setSearchError(dict.errors.invalidCoords);
        setSearching(false);
        return;
      }
      try {
        const { data } = await searchCatalog({
          ra,
          dec,
          radius_arcmin: 5,
          include_field: true,
          epoch,
        });
        if (seq !== searchSeqRef.current) return;
        const hit = data.results[0] ?? null;
        if (hit && hit.source !== "field") {
          try {
            const { data: refData } = await searchCatalog({ q: hit.id });
            if (seq !== searchSeqRef.current) return;
            const refHit = refData.results[0];
            onSelectObject(
              hit,
              { ra, dec },
              { ra: refHit?.ra ?? ra, dec: refHit?.dec ?? dec }
            );
            return;
          } catch {
            // fallback below
          }
        }
        onSelectObject(hit, { ra, dec }, { ra, dec });
      } catch {
        if (seq !== searchSeqRef.current) return;
        onSelectObject(null, { ra, dec }, { ra, dec });
      } finally {
        if (seq === searchSeqRef.current) {
          setSearching(false);
        }
      }
      return;
    }

    // Name / designation search
    try {
      const [epochRes, refRes] = await Promise.all([
        searchCatalog({ q: raw, epoch }),
        searchCatalog({ q: raw }),
      ]);
      if (seq !== searchSeqRef.current) return;
      const hit = epochRes.data.results[0];
      const refHit = refRes.data.results[0];
      if (!hit) {
        setSearchError(dict.sky.noResults);
      } else {
        onSelectObject(
          hit,
          { ra: hit.ra, dec: hit.dec },
          { ra: refHit?.ra ?? hit.ra, dec: refHit?.dec ?? hit.dec }
        );
      }
    } catch {
      if (seq !== searchSeqRef.current) return;
      setSearchError(dict.errors.network);
    } finally {
      if (seq === searchSeqRef.current) {
        setSearching(false);
      }
    }
  };

  const epochIndex = EPOCHS.indexOf(epoch);

  return (
    <section className="aeon-panel rounded-2xl p-4 sm:p-5">
      {/* Top Bar: Title + Search + Renderer */}
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-2.5">
          <Globe className="h-4 w-4 text-cyan-400" />
          <h1 className="text-sm font-semibold uppercase tracking-wider text-white">
            {dict.sky.title}
          </h1>
          {fromCache && (
            <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300">
              {dict.header.dataMode.offline_cache}
            </span>
          )}
        </div>

        <form onSubmit={handleSearchSubmit} className="flex w-full max-w-xl items-center gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={dict.sky.searchPlaceholder}
              className="w-full rounded-xl border border-white/10 bg-black/40 py-2 pl-9 pr-3 text-xs text-white placeholder:text-slate-500 focus:border-cyan-400/60 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={searching}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-cyan-400/35 bg-cyan-500/15 px-3.5 py-2 text-xs font-medium text-cyan-200 transition hover:bg-cyan-500/25 disabled:opacity-50"
          >
            {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Crosshair className="h-3.5 w-3.5" />}
            <span>{searching ? dict.sky.searching : dict.sky.searchButton}</span>
          </button>
        </form>
      </div>

      {/* Quick Demo Targets + Colormap + Renderer */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[11px] font-medium uppercase tracking-wider text-slate-400">
            {dict.sky.quickTargets}:
          </span>
          {DEMO_TARGETS.map((qt) => {
            const active = selectedObject?.id === qt.id;
            const epCoord = qt.epochCoords[epoch] ?? { ra: qt.ra, dec: qt.dec };
            return (
              <button
                key={qt.id}
                type="button"
                onClick={() =>
                  handleSelectTargetId(
                    qt.id,
                    epCoord.ra,
                    epCoord.dec,
                    qt.refRa,
                    qt.refDec
                  )
                }
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition ${
                  active
                    ? "border-amber-400/50 bg-amber-500/20 text-amber-200"
                    : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
                }`}
              >
                <span>{qt.label}</span>
                {qt.synthetic && (
                  <span className="rounded bg-rose-500/20 px-1 py-0.2 text-[9px] uppercase tracking-wider text-rose-300">
                    SYN
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/30 px-2.5 py-1 text-xs">
            <SlidersHorizontal className="h-3.5 w-3.5 text-slate-400" />
            <span className="text-slate-400">{dict.sky.colormap}:</span>
            <select
              value={colormap}
              onChange={(e) => setColormap(e.target.value as ColormapName)}
              className="bg-transparent text-xs font-medium text-cyan-200 focus:outline-none"
            >
              {COLORMAP_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value} className="bg-[#090D16]">
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {!aladinFailed && (
            <div className="inline-flex rounded-lg border border-white/10 bg-white/5 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setRenderer("canvas")}
                className={`rounded-md px-2.5 py-1 transition ${
                  renderer === "canvas" ? "bg-cyan-500/20 text-cyan-200" : "text-slate-400 hover:text-white"
                }`}
              >
                {dict.sky.rendererCanvas}
              </button>
              <button
                type="button"
                onClick={() => setRenderer("aladin")}
                className={`rounded-md px-2.5 py-1 transition ${
                  renderer === "aladin" ? "bg-cyan-500/20 text-cyan-200" : "text-slate-400 hover:text-white"
                }`}
              >
                {dict.sky.rendererAladin}
              </button>
            </div>
          )}
        </div>
      </div>

      {searchError && (
        <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {searchError}
        </div>
      )}

      {/* Main Grid: Viewport + Telemetry Card */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Viewport */}
        <div className="relative overflow-hidden rounded-xl border border-white/10 bg-black/60 lg:col-span-8">
          <div className="relative aspect-square max-h-[460px] w-full">
            {renderer === "aladin" && !aladinFailed ? (
              <div ref={aladinContainerRef} className="h-full w-full" />
            ) : (
              <>
                <canvas
                  ref={canvasRef}
                  className="h-full w-full object-contain [image-rendering:pixelated]"
                />
                {/* Center Reticle */}
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                  <div className="h-8 w-8 rounded-full border border-cyan-400/50" />
                </div>
              </>
            )}

            {/* Loading Overlay */}
            {loadingCutout && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-xs">
                <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-[#090D16]/90 px-3 py-2 text-xs text-slate-200">
                  <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
                  <span>{dict.sky.loadingCutout}</span>
                </div>
              </div>
            )}

            {cutoutError && !loadingCutout && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/70 p-4 text-center text-xs text-rose-300">
                {cutoutError}
              </div>
            )}

            {/* HUD Overlays */}
            <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap gap-1.5">
              <span className="aeon-mono rounded-md border border-white/10 bg-black/70 px-2 py-0.5 text-[11px] text-slate-200">
                {dict.sky.fov}: {fovArcmin}′ × {fovArcmin}′
              </span>
              <span className="aeon-mono rounded-md border border-white/10 bg-black/70 px-2 py-0.5 text-[11px] text-slate-300">
                {pixelScaleArcsec}″/px
              </span>
              <span className="rounded-md border border-white/10 bg-black/70 px-2 py-0.5 text-[11px] text-cyan-300">
                {dict.sky.bandAll}
              </span>
            </div>

            <div className="pointer-events-none absolute right-3 top-3 rounded-md border border-white/10 bg-black/70 px-2 py-0.5 text-[11px] font-medium text-slate-300">
              {dict.sky.northUpEastLeft}
            </div>
          </div>

          {/* Timeline Slider */}
          <div className="border-t border-white/10 bg-[#090D16]/90 px-4 py-3">
            <div className="mb-2 flex items-center justify-between text-xs">
              <span className="font-medium text-slate-300">{dict.sky.timeline}</span>
              <span className="aeon-mono text-amber-300">
                {epoch} ({EPOCH_DECIMAL[epoch].toFixed(3)})
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={EPOCHS.length - 1}
              step={1}
              value={epochIndex >= 0 ? epochIndex : 0}
              onChange={(e) => onEpochChange(EPOCHS[Number(e.target.value)])}
              aria-label={dict.sky.timeline}
              className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-white/15 accent-amber-400"
            />
            <div className="mt-1.5 flex justify-between text-[11px] text-slate-400">
              {EPOCHS.map((ep) => (
                <button
                  key={ep}
                  type="button"
                  onClick={() => onEpochChange(ep)}
                  className={`aeon-mono transition ${
                    ep === epoch ? "font-semibold text-amber-300" : "hover:text-slate-200"
                  }`}
                >
                  {ep}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Target Telemetry Card */}
        <div className="flex flex-col gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-4 lg:col-span-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-slate-400">
                <MapPin className="h-3.5 w-3.5 text-amber-400" />
                <span>{dict.sky.coordinates}</span>
              </div>
              <h2 className="mt-1 text-base font-semibold text-white">
                {selectedObject?.name ?? `ICRS ${coords.ra.toFixed(4)}°, ${coords.dec.toFixed(4)}°`}
              </h2>
            </div>
          </div>

          {selectedObject?.is_synthetic && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-500/40 bg-rose-500/15 px-3 py-2 text-xs text-rose-200">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />
              <div>
                <p className="font-semibold">{dict.badges.synthetic}</p>
                <p className="mt-0.5 text-[11px] text-rose-200/80">{dict.badges.syntheticHint}</p>
              </div>
            </div>
          )}

          {selectedObject?.description && (
            <p className="text-xs leading-relaxed text-slate-300">
              {bilingual(selectedObject.description)}
            </p>
          )}

          <dl className="grid grid-cols-2 gap-2.5 text-xs">
            <div className="rounded-lg border border-white/5 bg-black/30 p-2.5">
              <dt className="text-[11px] text-slate-400">{dict.sky.ra}</dt>
              <dd className="aeon-mono mt-0.5 font-medium text-cyan-200">
                {coords.ra.toFixed(5)}°
              </dd>
            </div>
            <div className="rounded-lg border border-white/5 bg-black/30 p-2.5">
              <dt className="text-[11px] text-slate-400">{dict.sky.dec}</dt>
              <dd className="aeon-mono mt-0.5 font-medium text-cyan-200">
                {coords.dec >= 0 ? "+" : ""}
                {coords.dec.toFixed(5)}°
              </dd>
            </div>

            {selectedObject && (
              <>
                <div className="rounded-lg border border-white/5 bg-black/30 p-2.5">
                  <dt className="text-[11px] text-slate-400">{dict.sky.class}</dt>
                  <dd className="mt-0.5 font-medium text-violet-200">
                    {dict.classes[selectedObject.object_class]}
                  </dd>
                </div>

                <div className="rounded-lg border border-white/5 bg-black/30 p-2.5">
                  <dt className="text-[11px] text-slate-400">{dict.sky.properMotion}</dt>
                  <dd className="aeon-mono mt-0.5 font-medium text-amber-200">
                    {selectedObject.pm_ra_cosdec_arcsec_yr !== undefined
                      ? `${Math.hypot(
                          selectedObject.pm_ra_cosdec_arcsec_yr,
                          selectedObject.pm_dec_arcsec_yr ?? 0
                        ).toFixed(2)}″/yr`
                      : "—"}
                  </dd>
                </div>

                {(selectedObject.distance_au !== null && selectedObject.distance_au !== undefined) ||
                (selectedObject.distance_pc !== null && selectedObject.distance_pc !== undefined) ? (
                  <div className="rounded-lg border border-white/5 bg-black/30 p-2.5">
                    <dt className="text-[11px] text-slate-400">{dict.sky.distance}</dt>
                    <dd className="aeon-mono mt-0.5 font-medium text-slate-200">
                      {selectedObject.distance_au
                        ? `${selectedObject.distance_au} AU`
                        : `${selectedObject.distance_pc} pc`}
                    </dd>
                  </div>
                ) : null}

                {selectedObject.teff_k ? (
                  <div className="rounded-lg border border-white/5 bg-black/30 p-2.5">
                    <dt className="text-[11px] text-slate-400">{dict.sky.teff}</dt>
                    <dd className="aeon-mono mt-0.5 font-medium text-slate-200">
                      {selectedObject.teff_k} K
                    </dd>
                  </div>
                ) : null}
              </>
            )}
          </dl>
        </div>
      </div>
    </section>
  );
}
