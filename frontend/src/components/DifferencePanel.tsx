"use client";

import React, { useEffect, useRef, useState } from "react";
import { AlertTriangle, Layers, Loader2, RefreshCw, SlidersHorizontal } from "lucide-react";
import { useI18n } from "@/i18n/context";
import {
  EPOCHS,
  runDifference,
  type CatalogObject,
  type DifferenceResult,
  type Epoch,
} from "@/lib/api";
import { renderSkyArrayToCanvas, type ColormapName } from "@/lib/colormaps";

interface DifferencePanelProps {
  coords: { ra: number; dec: number };
  selectedObject: CatalogObject | null;
}

export function DifferencePanel({ coords, selectedObject }: DifferencePanelProps) {
  const { dict } = useI18n();

  const [epoch1, setEpoch1] = useState<Epoch>("2026-Q1");
  const [epoch2, setEpoch2] = useState<Epoch>("2026-Q3");
  const [colormap, setColormap] = useState<ColormapName>("inferno");
  const [result, setResult] = useState<DifferenceResult | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [refreshCount, setRefreshCount] = useState(0);

  const canvas1Ref = useRef<HTMLCanvasElement | null>(null);
  const canvas2Ref = useRef<HTMLCanvasElement | null>(null);
  const canvasDiffRef = useRef<HTMLCanvasElement | null>(null);

  const reqKey = `${coords.ra}:${coords.dec}:${epoch1}:${epoch2}:${refreshCount}`;
  const loading = loadedKey !== reqKey;

  useEffect(() => {
    let active = true;
    runDifference({
      ra: coords.ra,
      dec: coords.dec,
      epoch_1: epoch1,
      epoch_2: epoch2,
      size_px: 64,
      pixel_scale_arcsec: 6.2,
    })
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setResult(data);
        setFromCache(cached);
        setError(null);
        setLoadedKey(reqKey);
      })
      .catch(() => {
        if (!active) return;
        setError(dict.diff.error);
        setLoadedKey(reqKey);
      });

    return () => {
      active = false;
    };
  }, [coords.ra, coords.dec, epoch1, epoch2, refreshCount, reqKey, dict.diff.error]);

  useEffect(() => {
    if (!result) return;
    if (result.image_1 && canvas1Ref.current) {
      renderSkyArrayToCanvas(
        canvas1Ref.current,
        result.image_1.data,
        result.image_1.width,
        result.image_1.height,
        colormap
      );
    }
    if (result.image_2 && canvas2Ref.current) {
      renderSkyArrayToCanvas(
        canvas2Ref.current,
        result.image_2.data,
        result.image_2.width,
        result.image_2.height,
        colormap
      );
    }
    if (result.difference && canvasDiffRef.current) {
      renderSkyArrayToCanvas(
        canvasDiffRef.current,
        result.difference.data,
        result.difference.width,
        result.difference.height,
        colormap,
        {
          symmetric: true,
          detections: result.detections,
        }
      );
    }
  }, [result, colormap]);

  return (
    <section className="aeon-panel rounded-2xl p-4 sm:p-5">
      {/* Header Controls */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <Layers className="h-4 w-4 text-amber-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
            {dict.diff.title}
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
          {/* Epoch 1 */}
          <label className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/30 px-2.5 py-1">
            <span className="text-slate-400">{dict.diff.epoch1}:</span>
            <select
              value={epoch1}
              onChange={(e) => setEpoch1(e.target.value as Epoch)}
              className="aeon-mono bg-transparent font-medium text-amber-200 focus:outline-none"
            >
              {EPOCHS.map((ep) => (
                <option key={ep} value={ep} className="bg-[#090D16]">
                  {ep}
                </option>
              ))}
            </select>
          </label>

          {/* Epoch 2 */}
          <label className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/30 px-2.5 py-1">
            <span className="text-slate-400">{dict.diff.epoch2}:</span>
            <select
              value={epoch2}
              onChange={(e) => setEpoch2(e.target.value as Epoch)}
              className="aeon-mono bg-transparent font-medium text-cyan-200 focus:outline-none"
            >
              {EPOCHS.map((ep) => (
                <option key={ep} value={ep} className="bg-[#090D16]">
                  {ep}
                </option>
              ))}
            </select>
          </label>

          {/* Colormap */}
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
            onClick={() => setRefreshCount((c) => c + 1)}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/35 bg-amber-500/15 px-3 py-1 font-medium text-amber-200 transition hover:bg-amber-500/25 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            <span>{dict.diff.run}</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      {/* Three Canvases: I(t1), I(t2), Difference */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="overflow-hidden rounded-xl border border-white/10 bg-black/50 p-3">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-medium text-slate-300">{dict.diff.image1}</span>
            <span className="aeon-mono text-amber-300">{epoch1}</span>
          </div>
          <div className="relative aspect-square w-full overflow-hidden rounded-lg border border-white/5 bg-black">
            <canvas
              ref={canvas1Ref}
              className="h-full w-full object-contain [image-rendering:pixelated]"
            />
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-white/10 bg-black/50 p-3">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-medium text-slate-300">{dict.diff.image2}</span>
            <span className="aeon-mono text-cyan-300">{epoch2}</span>
          </div>
          <div className="relative aspect-square w-full overflow-hidden rounded-lg border border-white/5 bg-black">
            <canvas
              ref={canvas2Ref}
              className="h-full w-full object-contain [image-rendering:pixelated]"
            />
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-amber-400/30 bg-black/50 p-3">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-semibold text-amber-200">{dict.diff.difference}</span>
            <div className="flex items-center gap-2 text-[11px]">
              <span className="text-emerald-400">{dict.diff.positive}</span>
              <span className="text-rose-400">{dict.diff.negative}</span>
            </div>
          </div>
          <div className="relative aspect-square w-full overflow-hidden rounded-lg border border-white/5 bg-black">
            <canvas
              ref={canvasDiffRef}
              className="h-full w-full object-contain [image-rendering:pixelated]"
            />
          </div>
        </div>
      </div>

      {/* Detections + Stats Footer */}
      {result && (
        <div className="mt-4 flex flex-col justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-3 sm:flex-row sm:items-center">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-medium text-slate-300">{dict.diff.detections}:</span>
            {result.detections.length === 0 ? (
              <span className="text-slate-400">{dict.diff.noDetections}</span>
            ) : (
              result.detections.slice(0, 6).map((det, idx) => (
                <span
                  key={idx}
                  className={`aeon-mono inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] ${
                    det.sign === "negative"
                      ? "border-rose-500/35 bg-rose-500/15 text-rose-200"
                      : "border-emerald-500/35 bg-emerald-500/15 text-emerald-200"
                  }`}
                >
                  <span>{det.sign === "negative" ? "−" : "+"}</span>
                  <span>S/N {det.snr?.toFixed(1) ?? "—"}</span>
                  {det.x !== undefined && det.y !== undefined && (
                    <span className="text-slate-400">
                      ({det.x.toFixed(1)}, {det.y.toFixed(1)})
                    </span>
                  )}
                </span>
              ))
            )}
          </div>

          <div className="aeon-mono flex items-center gap-3 text-xs text-slate-400">
            {result.dt_years !== undefined && (
              <span>
                {dict.diff.baseline}: {result.dt_years.toFixed(2)} {dict.diff.years}
              </span>
            )}
            {result.noise_sigma !== undefined && (
              <span>
                {dict.diff.noiseSigma}: {result.noise_sigma.toFixed(2)} µJy
              </span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
