"use client";

import React from "react";
import { Hourglass, Loader2 } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { DataFacts, fill, num, signed } from "@/components/DataFacts";
import { MiniChart, type ChartSeries } from "@/components/MiniChart";
import type { AgeChannel, AgeMass, GalacticKinematics } from "@/lib/api";

const COLOR = { spectral: "#9db4f0", kinematic: "#5fd39a", joint: "#ff5a1f" } as const;

function short(x: number): string {
  return String(Number(x.toPrecision(x >= 100 ? 3 : 2)));
}

/** Ages below 0.1 Gyr read better in Myr. */
function ageText(ch: AgeChannel | undefined): string | null {
  if (!ch || typeof ch.median_gyr !== "number" || typeof ch.lo_gyr !== "number" || typeof ch.hi_gyr !== "number") return null;
  const myr = ch.hi_gyr < 0.1;
  const k = myr ? 1000 : 1;
  return `${short(ch.median_gyr * k)} (${short(ch.lo_gyr * k)}–${short(ch.hi_gyr * k)}) ${myr ? "Myr" : "Gyr"}`;
}

function finite(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

interface AgeMassCardProps {
  ageMass: AgeMass | null;
  galactic: GalacticKinematics | null;
  loading: boolean;
  failed?: boolean;
}

/**
 * Stage 2: what the spectrum alone allows (a mass-age curve), what the Galactic velocity allows
 * (an age range), and their product.
 */
export function AgeMassCard({ ageMass, galactic, loading, failed = false }: AgeMassCardProps) {
  const { dict } = useI18n();
  const t = dict.science;

  const header = (
    <div className="mb-3 flex items-start gap-2">
      <Hourglass className="mt-0.5 h-4 w-4 shrink-0 text-signal" strokeWidth={1.75} />
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-slate-100">{t.ageTitle}</h3>
        <p className="mt-0.5 text-[11px] leading-relaxed text-slate-400">{t.ageLead}</p>
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="rounded-xl border border-white/10 bg-black/40 p-4">
        {header}
        <p className="flex items-center gap-2 text-xs text-slate-400">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t.loading}
        </p>
      </div>
    );
  }
  if (failed || !ageMass) {
    return (
      <div className="rounded-xl border border-white/10 bg-black/40 p-4">
        {header}
        <p className="text-xs text-slate-400">{t.serviceDown}</p>
      </div>
    );
  }
  if (ageMass.status === "not_applicable") {
    return (
      <div className="rounded-xl border border-white/10 bg-black/40 p-4">
        {header}
        <p className="text-xs text-slate-300">{t.notApplicable}</p>
        {ageMass.reason && <p className="mt-1 text-[11px] text-slate-500">{ageMass.reason}</p>}
      </div>
    );
  }

  const channels: Array<{ id: "spectral" | "kinematic" | "joint"; label: string; ch: AgeChannel | undefined }> = [
    { id: "spectral", label: t.spectralAge, ch: ageMass.spectral },
    { id: "kinematic", label: t.kinematicAge, ch: ageMass.kinematic },
    { id: "joint", label: t.jointAge, ch: ageMass.joint },
  ];
  const grid = ageMass.age_grid_gyr ?? [];
  const series: ChartSeries[] = [];
  for (const c of channels) {
    const pdf = c.ch?.pdf;
    if (Array.isArray(pdf) && pdf.length === grid.length && grid.length > 1) {
      series.push({
        points: grid.map((a, i) => [a, pdf[i]] as [number, number]),
        color: COLOR[c.id],
        width: c.id === "joint" ? 2.2 : 1.4,
        fill: c.id === "joint",
        dash: c.id === "joint" ? undefined : "4 3",
      });
    }
  }

  const mass = ageMass.mass ?? null;
  const specMass = ageMass.mass_spectral_only ?? null;
  const inMjup = ageMass.mode === "substellar_w2";
  const massText = mass
    ? inMjup
      ? `${short(mass.median_mjup)} (${short(mass.lo_mjup)}–${short(mass.hi_mjup)}) M_Jup`
      : `${short(mass.median_msun)} (${short(mass.lo_msun)}–${short(mass.hi_msun)}) M☉`
    : null;
  const specMassText =
    specMass && mass && mass.from === "joint"
      ? inMjup
        ? `${short(specMass.lo_mjup)}–${short(specMass.hi_mjup)} M_Jup`
        : `${short(specMass.lo_msun)}–${short(specMass.hi_msun)} M☉`
      : null;

  const track = ageMass.degeneracy_track ?? [];
  const first = track[0];
  const last = track[track.length - 1];
  const inputs = ageMass.inputs ?? {};
  const sol = galactic?.status === "ok" ? (galactic.solutions ?? []) : [];
  const mid = sol.length === 3 ? sol[1] : sol[0];
  const env = galactic?.envelope;
  const comp = (key: "u_lsr_km_s" | "v_lsr_km_s" | "w_lsr_km_s" | "v_tot_km_s"): string | null => {
    if (env && Array.isArray(env[key]) && env[key].length === 2) return `${signed(env[key][0], 1)} … ${signed(env[key][1], 1)}`;
    return mid ? signed(mid[key], 1) : null;
  };
  const pop = mid?.membership?.most_likely;
  const popName = pop && pop in t.populations ? t.populations[pop as keyof typeof t.populations] : null;
  const excess = inputs.mid_ir_excess as { detected?: boolean } | undefined;

  return (
    <div className="rounded-xl border border-white/10 bg-black/40 p-4">
      {header}

      <div className="grid grid-cols-1 gap-2 @xl:grid-cols-3">
        {channels.map((c) => {
          const text = ageText(c.ch);
          const status = c.ch?.status;
          return (
            <div key={c.id} className="rounded-lg border border-white/10 bg-black/30 p-3" title={c.ch?.reason ?? c.ch?.method ?? undefined}>
              <p className="flex items-center gap-1.5 text-[10px] tracking-wide text-slate-400">
                <span className="inline-block h-1.5 w-3 rounded-full" style={{ background: COLOR[c.id] }} />
                {c.label}
              </p>
              <p className={`aeon-mono mt-1 text-sm ${c.id === "joint" ? "text-amber-200" : "text-slate-100"}`}>
                {text ?? (status === "no_model_match" ? t.noModelMatch : t.unmeasured)}
              </p>
              {text && c.ch?.constraint && <p className="mt-0.5 text-[10px] text-slate-500">{t.constraint[c.ch.constraint]}</p>}
            </div>
          );
        })}
      </div>

      {series.length > 0 && (
        <div className="mt-3">
          <MiniChart series={series} xLog yZero height={170} xLabel={t.ageAxis} ariaLabel={t.pdfCaption} />
          <p className="text-center text-[10px] text-slate-500">{t.pdfCaption}</p>
        </div>
      )}

      <div className="mt-3 rounded-lg border border-white/10 bg-black/30 p-3">
        <p className="text-[10px] tracking-wide text-slate-400">{t.mass}</p>
        <p className="aeon-mono mt-1 text-base text-slate-100">{massText ?? t.unmeasured}</p>
        {specMassText && (
          <p className="mt-0.5 text-[11px] text-slate-400">
            {t.massSpectralOnly}: <span className="aeon-mono">{specMassText}</span>
          </p>
        )}
        {first && last && first !== last && (
          <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
            {fill(t.degeneracyLine, {
              a1: short(first.age_gyr),
              m1: short(first.mass_mjup),
              a2: short(last.age_gyr),
              m2: short(last.mass_mjup),
            })}
          </p>
        )}
      </div>

      <DataFacts
        className="mt-3"
        title={t.modelValues}
        facts={[
          mass?.model_teff_k ? { label: t.modelTeff, value: `${num(mass.model_teff_k.median, 0)} K (${num(mass.model_teff_k.lo, 0)}–${num(mass.model_teff_k.hi, 0)})` } : null,
          mass?.model_log_g_cgs ? { label: t.modelLogg, value: `${num(mass.model_log_g_cgs.median)} (${num(mass.model_log_g_cgs.lo)}–${num(mass.model_log_g_cgs.hi)})` } : null,
          mass?.model_radius_rjup ? { label: t.modelRadius, value: `${num(mass.model_radius_rjup.median)} R_Jup` } : null,
          mass?.model_log_l_lsun ? { label: t.logL, value: num(mass.model_log_l_lsun.median) } : null,
        ]}
      />

      <DataFacts
        className="mt-3"
        title={t.inputs}
        facts={[
          finite(inputs.distance_pc) !== null
            ? { label: t.distance, value: `${num(inputs.distance_pc, 2)} pc`, title: typeof inputs.distance_source === "string" ? inputs.distance_source : undefined }
            : null,
          finite(inputs.m_w2_abs) !== null
            ? { label: t.w2abs, value: `${num(inputs.m_w2_abs)} ± ${num(inputs.m_w2_sigma)}`, title: typeof inputs.w2_source === "string" ? inputs.w2_source : undefined }
            : null,
          typeof inputs.w2_source === "string" ? { label: t.w2source, value: inputs.w2_source } : null,
          finite(inputs.log_l_lsun) !== null
            ? { label: t.logL, value: `${num(inputs.log_l_lsun)} ± ${num(inputs.log_l_sigma)}`, title: typeof inputs.log_l_note === "string" ? inputs.log_l_note : undefined }
            : null,
          finite(inputs.teff_k) !== null
            ? { label: t.colourTeff, value: `${num(inputs.teff_k, 0)} ± ${num(inputs.teff_sigma_k, 0)} K`, title: typeof inputs.teff_note === "string" ? inputs.teff_note : undefined }
            : null,
          excess ? { label: t.disk, value: excess.detected ? t.diskYes : t.diskNo, tone: excess.detected ? "warn" : "default" } : null,
        ]}
      />

      {sol.length > 0 && (
        <DataFacts
          className="mt-3"
          title={t.velocityTitle}
          facts={[
            { label: "U", value: comp("u_lsr_km_s") ? `${comp("u_lsr_km_s")} km/s` : null },
            { label: "V", value: comp("v_lsr_km_s") ? `${comp("v_lsr_km_s")} km/s` : null },
            { label: "W", value: comp("w_lsr_km_s") ? `${comp("w_lsr_km_s")} km/s` : null },
            { label: t.vTot, value: comp("v_tot_km_s") ? `${comp("v_tot_km_s")} km/s` : null },
            {
              label: t.rv,
              value: galactic?.rv_status === "measured" && mid ? `${signed(mid.rv_km_s, 1)} km/s` : t.rvEnvelope,
              tone: galactic?.rv_status === "measured" ? "real" : "warn",
            },
            popName ? { label: t.population, value: popName } : null,
          ]}
        />
      )}

      {ageMass.assumptions && (
        <details className="mt-3 text-[11px] text-slate-400">
          <summary className="cursor-pointer text-slate-300">{t.assumptions}</summary>
          <ul className="mt-1.5 space-y-1">
            {Object.entries({ ...ageMass.assumptions, ...(ageMass.references ?? {}) }).map(([k, v]) => (
              <li key={k}>
                <span className="aeon-mono text-slate-500">{k}</span> · {v}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
