"use client";

import React from "react";
import { AlertTriangle } from "lucide-react";
import { useI18n } from "@/i18n/context";
import type { CatalogObject } from "@/lib/api";

interface TargetCardProps {
  selectedObject: CatalogObject | null;
  coords: { ra: number; dec: number };
  compact?: boolean;
}

function Datum({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="aeon-label">{label}</dt>
      <dd className="aeon-mono mt-1 whitespace-nowrap text-[13px] text-foreground">{value}</dd>
    </div>
  );
}

/** Object-centric readout: what you are looking at, always in the same place. */
export function TargetCard({ selectedObject, coords, compact }: TargetCardProps) {
  const { dict, bilingual } = useI18n();
  const obj = selectedObject;
  const kicker = obj ? dict.classes[obj.object_class] : dict.shell.fieldPosition;
  const title = obj?.name ?? `${coords.ra.toFixed(4)}°  ${coords.dec >= 0 ? "+" : ""}${coords.dec.toFixed(4)}°`;
  const pm =
    obj?.pm_ra_cosdec_arcsec_yr !== undefined && obj?.pm_ra_cosdec_arcsec_yr !== null
      ? `${Math.hypot(obj.pm_ra_cosdec_arcsec_yr, obj.pm_dec_arcsec_yr ?? 0).toFixed(2)}″/yr`
      : null;
  const distance =
    obj?.distance_au !== null && obj?.distance_au !== undefined
      ? `${obj.distance_au} AU`
      : obj?.distance_pc !== null && obj?.distance_pc !== undefined
        ? `${obj.distance_pc} pc`
        : null;

  return (
    <section aria-label={dict.shell.target} className="max-w-[420px]">
      <p className="aeon-label flex items-center gap-2">
        <span className="h-1.5 w-1.5 rounded-full bg-signal" />
        {dict.shell.target} · {kicker}
      </p>
      <h1 className="aeon-display mt-2 break-words text-[28px] text-foreground md:text-[34px]">{title}</h1>

      {obj?.is_synthetic && (
        <p className="mt-3 inline-flex items-start gap-2 rounded-lg border border-[var(--aeon-danger)]/50 bg-[var(--aeon-danger)]/10 px-2.5 py-1.5 text-xs text-[#ffb3ba]">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            <strong className="font-semibold">{dict.badges.synthetic}.</strong> {dict.badges.syntheticHint}
          </span>
        </p>
      )}

      <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-3">
        <Datum label={dict.sky.ra} value={`${coords.ra.toFixed(5)}°`} />
        <Datum label={dict.sky.dec} value={`${coords.dec >= 0 ? "+" : ""}${coords.dec.toFixed(5)}°`} />
        {pm && <Datum label={dict.shell.pmShort} value={pm} />}
        {distance && <Datum label={dict.sky.distance} value={distance} />}
        {obj?.teff_k ? <Datum label={dict.sky.teff} value={`${obj.teff_k} K`} /> : null}
        {typeof obj?.mag_ab_w2 === "number" && Number.isFinite(obj.mag_ab_w2) ? (
          <Datum label={dict.data.w2} value={`${obj.mag_ab_w2.toFixed(1)} mag`} />
        ) : null}
      </dl>

      {!compact && obj?.description && (
        <p className="mt-4 line-clamp-3 max-w-[400px] text-[13px] leading-relaxed text-muted md:max-xl:hidden">
          {bilingual(obj.description)}
        </p>
      )}
    </section>
  );
}
