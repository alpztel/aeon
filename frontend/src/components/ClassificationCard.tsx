"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle, Cpu, RotateCw, Sparkles } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { AgeMassCard } from "@/components/AgeMassCard";
import { DataFacts, DataModeBadge, fill, num, signed } from "@/components/DataFacts";
import { ValidationScorecard } from "@/components/ValidationScorecard";
import {
  ApiError,
  classifyTarget,
  isServiceDown,
  stage24,
  type AiClassifyResponse,
  type CatalogObject,
  type ObjectClass,
} from "@/lib/api";
import { useCrossmatch } from "@/lib/useCrossmatch";

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

  const xm = useCrossmatch(coords.ra, coords.dec);
  const stage = stage24(xm.data);
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

  const physics = result?.physics_diagnostics ?? null;

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
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <DataModeBadge
            mode={result.spectrum_data_mode}
            realLabel={dict.data.realSpherex}
            modelLabel={dict.data.physicalModel}
            detail={[
              result.spectrum_epoch,
              result.spectrum_observed_quarter && result.spectrum_observed_quarter !== result.spectrum_epoch
                ? `${dict.data.observedQuarter} ${result.spectrum_observed_quarter}`
                : null,
              typeof result.spectrum_bands_measured === "number" ? `${result.spectrum_bands_measured}/102` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          />
          <p className="aeon-mono text-[11px] text-slate-400">
            {result.spectrum_data_mode ? "" : source}
            {snr !== null && `${result.spectrum_data_mode ? "" : " · "}${dict.ai.snrMedian} ${snr.toFixed(1)}`}
          </p>
        </div>
      )}
      {typeof result.spectrum_bands_blended === "number" && result.spectrum_bands_blended > 0 && (
        <p className="mb-3 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {fill(dict.data.classifiedBlended, {
            b: result.spectrum_bands_blended,
            u: typeof result.spectrum_bands_used === "number" ? result.spectrum_bands_used : "—",
          })}
        </p>
      )}
      {result.physics_agrees === false && physics?.best_template_class && ALL_CLASSES.includes(physics.best_template_class) && (
        <p className="mb-3 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {fill(dict.data.physicsDisagrees, { t: dict.classes[physics.best_template_class] })}
        </p>
      )}
      {result.spectrum_data_mode === "physical_model" && (
        <p className="mb-3 rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-xs text-slate-300">
          {dict.data.classifiedModel}
        </p>
      )}
      {snr !== null && snr < LOW_SNR && (
        <p className="mb-3 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {dict.ai.lowSnr}
        </p>
      )}
      <div className="grid grid-cols-1 gap-4 @2xl:grid-cols-12">
        {/* 5 Class Probability Bars */}
        <div className="space-y-2.5 @2xl:col-span-12">
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

      </div>
      {result?.model_versions && (
        <p className="aeon-mono mt-3 text-[10px] text-slate-500">
          {Object.entries(result.model_versions)
            .map(([k, v]) => `${k}: ${v}`)
            .join(" · ")}
        </p>
      )}

      {physics && (
        <DataFacts
          className="mt-4"
          title={dict.data.physicsTitle}
          facts={[
            {
              label: dict.data.teff,
              value: num(physics.teff_k, 0) !== null ? `${num(physics.teff_k, 0)} K` : dict.data.notMeasurable,
              title: physics.temperature_note,
              tone: physics.teff_method === "template_grid" ? "default" : "warn",
            },
            num(physics.log_g_cgs) !== null && { label: dict.data.logg, value: num(physics.log_g_cgs) },
            signed(physics.w1_minus_w2_ab) !== null && { label: dict.data.w1w2, value: `${signed(physics.w1_minus_w2_ab)} mag` },
            num(physics.w2_ab_mag) !== null && { label: dict.data.w2, value: `${num(physics.w2_ab_mag)} mag` },
            signed(physics.ch4_3_3um_index, 3) !== null && { label: dict.data.ch4, value: signed(physics.ch4_3_3um_index, 3) },
            signed(physics.h2o_2_7um_index, 3) !== null && { label: dict.data.h2o, value: signed(physics.h2o_2_7um_index, 3) },
            signed(physics.co_4_67um_index, 3) !== null && { label: dict.data.co, value: signed(physics.co_4_67um_index, 3) },
            physics.best_template_class &&
              ALL_CLASSES.includes(physics.best_template_class) && {
                label: dict.data.bestTemplate,
                value: dict.classes[physics.best_template_class],
              },
            num(physics.spectral_recon_rms, 3) !== null && { label: dict.data.reconRms, value: num(physics.spectral_recon_rms, 3) },
          ]}
        />
      )}
      {physics?.teff_method === "not_measurable_reflected_light" && physics.temperature_note && (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-400">{physics.temperature_note}</p>
      )}

      <div className="mt-4 space-y-4">
        <AgeMassCard ageMass={stage.ageMass} galactic={stage.galactic} loading={xm.loading} failed={xm.failed} />
        <ValidationScorecard validation={stage.validation} loading={xm.loading} failed={xm.failed} />
      </div>
      </>
      )}
    </section>
  );
}
