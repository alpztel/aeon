"use client";

import React from "react";

/**
 * Label / value grid for the numbers an API response carries beyond the main plot: provenance,
 * physics, kinematics. Values the service did not send are left out, never shown as zeros.
 */
export type FactTone = "default" | "real" | "model" | "warn";

export interface Fact {
  label: string;
  value: React.ReactNode;
  title?: string;
  tone?: FactTone;
}

const TONE: Record<FactTone, string> = {
  default: "text-slate-100",
  real: "text-cyan-200",
  model: "text-slate-300",
  warn: "text-amber-200",
};

export function DataFacts({
  title,
  facts,
  className = "",
}: {
  title?: string;
  facts: Array<Fact | null | undefined | false>;
  className?: string;
}) {
  const list = facts.filter((f): f is Fact => Boolean(f) && (f as Fact).value !== null && (f as Fact).value !== undefined);
  if (list.length === 0) return null;
  return (
    <div className={`rounded-xl border border-white/10 bg-black/25 p-3 ${className}`}>
      {title && <p className="aeon-label mb-2 normal-case">{title}</p>}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 @xl:grid-cols-3 @4xl:grid-cols-4">
        {list.map((f, i) => (
          <div key={`${f.label}-${i}`} className="min-w-0" title={f.title}>
            <dt className="text-[10px] uppercase tracking-wider text-slate-400">{f.label}</dt>
            <dd className={`aeon-mono mt-0.5 break-words text-xs ${TONE[f.tone ?? "default"]}`}>{f.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** "Real SPHEREx" / "Physical model" pill for a data_mode. */
export function DataModeBadge({
  mode,
  realLabel,
  modelLabel,
  detail,
}: {
  mode: unknown;
  realLabel: string;
  modelLabel: string;
  detail?: string | null;
}) {
  if (mode === "fits_archive") {
    return (
      <span className="aeon-mono inline-flex items-center gap-1.5 rounded-full border border-cyan-400/35 bg-cyan-500/15 px-2.5 py-0.5 text-[10px] font-medium text-cyan-200">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-cyan-300" />
        {realLabel}
        {detail ? ` · ${detail}` : ""}
      </span>
    );
  }
  if (mode === "physical_model") {
    return (
      <span className="aeon-mono inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/5 px-2.5 py-0.5 text-[10px] font-medium text-slate-300">
        <span className="inline-block h-1.5 w-1.5 rounded-full border border-white/50" />
        {modelLabel}
        {detail ? ` · ${detail}` : ""}
      </span>
    );
  }
  return null;
}

/** A finite number formatted with `digits` decimals, or null (the fact is then left out). */
export function num(value: unknown, digits = 2): string | null {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : null;
}

/** Like num() with an explicit sign. */
export function signed(value: unknown, digits = 2): string | null {
  const s = num(value, digits);
  return s === null ? null : (value as number) >= 0 ? `+${s}` : s;
}

/** Scientific notation for very small / large numbers (fluxes in W m⁻²). */
export function sci(value: unknown, digits = 2): string | null {
  return typeof value === "number" && Number.isFinite(value) ? value.toExponential(digits) : null;
}

/** Replace {name} placeholders. */
export function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}

/** First 10 characters (the date) of both ends of an ISO date range. */
export function dateRange(range: unknown): string | null {
  if (!Array.isArray(range) || range.length < 2) return null;
  const [a, b] = range;
  if (typeof a !== "string" || typeof b !== "string") return null;
  return a.slice(0, 10) === b.slice(0, 10) ? a.slice(0, 10) : `${a.slice(0, 10)} → ${b.slice(0, 10)}`;
}
