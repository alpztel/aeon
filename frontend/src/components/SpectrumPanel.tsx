"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bookmark,
  Loader2,
} from "lucide-react";
import { useI18n } from "@/i18n/context";
import { DataFacts, DataModeBadge, dateRange, fill, num } from "@/components/DataFacts";
import {
  getSpectrum,
  spectrumPipeline,
  type CatalogObject,
  type Epoch,
  type SpectrumResponse,
} from "@/lib/api";

interface SpectrumPanelProps {
  coords: { ra: number; dec: number };
  epoch: Epoch;
  selectedObject: CatalogObject | null;
}

const MOLECULE_BANDS: Record<
  "H2O" | "CH4" | "CO2" | "CO",
  { halfWidth: number; color: string; border: string; label: string }
> = {
  H2O: {
    halfWidth: 0.14,
    color: "rgba(34, 211, 238, 0.12)",
    border: "rgba(34, 211, 238, 0.45)",
    label: "H₂O",
  },
  CH4: {
    halfWidth: 0.16,
    color: "rgba(245, 158, 11, 0.14)",
    border: "rgba(245, 158, 11, 0.55)",
    label: "CH₄",
  },
  CO2: {
    halfWidth: 0.12,
    color: "rgba(167, 139, 250, 0.14)",
    border: "rgba(167, 139, 250, 0.5)",
    label: "CO₂",
  },
  CO: {
    halfWidth: 0.12,
    color: "rgba(244, 63, 94, 0.12)",
    border: "rgba(244, 63, 94, 0.45)",
    label: "CO",
  },
};

export function SpectrumPanel({ coords, epoch, selectedObject }: SpectrumPanelProps) {
  const { dict } = useI18n();

  const [spectrum, setSpectrum] = useState<SpectrumResponse | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [logScale, setLogScale] = useState(false);
  const [pinned, setPinned] = useState<{
    label: string;
    data: SpectrumResponse;
  } | null>(null);

  const plotRef = useRef<HTMLDivElement | null>(null);

  const reqKey = `${coords.ra}:${coords.dec}:${epoch}`;
  const loading = loadedKey !== reqKey;

  useEffect(() => {
    let active = true;
    getSpectrum({ ra: coords.ra, dec: coords.dec, epoch })
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setSpectrum(data);
        setFromCache(cached);
        setError(null);
        setLoadedKey(reqKey);
      })
      .catch(() => {
        if (!active) return;
        setError(dict.spectrum.error);
        setLoadedKey(reqKey);
      });
    return () => {
      active = false;
    };
  }, [coords.ra, coords.dec, epoch, reqKey, dict.spectrum.error]);

  // Render Plotly chart
  useEffect(() => {
    if (!spectrum || !plotRef.current) return;
    const container = plotRef.current;
    let cancelled = false;

    import("plotly.js-dist-min").then((Plotly) => {
      if (cancelled || !container) return;

      const yVals = logScale
        ? spectrum.flux_ujy.map((v) => Math.max(v, 0.05))
        : spectrum.flux_ujy;
      // Real data: bands no SPHEREx frame measured are interpolated fill (open grey markers).
      const pipe = spectrumPipeline(spectrum);
      const measured =
        pipe.data_mode === "fits_archive" && pipe.measured?.length === spectrum.flux_ujy.length ? pipe.measured : null;
      // Measured but centred on a neighbour inside the aperture: not the target's light (amber diamonds).
      const blendedBands = measured && pipe.blended?.length === measured.length ? pipe.blended : null;

      const traces: import("plotly.js-dist-min").PlotData[] = [
        {
          x: spectrum.wavelength_um,
          y: yVals,
          type: "scatter",
          mode: "lines+markers",
          name: `${dict.spectrum.currentCurve} (${epoch})`,
          line: { color: "#9db4f0", width: 2 },
          marker: measured
            ? {
                color: measured.map((m, i) => (blendedBands?.[i] ? "#f5a524" : m ? "#9db4f0" : "rgba(255,255,255,0.35)")),
                symbol: measured.map((m, i) => (blendedBands?.[i] ? "diamond-open" : m ? "circle" : "circle-open")),
                size: measured.map((m, i) => (blendedBands?.[i] ? 7 : m ? 5 : 6)),
              }
            : { color: "#9db4f0", size: 4 },
          error_y: {
            type: "data",
            array: spectrum.flux_err_ujy,
            visible: !logScale,
            color: "rgba(34,211,238,0.35)",
            thickness: 1,
            width: 2,
          },
          hovertemplate: "λ = %{x:.3f} µm<br>Fν = %{y:.2f} µJy<extra></extra>",
        },
      ];

      if (pinned) {
        const pinnedY = logScale
          ? pinned.data.flux_ujy.map((v) => Math.max(v, 0.05))
          : pinned.data.flux_ujy;
        traces.push({
          x: pinned.data.wavelength_um,
          y: pinnedY,
          type: "scatter",
          mode: "lines",
          name: `${dict.spectrum.pinnedLabel} (${pinned.label})`,
          line: { color: "#ff5a1f", width: 1.75, dash: "dash" },
          hovertemplate: "λ = %{x:.3f} µm<br>Ref = %{y:.2f} µJy<extra></extra>",
        });
      }

      const shapes: import("plotly.js-dist-min").Shape[] = [];
      const annotations: import("plotly.js-dist-min").Annotation[] = [];

      let labelRow = 0;
      for (const feat of spectrum.absorption_features ?? []) {
        if (!feat.molecule || feat.center_um === undefined) continue;
        const meta = MOLECULE_BANDS[feat.molecule];
        if (!meta) continue;
        shapes.push({
          type: "rect",
          xref: "x",
          yref: "paper",
          x0: feat.center_um - meta.halfWidth,
          x1: feat.center_um + meta.halfWidth,
          y0: 0,
          y1: 1,
          fillcolor: meta.color,
          line: { width: 1, color: meta.border, dash: feat.detected ? "solid" : "dot" },
        });
        // Label detected bands only, staggered over three rows so neighbours never overlap;
        // wavelengths and depths are listed under the chart.
        if (feat.detected) {
          annotations.push({
            x: feat.center_um,
            y: [0.98, 0.9, 0.82][labelRow++ % 3],
            xref: "x",
            yref: "paper",
            text: meta.label,
            showarrow: false,
            font: { color: "#ece8e3", size: 10 },
            bgcolor: "rgba(5,5,6,0.7)",
          });
        }
      }

      Plotly.react(
        container,
        traces,
        {
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(255,255,255,0.015)",
          margin: { l: 56, r: 20, t: 24, b: 46 },
          font: { color: "#c2bbb3", size: 11 },
          xaxis: {
            title: { text: dict.spectrum.xAxis },
            gridcolor: "rgba(255,255,255,0.06)",
            zerolinecolor: "rgba(255,255,255,0.1)",
            range: [0.7, 5.05],
          },
          yaxis: {
            title: { text: dict.spectrum.yAxis },
            type: logScale ? "log" : "linear",
            gridcolor: "rgba(255,255,255,0.06)",
            zerolinecolor: "rgba(255,255,255,0.1)",
          },
          legend: {
            orientation: "h",
            x: 0,
            y: 1.14,
            bgcolor: "rgba(0,0,0,0)",
          },
          shapes,
          annotations,
          autosize: true,
        },
        {
          responsive: true,
          displayModeBar: false,
          displaylogo: false,
        }
      );
    });

    return () => {
      cancelled = true;
    };
  }, [spectrum, pinned, logScale, epoch, dict.spectrum]);

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

  const isSynthetic =
    selectedObject?.is_synthetic || spectrum?.matched_object?.is_synthetic;
  const pipe = spectrumPipeline(spectrum);

  return (
    <section className="aeon-panel rounded-2xl p-4 @xl:p-5">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <Activity className="h-4 w-4 text-cyan-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
            {dict.spectrum.title}
          </h2>
          {spectrum?.snr_median !== undefined && (
            <span className="aeon-mono rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2.5 py-0.5 text-[11px] text-cyan-200">
              {dict.spectrum.snrMedian}: {spectrum.snr_median.toFixed(1)}
            </span>
          )}
          <DataModeBadge
            mode={pipe.data_mode}
            realLabel={dict.data.realSpherex}
            modelLabel={dict.data.physicalModel}
            detail={typeof pipe.n_bands_measured === "number" ? `${pipe.n_bands_measured}/102` : null}
          />
          {isSynthetic && (
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

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {/* Linear / Log Toggle */}
          <button
            type="button"
            onClick={() => setLogScale((s) => !s)}
            className={`rounded-lg border px-2.5 py-1.5 font-medium transition ${
              logScale
                ? "border-violet-400/40 bg-violet-500/20 text-violet-200"
                : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
            }`}
          >
            {logScale ? dict.spectrum.logScale : dict.spectrum.linearScale}
          </button>

          {/* Pin / Clear Reference */}
          {pinned ? (
            <button
              type="button"
              onClick={() => setPinned(null)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/40 bg-amber-500/20 px-2.5 py-1.5 font-medium text-amber-200 transition hover:bg-amber-500/30"
            >
              <Bookmark className="h-3.5 w-3.5 fill-current" />
              <span>{dict.spectrum.clearReference}</span>
            </button>
          ) : (
            <button
              type="button"
              disabled={!spectrum}
              onClick={() => {
                if (!spectrum) return;
                const label = `${selectedObject?.name ?? `${coords.ra.toFixed(2)}°`} · ${epoch}`;
                setPinned({ label, data: spectrum });
              }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 font-medium text-slate-300 transition hover:bg-white/10 disabled:opacity-40"
            >
              <Bookmark className="h-3.5 w-3.5" />
              <span>{dict.spectrum.pinReference}</span>
            </button>
          )}

        </div>
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      {pipe.epoch_folded && pipe.observed_quarter && (
        <p className="mb-3 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {fill(dict.data.folded, { q: pipe.observed_quarter, e: spectrum?.epoch ?? epoch })}
        </p>
      )}
      {pipe.data_mode === "physical_model" && (
        <p className="mb-3 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-slate-300">
          {dict.data.modelNoData}
          {pipe.archive_fallback_reason ? (
            <span className="aeon-mono mt-1 block text-[11px] text-slate-500">{pipe.archive_fallback_reason}</span>
          ) : null}
        </p>
      )}

      {/* Plot Container */}
      <div className="relative h-[320px] w-full overflow-hidden rounded-xl border border-white/10 bg-black/40">
        <div ref={plotRef} className="h-full w-full" />
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-xs">
            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-[#0E0E10]/90 px-3 py-2 text-xs text-slate-200">
              <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
              <span>{dict.spectrum.loading}</span>
            </div>
          </div>
        )}
      </div>

      {pipe.data_mode === "fits_archive" && (
        <DataFacts
          className="mt-3"
          facts={[
            { label: dict.data.epoch, value: spectrum?.epoch ?? epoch },
            pipe.observed_quarter
              ? { label: dict.data.observedQuarter, value: pipe.observed_quarter, tone: pipe.epoch_folded ? "warn" : "real" }
              : null,
            typeof pipe.n_bands_measured === "number" && {
              label: dict.data.bandsMeasured,
              value: `${pipe.n_bands_measured} / 102`,
              tone: "real",
            },
            typeof pipe.n_frames_used === "number" && {
              label: dict.data.framesUsed,
              value: `${pipe.n_frames_used}${typeof pipe.n_frames === "number" ? ` / ${pipe.n_frames}` : ""}${
                typeof pipe.n_frames_rejected === "number" && pipe.n_frames_rejected > 0
                  ? ` (${pipe.n_frames_rejected} ${dict.data.rejected})`
                  : ""
              }`,
            },
            dateRange(pipe.obs_date_range) ? { label: dict.data.obsDates, value: dateRange(pipe.obs_date_range) } : null,
            num(pipe.aperture_px, 2) !== null && { label: dict.data.aperture, value: `${num(pipe.aperture_px, 2)} px` },
            typeof pipe.n_bands_blended === "number" && pipe.n_bands_blended > 0
              ? {
                  label: dict.data.blendedBands,
                  value: `${pipe.n_bands_blended}${num(pipe.blend_offset_arcsec, 1) !== null ? ` · ${num(pipe.blend_offset_arcsec, 1)}″` : ""}`,
                  tone: "warn",
                  title: dict.data.blendedHint,
                }
              : null,
          ]}
        />
      )}
      {pipe.data_mode === "fits_archive" &&
        ((pipe.measured && pipe.measured.some((m) => !m)) || (pipe.n_bands_blended ?? 0) > 0) && (
          <p className="mt-2 text-[11px] text-slate-500">
            ● {dict.data.measured} · ○ {dict.data.interpolated}
            {(pipe.n_bands_blended ?? 0) > 0 ? ` · ◇ ${dict.data.blendedLegend}` : ""}
          </p>
        )}

      {/* Absorption Feature Badges */}
      {spectrum?.absorption_features && spectrum.absorption_features.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="font-medium text-slate-400">
            {dict.spectrum.absorptionTitle}:
          </span>
          {spectrum.absorption_features.map((feat, idx) => {
            const mol = feat.molecule ?? "H2O";
            const meta = MOLECULE_BANDS[mol];
            return (
              <div
                key={idx}
                className={`aeon-mono inline-flex items-center gap-2 rounded-lg border px-2.5 py-1 text-[11px] ${
                  feat.detected
                    ? "border-amber-400/40 bg-amber-500/15 text-amber-200"
                    : "border-white/10 bg-white/5 text-slate-400"
                }`}
              >
                <span className="font-semibold">{meta?.label ?? mol}</span>
                <span>{feat.center_um?.toFixed(2)} µm</span>
                {feat.depth !== undefined && (
                  <span>
                    {dict.spectrum.depth}:{" "}
                    {Math.abs(feat.depth) >= 0.99 ? "n/a" : `${(feat.depth * 100).toFixed(0)}%`}
                  </span>
                )}
                <span className="rounded bg-black/40 px-1.5 py-0.2 text-[10px]">
                  {feat.detected ? dict.spectrum.detected : dict.spectrum.notDetected}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
