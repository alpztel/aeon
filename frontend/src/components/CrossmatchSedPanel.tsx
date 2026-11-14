"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ExternalLink,
  Flame,
  Loader2,
  Satellite,
} from "lucide-react";
import { useI18n } from "@/i18n/context";
import {
  getCrossmatch,
  type CatalogObject,
  type CrossmatchResult,
} from "@/lib/api";

interface CrossmatchSedPanelProps {
  coords: { ra: number; dec: number };
  selectedObject: CatalogObject | null;
  onOpenPip: (overlaps: NonNullable<CrossmatchResult["mast_overlap"]>) => void;
}

const SURVEY_COLORS: Record<string, string> = {
  Gaia: "#38bdf8",
  SPHEREx: "#22d3ee",
  WISE: "#f59e0b",
};

export function CrossmatchSedPanel({
  coords,
  selectedObject,
  onOpenPip,
}: CrossmatchSedPanelProps) {
  const { dict } = useI18n();

  const [data, setData] = useState<CrossmatchResult | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const plotRef = useRef<HTMLDivElement | null>(null);
  const reqKey = `${coords.ra}:${coords.dec}`;
  const loading = loadedKey !== reqKey;

  useEffect(() => {
    let active = true;
    getCrossmatch({ ra: coords.ra, dec: coords.dec, radius_arcsec: 10 })
      .then(({ data: res, fromCache: cached }) => {
        if (!active) return;
        setData(res);
        setFromCache(cached);
        setError(null);
        setLoadedKey(reqKey);
      })
      .catch(() => {
        if (!active) return;
        setData(null);
        setFromCache(false);
        setError(dict.missions.serviceUnavailable);
        setLoadedKey(reqKey);
      });
    return () => {
      active = false;
    };
  }, [coords.ra, coords.dec, reqKey, dict.missions.serviceUnavailable]);

  // Render full 0.4 - 22 um SED with Plotly
  useEffect(() => {
    if (!data?.sed || !plotRef.current) return;
    const container = plotRef.current;
    let cancelled = false;

    import("plotly.js-dist-min").then((Plotly) => {
      if (cancelled || !container) return;

      const bySurvey = new Map<string, NonNullable<CrossmatchResult["sed"]>>();
      for (const pt of data.sed ?? []) {
        const s = pt.survey ?? "SPHEREx";
        const arr = bySurvey.get(s) ?? [];
        arr.push(pt);
        bySurvey.set(s, arr);
      }

      const traces: import("plotly.js-dist-min").PlotData[] = [];
      for (const [survey, pts] of bySurvey.entries()) {
        const sorted = [...pts].sort((a, b) => a.wavelength_um - b.wavelength_um);
        const color = SURVEY_COLORS[survey] ?? "#a78bfa";
        traces.push({
          x: sorted.map((p) => p.wavelength_um),
          y: sorted.map((p) => Math.max(p.flux_ujy, 0.05)),
          type: "scatter",
          mode: survey === "SPHEREx" ? "lines+markers" : "markers",
          name: survey,
          line: { color, width: 1.75 },
          marker: { color, size: survey === "SPHEREx" ? 4 : 8 },
          error_y: {
            type: "data",
            array: sorted.map((p) => p.flux_err_ujy ?? 0),
            visible: true,
            color: "rgba(255,255,255,0.25)",
          },
          hovertemplate: `${survey}<br>λ = %{x:.2f} µm<br>Fν = %{y:.2f} µJy<extra></extra>`,
        });
      }

      Plotly.react(
        container,
        traces,
        {
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(3,7,18,0.65)",
          margin: { l: 58, r: 20, t: 24, b: 46 },
          font: { color: "#cbd5e1", size: 11 },
          xaxis: {
            title: { text: dict.missions.sedX },
            gridcolor: "rgba(255,255,255,0.06)",
            zerolinecolor: "rgba(255,255,255,0.1)",
          },
          yaxis: {
            title: { text: dict.missions.sedY },
            type: "log",
            gridcolor: "rgba(255,255,255,0.06)",
            zerolinecolor: "rgba(255,255,255,0.1)",
          },
          legend: {
            orientation: "h",
            x: 0,
            y: 1.14,
            bgcolor: "rgba(0,0,0,0)",
          },
          autosize: true,
        },
        { responsive: true, displayModeBar: false, displaylogo: false }
      );
    });

    return () => {
      cancelled = true;
    };
  }, [data, dict.missions.sedX, dict.missions.sedY]);

  useEffect(() => {
    const container = plotRef.current;
    return () => {
      if (container) {
        import("plotly.js-dist-min")
          .then((Plotly) => Plotly.purge(container))
          .catch(() => {});
      }
    };
  }, []);

  return (
    <section className="aeon-panel rounded-2xl p-4 sm:p-5">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <Satellite className="h-4 w-4 text-cyan-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
            {dict.missions.title}
          </h2>

          {data?.unmatched_ir_candidate && (
            <span
              title={dict.missions.unmatchedHint}
              className="inline-flex items-center gap-1 rounded-full border border-amber-400/50 bg-amber-500/20 px-2.5 py-0.5 text-[11px] font-semibold text-amber-200"
            >
              <Flame className="h-3.5 w-3.5 text-amber-400" />
              <span>{dict.missions.unmatchedCold}</span>
            </span>
          )}

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

        <button
          type="button"
          onClick={() => onOpenPip(data?.mast_overlap ?? [])}
          className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-400/35 bg-cyan-500/15 px-3 py-1.5 text-xs font-medium text-cyan-200 transition hover:bg-cyan-500/25"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          <span>
            {dict.missions.openJwstPip} ({data?.mast_overlap?.length ?? 0})
          </span>
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* SED Plot */}
        <div className="relative h-[300px] overflow-hidden rounded-xl border border-white/10 bg-black/40 lg:col-span-8">
          <div ref={plotRef} className="h-full w-full" />
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-xs">
              <Loader2 className="h-5 w-5 animate-spin text-cyan-400" />
            </div>
          )}
        </div>

        {/* Counterpart Cards (Gaia DR3 + WISE) */}
        <div className="flex flex-col justify-between gap-3 lg:col-span-4">
          <div className="rounded-xl border border-white/10 bg-black/30 p-3.5 text-xs">
            <h3 className="mb-2 font-semibold uppercase tracking-wider text-sky-300">
              {dict.missions.gaiaTitle}
            </h3>
            {!data ? (
              <p className="text-slate-500">—</p>
            ) : !data.gaia || data.gaia.length === 0 ? (
              <p className="text-slate-400">{dict.missions.noGaia}</p>
            ) : (
              <div className="aeon-mono space-y-1 text-[11px] text-slate-200">
                {data.gaia.map((g, idx) => (
                  <div key={idx} className="rounded bg-white/5 p-2">
                    <p className="font-semibold text-sky-200">
                      {String(g.source_id ?? "Gaia DR3")}
                    </p>
                    <p className="text-slate-300">
                      G = {String(g.phot_g_mean_mag ?? "—")} · BP−RP = {String(g.bp_rp ?? "—")}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-white/10 bg-black/30 p-3.5 text-xs">
            <h3 className="mb-2 font-semibold uppercase tracking-wider text-amber-300">
              {dict.missions.wiseTitle}
            </h3>
            {!data ? (
              <p className="text-slate-500">—</p>
            ) : !data.wise || data.wise.length === 0 ? (
              <p className="text-slate-400">{dict.missions.noWise}</p>
            ) : (
              <div className="aeon-mono space-y-1 text-[11px] text-slate-200">
                {data.wise.map((w, idx) => (
                  <div key={idx} className="rounded bg-white/5 p-2">
                    <p className="font-semibold text-amber-200">
                      {String(w.designation ?? "AllWISE / CatWISE")}
                    </p>
                    <p className="text-slate-300">
                      W1 = {String(w.w1_ab ?? w.w1mpro ?? "—")} · W2 ={" "}
                      {String(w.w2_ab ?? w.w2mpro ?? "—")}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
