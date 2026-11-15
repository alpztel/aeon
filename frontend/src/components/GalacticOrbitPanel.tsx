"use client";

import React, { useEffect, useState } from "react";
import { Loader2, Orbit } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { AgeMassCard } from "@/components/AgeMassCard";
import { DataFacts, fill, num, signed } from "@/components/DataFacts";
import { MiniChart, type ChartMarker, type ChartSeries } from "@/components/MiniChart";
import {
  simulateGalacticOrbit,
  stage24,
  type CatalogObject,
  type GalacticAstrometry,
  type GalacticOrbitResult,
  type MaybeRange,
} from "@/lib/api";
import { useCrossmatch } from "@/lib/useCrossmatch";

interface GalacticOrbitPanelProps {
  coords: { ra: number; dec: number };
  selectedObject: CatalogObject | null;
}

const RV_COLORS = ["#9db4f0", "#ff5a1f", "#5fd39a"];

function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function range(v: MaybeRange | undefined, digits: number, unit: string, plus = false): string | null {
  const f = (x: number) => (plus ? signed(x, digits) : num(x, digits));
  if (Array.isArray(v) && v.length === 2 && finite(v[0]) && finite(v[1])) return `${f(v[0])} … ${f(v[1])} ${unit}`;
  if (finite(v)) return `${f(v)} ${unit}`;
  return null;
}

/** Stage 3, regime A: age and mass on top, then the orbit in the Milky Way and the closest approach to the Sun. */
export function GalacticOrbitPanel({ coords, selectedObject }: GalacticOrbitPanelProps) {
  const { dict } = useI18n();
  const t = dict.science;
  const xm = useCrossmatch(coords.ra, coords.dec);
  const stage = stage24(xm.data);

  // Astrometry: what the cross-match used (Gaia or the catalog entry); before it answers, the catalog target.
  const inp = stage.galactic?.status === "ok" ? stage.galactic.inputs : null;
  let reqJson: string | null = null;
  const aRa: unknown = inp?.ra;
  const aDec: unknown = inp?.dec;
  const aDist: unknown = inp?.distance_pc;
  const aPmRa: unknown = inp?.pm_ra_cosdec_mas_yr;
  const aPmDec: unknown = inp?.pm_dec_mas_yr;
  const aRv: unknown = inp?.radial_velocity_km_s;
  if (finite(aRa) && finite(aDec) && finite(aDist) && finite(aPmRa) && finite(aPmDec)) {
    const astro: GalacticAstrometry = {
      ra: aRa,
      dec: aDec,
      distance_pc: aDist,
      pm_ra_cosdec_mas_yr: aPmRa,
      pm_dec_mas_yr: aPmDec,
      radial_velocity_km_s: finite(aRv) ? aRv : null,
    };
    reqJson = JSON.stringify({ galactic: astro });
  } else if (!xm.loading && selectedObject && finite(selectedObject.distance_pc) && selectedObject.source !== "field") {
    reqJson = JSON.stringify({ target_id: selectedObject.id });
  }

  const [orbit, setOrbit] = useState<{ key: string; data: GalacticOrbitResult | null }>({ key: "", data: null });
  useEffect(() => {
    if (!reqJson) return undefined;
    let active = true;
    const key = reqJson;
    simulateGalacticOrbit(JSON.parse(key) as { target_id?: string; galactic?: GalacticAstrometry })
      .then((data) => {
        if (active) setOrbit({ key, data });
      })
      .catch(() => {
        if (active) setOrbit({ key, data: null });
      });
    return () => {
      active = false;
    };
  }, [reqJson]);

  const orbitReady = reqJson !== null && orbit.key === reqJson;
  const orbitLoading = xm.loading || (reqJson !== null && !orbitReady);
  const res = orbitReady ? orbit.data : null;

  let body: React.ReactNode;
  if (orbitLoading) {
    body = (
      <p className="flex items-center gap-2 text-xs text-slate-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t.loading}
      </p>
    );
  } else if (!res) {
    body = (
      <>
        <p className="text-xs text-slate-300">{reqJson ? t.orbitUnavailable : t.orbitNeeds}</p>
        {!reqJson && stage.galactic?.reason && <p className="mt-1 text-[11px] text-slate-500">{stage.galactic.reason}</p>}
      </>
    );
  } else {
    const color = (i: number) => (res.orbits.length === 1 ? RV_COLORS[1] : RV_COLORS[i % RV_COLORS.length]);
    const top: ChartSeries[] = [
      { points: res.sun.x_kpc.map((x, i) => [x, res.sun.y_kpc[i]] as [number, number]), color: "#8e877f", dash: "3 3", width: 1.2 },
      ...res.orbits.map((o, i) => ({
        points: o.trajectory.x_kpc.map((x, k) => [x, o.trajectory.y_kpc[k]] as [number, number]),
        color: color(i),
        width: 1.5,
      })),
    ];
    const mid = Math.floor(res.sun.x_kpc.length / 2);
    const topMarkers: ChartMarker[] = [
      { x: 0, y: 0, color: "#f2b544", label: t.galacticCentre },
      { x: res.sun.x_kpc[mid], y: res.sun.y_kpc[mid], color: "#ece8e3", label: t.sun },
    ];
    const heights: ChartSeries[] = res.orbits.map((o, i) => ({
      points: o.trajectory.t_myr.map((tm, k) => [tm, o.trajectory.z_kpc[k]] as [number, number]),
      color: color(i),
      width: 1.4,
    }));
    const enc: ChartSeries[] = res.encounters.map((e, i) => ({
      points: e.curve.t_kyr.map((tk, k) => [tk, e.curve.distance_pc[k]] as [number, number]),
      color: color(i),
      width: 1.6,
    }));
    const encMarkers: ChartMarker[] = [];
    res.encounters.forEach((e, i) => {
      if (e.status === "found") encMarkers.push({ x: e.t_min_kyr, y: e.d_min_pc, color: color(i), label: `${num(e.d_min_pc, 2)} pc` });
    });
    const s = res.summary;
    const envelope = res.rv_status === "marginalized_envelope";

    body = (
      <>
        <p className="mb-2 text-[11px] leading-relaxed text-slate-400">{fill(t.orbitLead, { span: res.span_myr })}</p>
        {envelope && (
          <p className="mb-3 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-[11px] leading-relaxed text-amber-200">
            {t.rvEnvelopeNote}
          </p>
        )}
        {res.orbits.length > 1 && (
          <p className="mb-1 flex flex-wrap gap-3 text-[10px] text-slate-400">
            {res.orbits.map((o, i) => (
              <span key={o.rv_km_s} className="inline-flex items-center gap-1.5">
                <span className="inline-block h-1.5 w-3 rounded-full" style={{ background: color(i) }} />
                RV {signed(o.rv_km_s, 0)} km/s
              </span>
            ))}
          </p>
        )}
        <MiniChart series={top} markers={topMarkers} equal height={300} xLabel="x (kpc)" yLabel="y (kpc)" ariaLabel={t.topView} />
        <p className="mb-3 text-center text-[10px] text-slate-500">{t.topView}</p>
        <MiniChart series={heights} height={150} xLabel={t.timeMyr} yLabel="z (kpc)" ariaLabel={t.heightView} />
        <p className="mb-3 text-center text-[10px] text-slate-500">{t.heightView}</p>

        <DataFacts
          title={t.orbitNumbers}
          facts={[
            { label: t.rPeri, value: range(s.r_peri_kpc, 2, "kpc") },
            { label: t.rApo, value: range(s.r_apo_kpc, 2, "kpc") },
            { label: t.zMax, value: range(s.z_max_kpc, 2, "kpc") },
            { label: t.ecc, value: range(s.eccentricity, 3, "") },
            { label: t.engine, value: res.engine },
          ]}
        />

        <h4 className="mb-1 mt-4 text-xs font-semibold text-slate-200">{t.encounterTitle}</h4>
        <p className="mb-2 text-[11px] text-slate-400">{fill(t.encounterLead, { w: res.encounter_window_kyr })}</p>
        <MiniChart series={enc} markers={encMarkers} yZero height={190} xLabel={t.timeKyr} yLabel={t.encounterAxis} ariaLabel={t.encounterTitle} />
        <DataFacts
          className="mt-2"
          facts={[
            { label: t.dMin, value: range(s.d_min_pc, 3, "pc"), tone: envelope ? "warn" : "real" },
            { label: t.tMin, value: range(s.t_min_kyr, 2, "kyr", true), tone: envelope ? "warn" : "real" },
            s.encounter_status === "beyond_window" ? { label: t.status, value: t.beyondWindow, tone: "warn" } : null,
          ]}
        />
      </>
    );
  }

  return (
    <section className="space-y-4">
      <AgeMassCard ageMass={stage.ageMass} galactic={stage.galactic} loading={xm.loading} failed={xm.failed} />
      <div className="rounded-xl border border-white/10 bg-black/40 p-4">
        <div className="mb-3 flex items-start gap-2">
          <Orbit className="mt-0.5 h-4 w-4 shrink-0 text-signal" strokeWidth={1.75} />
          <h3 className="text-sm font-semibold text-slate-100">{t.orbitTitle}</h3>
        </div>
        {body}
      </div>
    </section>
  );
}
