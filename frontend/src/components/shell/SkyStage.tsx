"use client";

import React, { useEffect, useRef, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { getSkyCutout, imageProvenance, type Epoch, type SkyImage } from "@/lib/api";
import { COLORMAP_OPTIONS, renderSkyArrayToCanvas, type ColormapName } from "@/lib/colormaps";

const ALADIN_SCRIPT_URL = "https://aladin.cds.unistra.fr/AladinLite/api/v3/3.5.1/aladin.js";

interface AladinInstance {
  gotoRaDec: (ra: number, dec: number) => void;
  setFoV: (fovDeg: number) => void;
}

declare global {
  interface Window {
    A?: {
      init: Promise<void>;
      aladin: (selector: string | HTMLElement, options: Record<string, unknown>) => AladinInstance;
    };
  }
}

interface SkyStageProps {
  coords: { ra: number; dec: number };
  epoch: Epoch;
  /** full: nothing open · compact: inspector open · tour: inspector + tour caption */
  fit?: "full" | "compact" | "tour";
}

const FIT_CLASS = {
  full: "md:w-[min(56vw,calc(100dvh-380px),640px)]",
  compact: "md:w-[min(44vw,calc(100dvh-420px),560px)]",
  tour: "md:w-[min(40vw,calc(100dvh-470px),500px)]",
} as const;

const SIZE_PX = 64;
const PIXEL_SCALE_ARCSEC = 6.2;

/** Corner bracket used to frame the observation window. */
function Bracket({ className }: { className: string }) {
  return <span aria-hidden="true" className={`pointer-events-none absolute h-5 w-5 border-white/50 ${className}`} />;
}

/** The observation window: the SPHEREx cutout (or Aladin Lite) framed on the star field, with HUD readouts. */
export function SkyStage({ coords, epoch, fit = "full" }: SkyStageProps) {
  const { dict } = useI18n();
  const [cutout, setCutout] = useState<SkyImage | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [colormap, setColormap] = useState<ColormapName>("inferno");
  const [renderer, setRenderer] = useState<"canvas" | "aladin">("canvas");
  const [aladinFailed, setAladinFailed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const aladinRef = useRef<HTMLDivElement | null>(null);
  const aladinInstanceRef = useRef<AladinInstance | null>(null);

  const fovArcmin = ((SIZE_PX * PIXEL_SCALE_ARCSEC) / 60).toFixed(1);
  const requestKey = `${coords.ra}:${coords.dec}:${epoch}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let active = true;
    const key = `${coords.ra}:${coords.dec}:${epoch}`;
    getSkyCutout({ ra: coords.ra, dec: coords.dec, epoch, size_px: SIZE_PX, pixel_scale_arcsec: PIXEL_SCALE_ARCSEC })
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setCutout(data);
        setFromCache(cached);
        setError(null);
        setLoadedKey(key);
      })
      .catch(() => {
        if (!active) return;
        setError(dict.sky.cutoutError);
        setLoadedKey(key);
      });
    return () => {
      active = false;
    };
  }, [coords.ra, coords.dec, epoch, dict.sky.cutoutError]);

  useEffect(() => {
    if (!cutout || !canvasRef.current) return;
    renderSkyArrayToCanvas(canvasRef.current, cutout.data, cutout.width, cutout.height, colormap);
  }, [cutout, colormap, renderer]);

  useEffect(() => {
    if (renderer !== "aladin" || aladinFailed) return;
    let cancelled = false;
    const mount = async () => {
      try {
        if (!window.A) {
          await new Promise<void>((resolve, reject) => {
            const script = document.createElement("script");
            script.src = ALADIN_SCRIPT_URL;
            script.async = true;
            script.onload = () => resolve();
            script.onerror = () => reject(new Error("Aladin script load failed"));
            document.head.appendChild(script);
          });
        }
        if (cancelled || !window.A || !aladinRef.current) return;
        await window.A.init;
        if (cancelled || !aladinRef.current) return;
        if (!aladinInstanceRef.current) {
          aladinInstanceRef.current = window.A.aladin(aladinRef.current, {
            survey: "P/allWISE/color",
            fov: Number(fovArcmin) / 60,
            target: `${coords.ra} ${coords.dec}`,
            showReticle: true,
            showZoomControl: false,
            showLayersControl: false,
            showFrame: false,
            showCooGrid: false,
          });
        } else {
          aladinInstanceRef.current.gotoRaDec(coords.ra, coords.dec);
        }
      } catch {
        if (!cancelled) {
          setAladinFailed(true);
          setRenderer("canvas");
        }
      }
    };
    void mount();
    return () => {
      cancelled = true;
    };
  }, [renderer, aladinFailed, coords.ra, coords.dec, fovArcmin]);

  const showAladin = renderer === "aladin" && !aladinFailed;
  // Optional, additive field of the backend response (not in the frozen contract's Image schema).
  const provenance = imageProvenance(cutout);
  const lamRange =
    Array.isArray(provenance.wavelength_range_um) &&
    provenance.wavelength_range_um.length === 2 &&
    provenance.wavelength_range_um.every((v) => typeof v === "number" && Number.isFinite(v))
      ? `${provenance.wavelength_range_um[0].toFixed(2)}–${provenance.wavelength_range_um[1].toFixed(2)} µm`
      : null;

  return (
    <figure className={`relative mx-auto w-[min(86vw,calc(100dvh-300px),620px)] min-w-[200px] transition-[width] duration-300 ${FIT_CLASS[fit]}`}>
      {/* HUD — top */}
      <figcaption className="mb-2 flex items-end justify-between gap-2">
        <span className="aeon-label normal-case">
          {dict.sky.fov} {fovArcmin}′ · {PIXEL_SCALE_ARCSEC}″/px · 0.75–5.0 µm
        </span>
        <span className="aeon-label">{dict.sky.northUpEastLeft}</span>
      </figcaption>

      <div className="relative aspect-square w-full bg-black/40 ring-1 ring-white/10">
        {showAladin ? (
          <div ref={aladinRef} className="h-full w-full" />
        ) : (
          <>
            <canvas
              ref={canvasRef}
              role="img"
              aria-label={`${dict.sky.rendererCanvas} · RA ${coords.ra.toFixed(4)} Dec ${coords.dec.toFixed(4)} · ${epoch}`}
              className="h-full w-full [image-rendering:pixelated]"
            />
            {/* reticle */}
            <div aria-hidden="true" className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <span className="absolute h-px w-[18%] bg-gradient-to-r from-transparent via-white/40 to-transparent" />
              <span className="absolute h-[18%] w-px bg-gradient-to-b from-transparent via-white/40 to-transparent" />
              <span className="h-9 w-9 rounded-full border border-white/45" />
            </div>
          </>
        )}

        <Bracket className="-left-px -top-px border-l border-t" />
        <Bracket className="-right-px -top-px border-r border-t" />
        <Bracket className="-bottom-px -left-px border-b border-l" />
        <Bracket className="-bottom-px -right-px border-b border-r" />

        {error && !loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/70 p-6 text-center text-xs text-[var(--aeon-danger)]">
            {error}
          </div>
        )}
      </div>

      {/* loading line sits under the frame instead of covering the data */}
      <div className={`mt-px transition-opacity ${loading ? "opacity-100" : "opacity-0"}`} aria-hidden={!loading}>
        <div className="aeon-progress" />
      </div>

      {/* HUD — bottom */}
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="aeon-label flex items-center gap-2 normal-case">
          {showAladin ? (
            <span className="text-foreground/80">AllWISE · Aladin Lite</span>
          ) : cutout?.data_mode === "fits_archive" ? (
            <span className="flex items-center gap-1.5 text-foreground">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-ice" />
              {dict.shell.realData}
              {provenance.n_frames ? ` · ${provenance.n_frames} ${dict.shell.frames}` : ""}
              {provenance.obs_date_range ? ` · ${provenance.obs_date_range[0].slice(0, 10)} → ${provenance.obs_date_range[1].slice(0, 10)}` : ""}
              {lamRange ? ` · ${lamRange}` : ""}
              {typeof provenance.coverage === "number" && provenance.coverage < 0.999
                ? ` · ${dict.data.coverage} ${Math.round(provenance.coverage * 100)}%`
                : ""}
              {provenance.epoch_folded && provenance.observed_quarter ? (
                <span className="text-[var(--aeon-warn)]" title={dict.data.folded.replace("{q}", provenance.observed_quarter).replace("{e}", cutout?.epoch ?? epoch)}>
                  {` · ${dict.data.observedQuarter} ${provenance.observed_quarter}`}
                </span>
              ) : null}
            </span>
          ) : cutout ? (
            <span className="flex items-center gap-1.5 text-foreground/80">
              <span className="inline-block h-1.5 w-1.5 rounded-full border border-white/50" />
              {dict.shell.modelData} · {dict.shell.noObservation}
            </span>
          ) : null}
          {fromCache && <span className="text-[var(--aeon-warn)]">· {dict.header.dataMode.offline_cache}</span>}
          {loading && <span className="text-ice">· {dict.shell.loading}</span>}
        </span>
        <div className="relative">
          <button
            type="button"
            onClick={() => setSettingsOpen((v) => !v)}
            aria-expanded={settingsOpen}
            aria-label={dict.shell.viewSettings}
            title={dict.shell.viewSettings}
            className="aeon-icon-btn h-8 w-8"
          >
            <SlidersHorizontal className="h-4 w-4" />
          </button>
          {settingsOpen && (
            <div className="aeon-panel aeon-fade-up absolute bottom-10 right-0 z-30 w-60 space-y-3 p-3 shadow-2xl">
              <div>
                <p className="aeon-label mb-1.5">{dict.sky.title}</p>
                <div className="grid grid-cols-2 gap-1 rounded-full border border-line p-0.5 text-xs">
                  {(["canvas", "aladin"] as const).map((r) => (
                    <button
                      key={r}
                      type="button"
                      disabled={r === "aladin" && aladinFailed}
                      onClick={() => setRenderer(r)}
                      className={`rounded-full px-2 py-1 transition disabled:opacity-40 ${
                        renderer === r ? "bg-white/10 text-foreground" : "text-muted hover:text-foreground"
                      }`}
                    >
                      {r === "canvas" ? dict.sky.rendererCanvas : dict.sky.rendererAladin}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <p className="aeon-label mb-1.5">{dict.sky.colormap}</p>
                <div className="grid grid-cols-2 gap-1">
                  {COLORMAP_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      disabled={showAladin}
                      onClick={() => setColormap(opt.value)}
                      className={`rounded-full border px-2 py-1 text-xs transition disabled:opacity-40 ${
                        colormap === opt.value
                          ? "border-signal/70 text-foreground"
                          : "border-line text-muted hover:text-foreground"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </figure>
  );
}
