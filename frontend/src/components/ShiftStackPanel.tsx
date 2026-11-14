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
  type BlindSearchResult,
  type CatalogObject,
  type ShiftStackResult,
} from "@/lib/api";
import { renderSkyArrayToCanvas, type ColormapName } from "@/lib/colormaps";

interface ShiftStackPanelProps {
  coords: { ra: number; dec: number };
  selectedObject: CatalogObject | null;
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
                              ? "ring-2 ring-amber-400 text-white font-bold"
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

export function ShiftStackPanel({ coords, selectedObject }: ShiftStackPanelProps) {
  const { dict } = useI18n();

  const [rate, setRate] = useState<number>(110);
  const [pa, setPa] = useState<number>(62);
  const [combine, setCombine] = useState<"mean" | "median">("mean");
  const [colormap, setColormap] = useState<ColormapName>("inferno");

  const [stackResult, setStackResult] = useState<ShiftStackResult | null>(null);
  const [blindResult, setBlindResult] = useState<BlindSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);

  const singleCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const stackedCanvasRef = useRef<HTMLCanvasElement | null>(null);

  // Run initial shift-stack whenever target coordinates change
  useEffect(() => {
    let active = true;
    const defaultRate = selectedObject?.id === "px-2026-09" ? 110 : 8.15;
    const defaultPa = selectedObject?.id === "px-2026-09" ? 62 : 275;

    runShiftStack({
      ra: coords.ra,
      dec: coords.dec,
      rate_arcsec_yr: defaultRate,
      pa_deg: defaultPa,
      n_frames: 24,
      combine: "mean",
    })
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setRate(data.rate_arcsec_yr ?? defaultRate);
        setPa(data.pa_deg ?? defaultPa);
        setStackResult(data);
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
  }, [coords.ra, coords.dec, selectedObject?.id, dict.stack.error]);

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

  const executeStack = async (nextRate: number, nextPa: number) => {
    setLoading(true);
    setError(null);
    try {
      const { data, fromCache: cached } = await runShiftStack({
        ra: coords.ra,
        dec: coords.dec,
        rate_arcsec_yr: nextRate,
        pa_deg: nextPa,
        n_frames: 24,
        combine,
      });
      setStackResult(data);
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
        rate_range_arcsec_yr: [20, 200],
        pa_range_deg: [30, 90],
        grid: 5,
      });
      setBlindResult(data);
      setStackResult(data.best);
      if (data.best.rate_arcsec_yr !== undefined) setRate(Math.round(data.best.rate_arcsec_yr));
      if (data.best.pa_deg !== undefined) setPa(Math.round(data.best.pa_deg));
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

  return (
    <section className="aeon-panel rounded-2xl p-4 sm:p-5">
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
              <option value="inferno" className="bg-[#090D16]">Inferno</option>
              <option value="viridis" className="bg-[#090D16]">Viridis</option>
              <option value="magma" className="bg-[#090D16]">Magma</option>
              <option value="grayscale" className="bg-[#090D16]">Grayscale</option>
            </select>
          </label>

          <button
            type="button"
            onClick={() => executeStack(rate, pa)}
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

      {/* Sliders: Rate & PA & Combine */}
      <div className="mb-4 grid grid-cols-1 gap-3 rounded-xl border border-white/10 bg-black/30 p-3.5 md:grid-cols-3">
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

        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-slate-400">{dict.stack.combine}:</span>
          <div className="inline-flex rounded-lg border border-white/10 bg-white/5 p-0.5">
            <button
              type="button"
              onClick={() => setCombine("mean")}
              className={`rounded-md px-2.5 py-1 transition ${
                combine === "mean" ? "bg-violet-500/25 text-violet-200" : "text-slate-400"
              }`}
            >
              {dict.stack.mean}
            </button>
            <button
              type="button"
              onClick={() => setCombine("median")}
              className={`rounded-md px-2.5 py-1 transition ${
                combine === "median" ? "bg-violet-500/25 text-violet-200" : "text-slate-400"
              }`}
            >
              {dict.stack.median}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      {/* Side-by-side Single vs Stacked + S/N Gain */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="overflow-hidden rounded-xl border border-white/10 bg-black/50 p-3 lg:col-span-4">
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

        <div className="overflow-hidden rounded-xl border border-amber-400/35 bg-black/50 p-3 lg:col-span-4">
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

        {/* S/N Gain + Heatmaps */}
        <div className="flex flex-col justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-4 lg:col-span-4">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">{dict.stack.snrGain}</span>
              <span className="aeon-mono text-lg font-bold text-emerald-300">
                ×{snrGain.toFixed(2)}
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

            {blindResult && (
              <div className="rounded-xl border border-amber-400/30 bg-amber-500/10 p-3 text-xs text-amber-200">
                <div className="flex items-center gap-1.5 font-semibold">
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>{dict.stack.bestVelocity}</span>
                </div>
                <p className="aeon-mono mt-1 text-sm">
                  {blindResult.best.rate_arcsec_yr?.toFixed(1)}″/yr · PA{" "}
                  {blindResult.best.pa_deg?.toFixed(1)}° (S/N{" "}
                  {blindResult.best.snr_stacked.toFixed(2)})
                </p>
              </div>
            )}
          </div>

          <p className="text-[11px] text-slate-400">{dict.stack.clickCellHint}</p>
        </div>
      </div>

      {/* 5x5 Blind Search Heatmaps */}
      {blindResult && (
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          <SnrGrid
            title={dict.stack.coarseGrid}
            grid={blindResult.grid}
            rates={blindResult.rates_arcsec_yr}
            pas={blindResult.pas_deg}
            onSelectVector={(r, p) => {
              setRate(Math.round(r));
              setPa(Math.round(p));
              executeStack(r, p);
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
                executeStack(r, p);
              }}
            />
          )}
        </div>
      )}
    </section>
  );
}
