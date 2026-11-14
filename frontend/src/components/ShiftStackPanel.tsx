"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Compass,
  Grid,
  Loader2,
  Radar,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { useI18n } from "@/i18n/context";
import {
  runBlindSearch,
  runShiftStack,
  type AstrometryPoint,
  type BlindSearchResult,
  type CatalogObject,
  type ShiftStackResult,
} from "@/lib/api";
import {
  COLORMAP_OPTIONS,
  renderSkyArrayToCanvas,
  type ColormapName,
} from "@/lib/colormaps";

interface ShiftStackPanelProps {
  coords: { ra: number; dec: number };
  selectedObject: CatalogObject | null;
  onAstrometryReady?: (points: AstrometryPoint[]) => void;
}

function SnrGrid({
  title,
  grid,
  rates,
  pas,
  onSelectVector,
}: {
  title: string;
  grid: number[][];
  rates?: number[];
  pas?: number[];
  onSelectVector: (rate: number, pa: number) => void;
}) {
  const flat = grid.flat().filter((v) => Number.isFinite(v));
  const minVal = Math.min(...flat, 0);
  const maxVal = Math.max(...flat, minVal + 1);

  return (
    <div className="rounded-xl border border-white/10 bg-black/40 p-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
        {title}
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-center text-[11px]">
          <thead>
            <tr>
              <th className="p-1 text-left text-[10px] text-slate-500">Rate \ PA</th>
              {(pas ?? grid[0]?.map((_, j) => j) ?? []).map((pa, j) => (
                <th key={j} className="aeon-mono p-1 text-slate-400">
                  {typeof pa === "number" ? `${pa.toFixed(0)}°` : pa}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.map((row, i) => {
              const rateVal = rates?.[i];
              return (
                <tr key={i}>
                  <td className="aeon-mono p-1 text-left text-slate-400">
                    {rateVal !== undefined ? `${rateVal.toFixed(0)}″` : i}
                  </td>
                  {row.map((snr, j) => {
                    const norm = Math.max(0, Math.min(1, (snr - minVal) / (maxVal - minVal)));
                    const isPeak = snr === maxVal;
                    const paVal = pas?.[j];
                    return (
                      <td key={j} className="p-0.5">
                        <button
                          type="button"
                          onClick={() => {
                            if (rateVal !== undefined && paVal !== undefined) {
                              onSelectVector(rateVal, paVal);
                            }
                          }}
                          style={{
                            backgroundColor: `rgba(245, 158, 11, ${0.1 + norm * 0.65})`,
                          }}
                          className={`aeon-mono w-full rounded px-1.5 py-1.5 font-medium transition hover:ring-1 hover:ring-cyan-400 ${
                            isPeak
                              ? "ring-2 ring-amber-400 font-bold text-white"
                              : "text-slate-100"
                          }`}
                        >
                          {snr.toFixed(1)}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ShiftStackPanel({
  coords,
  selectedObject,
  onAstrometryReady,
}: ShiftStackPanelProps) {
  const { dict } = useI18n();

  const [rate, setRate] = useState<number>(110);
  const [pa, setPa] = useState<number>(62);
  const [useParallax, setUseParallax] = useState<boolean>(true);
  const [distanceAu, setDistanceAu] = useState<number>(520);
  const [cadence, setCadence] = useState<"uniform" | "spherex">("uniform");
  const [combine, setCombine] = useState<"mean" | "median">("mean");
  const [colormap, setColormap] = useState<ColormapName>("inferno");

  const [stackResult, setStackResult] = useState<ShiftStackResult | null>(null);
  const [blindResult, setBlindResult] = useState<BlindSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);

  const singleCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const stackedCanvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    let active = true;
    const isPx = selectedObject?.id === "px-2026-09";
    const defaultRate = isPx ? 110 : 8.15;
    const defaultPa = isPx ? 62 : 275;
    const defaultDist = isPx ? 520 : null;

    runShiftStack({
      ra: coords.ra,
      dec: coords.dec,
      rate_arcsec_yr: defaultRate,
      pa_deg: defaultPa,
      distance_au: defaultDist,
      cadence: "uniform",
      n_frames: 24,
      combine: "mean",
    })
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setRate(data.rate_arcsec_yr ?? defaultRate);
        setPa(data.pa_deg ?? defaultPa);
        setUseParallax(data.distance_au !== null && data.distance_au !== undefined);
        if (data.distance_au) setDistanceAu(Math.round(data.distance_au));
        setStackResult(data);
        if (data.astrometry && onAstrometryReady) {
          onAstrometryReady(data.astrometry);
        }
        setFromCache(cached);
        setError(null);
      })
      .catch(() => {
        if (!active) return;
        setError(dict.stack.error);
      });

    return () => {
      active = false;
    };
  }, [coords.ra, coords.dec, selectedObject?.id, dict.stack.error, onAstrometryReady]);

  useEffect(() => {
    if (!stackResult) return;
    if (stackResult.single_frame && singleCanvasRef.current) {
      renderSkyArrayToCanvas(
        singleCanvasRef.current,
        stackResult.single_frame.data,
        stackResult.single_frame.width,
        stackResult.single_frame.height,
        colormap
      );
    }
    if (stackResult.stacked && stackedCanvasRef.current) {
      renderSkyArrayToCanvas(
        stackedCanvasRef.current,
        stackResult.stacked.data,
        stackResult.stacked.width,
        stackResult.stacked.height,
        colormap,
        {
          detections: stackResult.peak ? [stackResult.peak] : undefined,
        }
      );
    }
  }, [stackResult, colormap]);

  const executeStack = async (
    nextRate: number,
    nextPa: number,
    nextDist: number | null
  ) => {
    setLoading(true);
    setError(null);
    try {
      const { data, fromCache: cached } = await runShiftStack({
        ra: coords.ra,
        dec: coords.dec,
        rate_arcsec_yr: nextRate,
        pa_deg: nextPa,
        distance_au: nextDist,
        cadence,
        n_frames: 24,
        combine,
      });
      setStackResult(data);
      if (data.astrometry && onAstrometryReady) {
        onAstrometryReady(data.astrometry);
      }
      setFromCache(cached);
    } catch {
      setError(dict.stack.error);
    } finally {
      setLoading(false);
    }
  };

  const executeBlindSearch = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data, fromCache: cached } = await runBlindSearch({
        ra: coords.ra,
        dec: coords.dec,
        n_frames: 24,
        combine,
        cadence,
        rate_range_arcsec_yr: [20, 200],
        pa_range_deg: [30, 90],
        distance_range_au: useParallax ? [250, 1000] : null,
        grid: 5,
      });
      setBlindResult(data);
      setStackResult(data.best);
      if (data.best.rate_arcsec_yr !== undefined) setRate(Math.round(data.best.rate_arcsec_yr));
      if (data.best.pa_deg !== undefined) setPa(Math.round(data.best.pa_deg));
      if (data.best.distance_au !== undefined && data.best.distance_au !== null) {
        setUseParallax(true);
        setDistanceAu(Math.round(data.best.distance_au));
      }
      if (data.best.astrometry && onAstrometryReady) {
        onAstrometryReady(data.best.astrometry);
      }
      setFromCache(cached);
    } catch {
      setError(dict.stack.error);
    } finally {
      setLoading(false);
    }
  };

  const snrSingle = stackResult?.snr_single_frame ?? 0;
  const snrStacked = stackResult?.snr_stacked ?? 0;
  const snrGain = stackResult?.snr_gain ?? (snrSingle > 0 ? snrStacked / snrSingle : 0);

  // Compute isotropic SVG polyline points for the apparent geocentric parallax track (preserving ΔRA·cos(Dec) scale)
  const trackPoints = (() => {
    const pts = stackResult?.track;
    if (!pts || pts.length < 2) return null;
    const meanRa = pts.reduce((s, p) => s + p.ra, 0) / pts.length;
    const meanDec = pts.reduce((s, p) => s + p.dec, 0) / pts.length;
    const cosDec = Math.max(Math.cos((meanDec * Math.PI) / 180), 1e-4);

    // Sky convention: East is left (-ΔRA·cos(Dec)), North is up (+ΔDec)
    const proj = pts.map((p) => ({
      dx: -(p.ra - meanRa) * cosDec * 3600,
      dy: (p.dec - meanDec) * 3600,
    }));
    const xs = proj.map((p) => p.dx);
    const ys = proj.map((p) => p.dy);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const midX = 0.5 * (minX + maxX);
    const midY = 0.5 * (minY + maxY);
    const uniformSpan = Math.max(maxX - minX, (maxY - minY) * (160 / 56), 1e-3);
    const scalePxPerArcsec = 156 / uniformSpan;

    return proj
      .map((p) => {
        const x = 100 + (p.dx - midX) * scalePxPerArcsec;
        const y = 42 - (p.dy - midY) * scalePxPerArcsec;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  })();

  return (
    <section className="aeon-panel rounded-2xl p-4 @xl:p-5">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <Radar className="h-4 w-4 text-violet-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
            {dict.stack.title}
          </h2>
          {selectedObject?.is_synthetic && (
            <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/40 bg-rose-500/15 px-2.5 py-0.5 text-[10px] font-semibold text-rose-300">
              <AlertTriangle className="h-3 w-3" />
              {dict.badges.synthetic}
            </span>
          )}
          {fromCache && (
            <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300">
              {dict.header.dataMode.offline_cache}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/30 px-2.5 py-1">
            <SlidersHorizontal className="h-3.5 w-3.5 text-slate-400" />
            <select
              value={colormap}
              onChange={(e) => setColormap(e.target.value as ColormapName)}
              className="bg-transparent font-medium text-cyan-200 focus:outline-none"
            >
              {COLORMAP_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value} className="bg-[#0E0E10]">
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            onClick={() => executeStack(rate, pa, useParallax ? distanceAu : null)}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-400/35 bg-cyan-500/15 px-3 py-1.5 font-medium text-cyan-200 transition hover:bg-cyan-500/25 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Compass className="h-3.5 w-3.5" />}
            <span>{dict.stack.runStack}</span>
          </button>

          <button
            type="button"
            onClick={executeBlindSearch}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/40 bg-amber-500/20 px-3 py-1.5 font-medium text-amber-200 transition hover:bg-amber-500/30 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Grid className="h-3.5 w-3.5" />}
            <span>{dict.stack.runBlind}</span>
          </button>
        </div>
      </div>

      {/* Sliders: Rate, PA, Trial Distance (Parallax), Cadence & Combine */}
      <div className="mb-4 grid grid-cols-1 gap-3 rounded-xl border border-white/10 bg-black/30 p-3.5 @2xl:grid-cols-2 @4xl:grid-cols-4">
        <div>
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-slate-400">{dict.stack.rate}</span>
            <span className="aeon-mono font-semibold text-amber-300">{rate}″/yr</span>
          </div>
          <input
            type="range"
            min={0}
            max={300}
            step={1}
            value={rate}
            onChange={(e) => setRate(Number(e.target.value))}
            className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-white/15 accent-amber-400"
          />
        </div>

        <div>
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-slate-400">{dict.stack.pa}</span>
            <span className="aeon-mono font-semibold text-cyan-300">{pa}°</span>
          </div>
          <input
            type="range"
            min={0}
            max={360}
            step={1}
            value={pa}
            onChange={(e) => setPa(Number(e.target.value))}
            className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-white/15 accent-cyan-400"
          />
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between text-xs">
            <label className="inline-flex cursor-pointer items-center gap-1.5 text-slate-400">
              <input
                type="checkbox"
                checked={useParallax}
                onChange={(e) => setUseParallax(e.target.checked)}
                className="accent-violet-400"
              />
              <span>{dict.stack.distance}</span>
            </label>
            <span className="aeon-mono font-semibold text-violet-300">
              {useParallax ? `${distanceAu} AU` : dict.stack.noParallax}
            </span>
          </div>
          <input
            type="range"
            min={200}
            max={1200}
            step={10}
            disabled={!useParallax}
            value={distanceAu}
            onChange={(e) => setDistanceAu(Number(e.target.value))}
            className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-white/15 accent-violet-400 disabled:opacity-40"
          />
        </div>

        <div className="flex flex-col justify-between gap-2 text-xs">
          <div className="flex items-center justify-between gap-1">
            <span className="text-slate-400">{dict.stack.cadence}:</span>
            <div className="inline-flex rounded-lg border border-white/10 bg-white/5 p-0.5">
              <button
                type="button"
                onClick={() => setCadence("uniform")}
                className={`rounded-md px-2 py-0.5 text-[11px] transition ${
                  cadence === "uniform" ? "bg-cyan-500/25 text-cyan-200" : "text-slate-400"
                }`}
              >
                {dict.stack.cadenceUniform}
              </button>
              <button
                type="button"
                onClick={() => setCadence("spherex")}
                className={`rounded-md px-2 py-0.5 text-[11px] transition ${
                  cadence === "spherex" ? "bg-cyan-500/25 text-cyan-200" : "text-slate-400"
                }`}
              >
                {dict.stack.cadenceSpherex}
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between gap-1">
            <span className="text-slate-400">{dict.stack.combine}:</span>
            <div className="inline-flex rounded-lg border border-white/10 bg-white/5 p-0.5">
              <button
                type="button"
                onClick={() => setCombine("mean")}
                className={`rounded-md px-2 py-0.5 text-[11px] transition ${
                  combine === "mean" ? "bg-violet-500/25 text-violet-200" : "text-slate-400"
                }`}
              >
                {dict.stack.mean}
              </button>
              <button
                type="button"
                onClick={() => setCombine("median")}
                className={`rounded-md px-2 py-0.5 text-[11px] transition ${
                  combine === "median" ? "bg-violet-500/25 text-violet-200" : "text-slate-400"
                }`}
              >
                {dict.stack.median}
              </button>
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      {/* Side-by-side Single vs Stacked + S/N Gain */}
      <div className="grid grid-cols-1 gap-4 @4xl:grid-cols-12">
        <div className="overflow-hidden rounded-xl border border-white/10 bg-black/50 p-3 @4xl:col-span-4">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-medium text-slate-300">{dict.stack.singleFrame}</span>
            <span className="aeon-mono rounded bg-white/10 px-2 py-0.5 text-[11px] text-slate-300">
              {dict.stack.snrSingle}: {snrSingle.toFixed(2)}
            </span>
          </div>
          <div className="relative aspect-square w-full overflow-hidden rounded-lg border border-white/5 bg-black">
            <canvas
              ref={singleCanvasRef}
              className="h-full w-full object-contain [image-rendering:pixelated]"
            />
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-amber-400/35 bg-black/50 p-3 @4xl:col-span-4">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-semibold text-amber-200">{dict.stack.stackedFrame}</span>
            <span
              className={`aeon-mono rounded px-2 py-0.5 text-[11px] font-semibold ${
                snrStacked >= 5
                  ? "bg-emerald-500/20 text-emerald-300"
                  : "bg-amber-500/20 text-amber-200"
              }`}
            >
              {dict.stack.snrStacked}: {snrStacked.toFixed(2)}
            </span>
          </div>
          <div className="relative aspect-square w-full overflow-hidden rounded-lg border border-white/5 bg-black">
            <canvas
              ref={stackedCanvasRef}
              className="h-full w-full object-contain [image-rendering:pixelated]"
            />
          </div>
        </div>

        {/* S/N Gain + Parallax Loop Preview */}
        <div className="flex flex-col justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-4 @4xl:col-span-4">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">{dict.stack.snrGain}</span>
              <span className="aeon-mono text-lg font-bold text-emerald-300">
                {snrSingle > 0 && snrGain > 0 ? `×${snrGain.toFixed(2)}` : "—"}
              </span>
            </div>

            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between text-slate-400">
                <span>{dict.stack.snrSingle}</span>
                <span className="aeon-mono text-slate-200">{snrSingle.toFixed(2)}</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-slate-400"
                  style={{ width: `${Math.min(100, (snrSingle / 10) * 100)}%` }}
                />
              </div>

              <div className="mt-2 flex justify-between text-slate-400">
                <span>{dict.stack.snrStacked}</span>
                <span className="aeon-mono font-semibold text-emerald-300">
                  {snrStacked.toFixed(2)}
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-emerald-400"
                  style={{ width: `${Math.min(100, (snrStacked / 10) * 100)}%` }}
                />
              </div>
            </div>

            {trackPoints && (
              <div className="rounded-xl border border-white/10 bg-black/40 p-2.5">
                <div className="mb-1 text-[11px] font-medium text-slate-400">
                  {dict.stack.parallaxTrack}
                </div>
                <svg viewBox="0 0 200 84" className="h-20 w-full">
                  <polyline
                    fill="none"
                    stroke="#9db4f0"
                    strokeWidth="2"
                    points={trackPoints}
                  />
                </svg>
              </div>
            )}

            {blindResult && (
              <div className="rounded-xl border border-amber-400/30 bg-amber-500/10 p-3 text-xs text-amber-200">
                <div className="flex items-center gap-1.5 font-semibold">
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>{dict.stack.bestVelocity}</span>
                </div>
                <p className="aeon-mono mt-1 text-sm">
                  {blindResult.best.rate_arcsec_yr?.toFixed(1)}″/yr · PA{" "}
                  {blindResult.best.pa_deg?.toFixed(1)}°
                  {blindResult.best.distance_au
                    ? ` · ${blindResult.best.distance_au.toFixed(0)} AU`
                    : ""}{" "}
                  (S/N {blindResult.best.snr_stacked.toFixed(2)})
                </p>
              </div>
            )}
          </div>

          <p className="text-[11px] text-slate-400">{dict.stack.clickCellHint}</p>
        </div>
      </div>

      {/* 5x5 Blind Search Heatmaps + Distance Profile */}
      {blindResult && (
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-1 gap-4 @2xl:grid-cols-2">
            <SnrGrid
              title={dict.stack.coarseGrid}
              grid={blindResult.grid}
              rates={blindResult.rates_arcsec_yr}
              pas={blindResult.pas_deg}
              onSelectVector={(r, p) => {
                setRate(Math.round(r));
                setPa(Math.round(p));
                executeStack(r, p, useParallax ? distanceAu : null);
              }}
            />
            {blindResult.refined?.grid && (
              <SnrGrid
                title={dict.stack.refinedGrid}
                grid={blindResult.refined.grid}
                rates={blindResult.refined.rates_arcsec_yr}
                pas={blindResult.refined.pas_deg}
                onSelectVector={(r, p) => {
                  setRate(Math.round(r));
                  setPa(Math.round(p));
                  executeStack(r, p, useParallax ? distanceAu : null);
                }}
              />
            )}
          </div>

          {blindResult.distances_au &&
            blindResult.distance_profile &&
            blindResult.distances_au.length > 0 && (
              <div className="rounded-xl border border-white/10 bg-black/40 p-3">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
                  {dict.stack.distanceProfile}
                </h3>
                <div className="flex flex-wrap items-end gap-2 pt-2">
                  {blindResult.distances_au.map((d, idx) => {
                    const snr = blindResult.distance_profile?.[idx] ?? 0;
                    const maxProf = Math.max(...(blindResult.distance_profile ?? [1]), 1);
                    const pct = Math.max(12, Math.round((snr / maxProf) * 100));
                    const isBest = snr === maxProf;
                    return (
                      <button
                        key={d}
                        type="button"
                        onClick={() => {
                          setUseParallax(true);
                          setDistanceAu(Math.round(d));
                          executeStack(rate, pa, d);
                        }}
                        className="group flex flex-1 min-w-[54px] flex-col items-center gap-1"
                      >
                        <span className="aeon-mono text-[10px] text-slate-300">
                          {snr.toFixed(1)}
                        </span>
                        <div className="flex h-20 w-full items-end rounded bg-white/5 p-1">
                          <div
                            style={{ height: `${pct}%` }}
                            className={`w-full rounded transition ${
                              isBest
                                ? "bg-amber-400"
                                : "bg-violet-400/60 group-hover:bg-cyan-400"
                            }`}
                          />
                        </div>
                        <span className="aeon-mono text-[10px] text-slate-400">
                          {d.toFixed(0)} AU
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
        </div>
      )}
    </section>
  );
}
