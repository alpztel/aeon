"use client";

import React from "react";
import { Loader2, ShieldCheck } from "lucide-react";
import { useI18n } from "@/i18n/context";
import type { ScorecardRow, Validation } from "@/lib/api";

const CHIP: Record<ScorecardRow["agreement"], string> = {
  consistent: "border-emerald-400/35 bg-emerald-500/15 text-emerald-200",
  partial: "border-amber-400/35 bg-amber-500/15 text-amber-200",
  discrepant: "border-rose-400/35 bg-rose-500/15 text-rose-200",
  not_comparable: "border-white/15 bg-white/5 text-slate-400",
};

interface ValidationScorecardProps {
  validation: Validation | null;
  loading: boolean;
  failed?: boolean;
}

/** Stage 4: AEON's numbers next to SIMBAD / literature, row by row, with the verdict of a fixed rule. */
export function ValidationScorecard({ validation, loading, failed = false }: ValidationScorecardProps) {
  const { dict, lang } = useI18n();
  const t = dict.science;

  const header = (
    <div className="mb-3 flex items-start gap-2">
      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-signal" strokeWidth={1.75} />
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-slate-100">{t.validationTitle}</h3>
        <p className="mt-0.5 text-[11px] leading-relaxed text-slate-400">{t.validationLead}</p>
      </div>
    </div>
  );
  const shell = (body: React.ReactNode) => (
    <div className="rounded-xl border border-white/10 bg-black/40 p-4">
      {header}
      {body}
    </div>
  );

  if (loading) {
    return shell(
      <p className="flex items-center gap-2 text-xs text-slate-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t.loading}
      </p>
    );
  }
  if (failed || !validation) return shell(<p className="text-xs text-slate-400">{t.serviceDown}</p>);
  if (validation.status === "not_applicable") {
    return shell(
      <>
        <p className="text-xs text-slate-300">{t.notApplicable}</p>
        {validation.reason && <p className="mt-1 text-[11px] text-slate-500">{validation.reason}</p>}
      </>
    );
  }

  const rows = validation.rows ?? [];
  const simbadStatus = validation.simbad?.status;
  const simbadLabel = simbadStatus && simbadStatus in t.simbadStatus ? t.simbadStatus[simbadStatus as keyof typeof t.simbadStatus] : null;
  const simbadName = validation.simbad?.object && typeof validation.simbad.object.main_id === "string" ? validation.simbad.object.main_id : null;
  const sources = validation.literature?.sources ?? [];
  const synthesis = validation.synthesis ? validation.synthesis[lang] : null;

  return shell(
    <>
      <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[10px]">
        {simbadLabel && (
          <span
            className={`aeon-mono rounded-full border px-2 py-0.5 ${
              simbadStatus === "unavailable" || simbadStatus === "not_found" ? CHIP.partial : CHIP.consistent
            }`}
            title={validation.simbad?.reason ?? undefined}
          >
            {simbadLabel}
            {simbadName ? ` · ${simbadName}` : ""}
          </span>
        )}
        <span className={`aeon-mono rounded-full border px-2 py-0.5 ${sources.length ? CHIP.consistent : CHIP.not_comparable}`}>
          {sources.length ? `${t.literature} · ${sources.length}` : t.noLiterature}
        </span>
      </div>

      <div className="overflow-hidden rounded-lg border border-white/10">
        <div className="grid grid-cols-[1.1fr_1fr_1fr] gap-2 border-b border-white/10 bg-white/[0.03] px-3 py-1.5 text-[10px] tracking-wide text-slate-400">
          <span>{t.quantity}</span>
          <span>{t.aeon}</span>
          <span>{t.reference}</span>
        </div>
        {rows.map((r) => (
          <div key={r.key} className="border-b border-white/5 px-3 py-2 last:border-b-0">
            <div className="grid grid-cols-[1.1fr_1fr_1fr] items-baseline gap-2 text-xs">
              <span className="min-w-0 text-slate-300">
                {r.label ? r.label[lang] : r.key}
                {r.unit ? <span className="text-slate-500"> ({r.unit})</span> : null}
              </span>
              <span className="aeon-mono break-words text-slate-100" title={r.aeon_source ?? undefined}>
                {r.aeon_text ?? "-"}
              </span>
              <span className="aeon-mono break-words text-slate-100" title={r.reference_source ?? undefined}>
                {r.reference_text ?? "-"}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap items-start gap-2">
              <span className={`aeon-mono shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${CHIP[r.agreement]}`}>
                {t.agreement[r.agreement]}
              </span>
              {r.agreement === "not_comparable" && r.not_comparable_reason && (
                <span className="min-w-0 flex-1 text-[10px] leading-relaxed text-slate-500">{r.not_comparable_reason}</span>
              )}
              {(r.agreement === "partial" || r.agreement === "discrepant") && r.explanation && (
                <span className="min-w-0 flex-1 text-[10px] leading-relaxed text-slate-400">{r.explanation[lang]}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {synthesis && (
        <div className="mt-3 rounded-lg border border-white/10 bg-black/30 p-3">
          <p className="text-[10px] tracking-wide text-slate-400">{t.synthesis}</p>
          <p className="mt-1 text-xs leading-relaxed text-slate-200">{synthesis}</p>
          <p className="mt-1.5 text-[10px] text-slate-500">{t.synthesisMethod}</p>
        </div>
      )}

      {(sources.length > 0 || validation.rule) && (
        <details className="mt-3 text-[11px] text-slate-400">
          <summary className="cursor-pointer text-slate-300">{t.sources}</summary>
          <ul className="mt-1.5 space-y-1">
            {sources.map((s) => (
              <li key={s.bibcode}>
                {s.ref} · <span className="aeon-mono text-slate-500">{s.bibcode}</span>
                {s.arxiv ? <span className="aeon-mono text-slate-500"> · arXiv:{s.arxiv}</span> : null}
              </li>
            ))}
            {validation.rule && <li className="text-slate-500">{validation.rule}</li>}
          </ul>
        </details>
      )}
    </>
  );
}
