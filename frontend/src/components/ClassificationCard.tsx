"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle, Cpu, RotateCw, Sparkles } from "lucide-react";
import { useI18n } from "@/i18n/context";
import {
  ApiError,
  classifyTarget,
  isServiceDown,
  type AiClassifyResponse,
  type CatalogObject,
  type ObjectClass,
} from "@/lib/api";

interface ClassificationCardProps {
  coords: { ra: number; dec: number };
  selectedObject: CatalogObject | null;
}

// One finished request. `key` ties it to the position (and retry) it answers, so a slow answer for
// an earlier target can never be shown for the current one, and "loading" needs no extra state.
type Outcome =
  | { key: string; kind: "ready"; result: AiClassifyResponse; fromCache: boolean }
  | { key: string; kind: "unreachable" }
  | { key: string; kind: "rejected"; detail: string };

const LOW_SNR = 3;

/** The engine's numbers are shown as they are, but never trusted to be numbers: clamp to [0, 1]. */
function unit(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
}

const ALL_CLASSES: ObjectClass[] = [
  "cold_brown_dwarf",
  "planet_x_candidate",
  "young_variable_star",
  "main_sequence_star",
  "high_z_galaxy",
];

export function ClassificationCard({
  coords,
  selectedObject,
}: ClassificationCardProps) {
  const { dict } = useI18n();

  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [attempt, setAttempt] = useState(0);
  const key = `${coords.ra},${coords.dec},${attempt}`;

  useEffect(() => {
    let active = true;
    classifyTarget({ ra: coords.ra, dec: coords.dec })
      .then(({ data, fromCache }) => {
        if (active) setOutcome({ key, kind: "ready", result: data, fromCache });
      })
      .catch((err: unknown) => {
        if (!active) return;
        if (isServiceDown(err)) setOutcome({ key, kind: "unreachable" });
        else setOutcome({ key, kind: "rejected", detail: err instanceof ApiError ? err.message : "" });
      });
    return () => {
      active = false;
    };
  }, [coords.ra, coords.dec, key]);

  const current = outcome?.key === key ? outcome : null;
  const loading = current === null;
  const answered = current?.kind === "ready" ? current.result : null;
  const fromCache = current?.kind === "ready" && current.fromCache;
  // No spectrum, no image: the engine only returns a uniform prior. That is not a classification.
  // (Engines older than `spectrum_source` signal the same case with physics_diagnostics: null.)
  const noSpectrum =
    answered?.spectrum_source === "none" ||
    (answered != null &&
      answered.spectrum_source === undefined &&
      (answered as { physics_diagnostics?: unknown }).physics_diagnostics === null);
  // The backend holding the spectra was down or too slow: worth another try, unlike an empty position.
  const spectrumDown = answered?.spectrum_source === "unavailable";
  const result = answered && !noSpectrum && !spectrumDown ? answered : null;
  const rawSnr = result?.spectrum_snr_median;
  const snr = typeof rawSnr === "number" && Number.isFinite(rawSnr) ? rawSnr : null;
  const source =
    result?.spectrum_source === "request"
      ? dict.ai.sourceRequest
      : result?.spectrum_source === "archive"
        ? dict.ai.sourceArchive
        : null;

  const aiState =
    current === null ? "loading" : noSpectrum ? "no-spectrum" : spectrumDown ? "spectrum-unavailable" : current.kind;

  const anomaly = unit(result?.anomaly_score);
  const topClass = result?.top_class && ALL_CLASSES.includes(result.top_class) ? result.top_class : undefined;

  const retryButton = (
    <button
      type="button"
      onClick={() => setAttempt((n) => n + 1)}
      className="aeon-btn aeon-btn-line h-7 shrink-0 px-2.5 text-[11px]"
    >
      <RotateCw className="h-3 w-3" />
      {dict.ai.retry}
    </button>
  );

  return (
    <section className="aeon-panel rounded-2xl p-4 @xl:p-5" aria-busy={loading} data-ai-state={aiState}>
      {current?.kind === "unreachable" && (
        <div role="alert" className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <span>{dict.ai.serviceUnavailable}</span>
          {retryButton}
        </div>
      )}
      {current?.kind === "rejected" && (
        <div role="alert" className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          <span className="min-w-0 break-words">
            {dict.ai.requestRejected}
            {current.detail ? `: ${current.detail}` : ""}
          </span>
          {retryButton}
        </div>
      )}
      {spectrumDown && (
        <div role="alert" className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <span>{dict.ai.spectrumUnavailable}</span>
          {retryButton}
        </div>
      )}
      {noSpectrum && (
        <p role="status" className="mb-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300">
          {dict.ai.noSpectrum}
        </p>
      )}
      {loading && (
        <p role="status" className="mb-3 text-xs text-slate-400">
          {dict.ai.classifying}
        </p>
      )}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2.5">
          <Cpu className="h-4 w-4 text-violet-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
            {dict.ai.classifyTitle}
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

        {topClass && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-violet-400/40 bg-violet-500/20 px-3 py-0.5 text-xs font-semibold text-violet-200">
            <Sparkles className="h-3.5 w-3.5" />
            <span>
              {dict.ai.topClass}: {dict.classes[topClass]}
            </span>
          </span>
        )}
      </div>

      {result && (
      <>
      {source && (
        <p className="aeon-mono mb-3 text-[11px] text-slate-400">
          {source}
          {snr !== null && ` · ${dict.ai.snrMedian} ${snr.toFixed(1)}`}
        </p>
      )}
      {snr !== null && snr < LOW_SNR && (
        <p className="mb-3 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {dict.ai.lowSnr}
        </p>
      )}
      <div className="grid grid-cols-1 gap-4 @2xl:grid-cols-12">
        {/* 5 Class Probability Bars */}
        <div className="space-y-2.5 @2xl:col-span-8">
          {ALL_CLASSES.map((cls) => {
            const p = unit(result?.probabilities?.[cls]);
            const pct = Math.round(p * 100);
            const isTop = cls === topClass;
            return (
              <div key={cls} className="space-y-1 text-xs">
                <div className="flex justify-between">
                  <span
                    className={
                      isTop ? "font-semibold text-amber-200" : "text-slate-300"
                    }
                  >
                    {dict.classes[cls]}
                  </span>
                  <span className="aeon-mono text-slate-300">{pct}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                  <div
                    className={`h-full rounded-full transition-all ${
                      isTop ? "bg-amber-400" : "bg-cyan-400/60"
                    }`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* PatchAnomalyViT Gauge */}
        <div className="flex flex-col justify-between rounded-xl border border-white/10 bg-black/40 p-4 @2xl:col-span-4">
          <div>
            <span className="text-xs font-medium text-slate-400">
              {dict.ai.anomalyScore}
            </span>
            <div className="mt-2 flex items-baseline gap-2">
              <span
                className={`aeon-mono text-3xl font-bold ${
                  anomaly >= 0.85 ? "text-rose-400" : "text-cyan-300"
                }`}
              >
                {anomaly.toFixed(2)}
              </span>
              <span className="text-xs text-slate-400">/ 1.00</span>
            </div>
            <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className={`h-full rounded-full ${
                  anomaly >= 0.85 ? "bg-rose-500" : "bg-cyan-400"
                }`}
                style={{ width: `${Math.min(100, Math.round(anomaly * 100))}%` }}
              />
            </div>
            <p className="mt-2 text-xs text-slate-300">
              {anomaly >= 0.85 ? dict.ai.highAnomaly : dict.ai.normalAnomaly}
            </p>
          </div>

          {result?.model_versions && (
            <div className="aeon-mono mt-3 border-t border-white/10 pt-2 text-[10px] text-slate-500">
              {Object.entries(result.model_versions)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · ")}
            </div>
          )}
        </div>
      </div>
      </>
      )}
    </section>
  );
}
