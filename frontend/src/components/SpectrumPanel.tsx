"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bookmark,
  Loader2,
  Volume2,
  VolumeX,
} from "lucide-react";
import { useI18n } from "@/i18n/context";
import {
  getSpectrum,
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
  const [playingBand, setPlayingBand] = useState<number | null>(null);

  const plotRef = useRef<HTMLDivElement | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const timerRef = useRef<number | null>(null);

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

      const traces: import("plotly.js-dist-min").PlotData[] = [
        {
          x: spectrum.wavelength_um,
          y: yVals,
          type: "scatter",
          mode: "lines+markers",
          name: `${dict.spectrum.currentCurve} (${epoch})`,
          line: { color: "#9db4f0", width: 2 },
          marker: { color: "#9db4f0", size: 4 },
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

      if (playingBand !== null && spectrum.wavelength_um[playingBand] !== undefined) {
        const wl = spectrum.wavelength_um[playingBand];
        shapes.push({
          type: "line",
          xref: "x",
          yref: "paper",
          x0: wl,
          x1: wl,
          y0: 0,
          y1: 1,
          line: { width: 2, color: "#ff5a1f" },
        });
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
  }, [spectrum, pinned, logScale, playingBand, epoch, dict.spectrum]);

  const stopSonification = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    setPlayingBand(null);
  };

  useEffect(() => {
    const container = plotRef.current;
    return () => {
      stopSonification();
      if (container) {
        import("plotly.js-dist-min")
          .then((Plotly) => Plotly.purge(container))
          .catch(() => {});
      }
    };
  }, []);

  const handleToggleSonify = () => {
    if (playingBand !== null) {
      stopSonification();
      return;
    }
    if (!spectrum || spectrum.flux_ujy.length === 0) return;

    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AudioCtx();
    audioCtxRef.current = ctx;

    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    gain.gain.value = 0.001;
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();

    const fluxes = spectrum.flux_ujy;
    const finite = fluxes.filter((v) => Number.isFinite(v));
    const minF = Math.min(...finite, 0);
    const maxF = Math.max(...finite, minF + 1);

    let idx = 0;
    setPlayingBand(0);

    timerRef.current = window.setInterval(() => {
      if (idx >= spectrum.wavelength_um.length) {
        stopSonification();
        return;
      }
      const fVal = fluxes[idx] ?? 0;
      const norm = Math.max(0, Math.min(1, (fVal - minF) / (maxF - minF)));
      // Map band index 0..101 -> 220..1100 Hz, modulate pitch & volume with normalized flux
      const freq = 220 + (idx / 101) * 660 + norm * 240;
      const amp = 0.02 + norm * 0.16;

      osc.frequency.setTargetAtTime(freq, ctx.currentTime, 0.02);
      gain.gain.setTargetAtTime(amp, ctx.currentTime, 0.02);
      setPlayingBand(idx);
      idx += 1;
    }, 45);
  };

  const isSynthetic =
    selectedObject?.is_synthetic || spectrum?.matched_object?.is_synthetic;

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

          {/* Web Audio Sonification */}
          <button
            type="button"
            disabled={!spectrum}
            onClick={handleToggleSonify}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 font-medium transition disabled:opacity-40 ${
              playingBand !== null
                ? "border-amber-400/50 bg-amber-500/25 text-amber-200"
                : "border-cyan-400/35 bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25"
            }`}
          >
            {playingBand !== null ? (
              <>
                <VolumeX className="h-3.5 w-3.5" />
                <span>{dict.spectrum.stopSonify}</span>
              </>
            ) : (
              <>
                <Volume2 className="h-3.5 w-3.5" />
                <span>{dict.spectrum.sonify}</span>
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
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
