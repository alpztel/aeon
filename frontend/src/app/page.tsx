"use client";

import React, { useCallback, useEffect, useState } from "react";
import { FileDown, Layers, Orbit, Radar, Sparkles } from "lucide-react";
import { AstroLlmModal } from "@/components/AstroLlmModal";
import { CandidatePoolPanel } from "@/components/CandidatePoolPanel";
import { ClassificationCard } from "@/components/ClassificationCard";
import { CrossmatchSedPanel } from "@/components/CrossmatchSedPanel";
import { DemoTourBar } from "@/components/DemoTourBar";
import { DifferencePanel } from "@/components/DifferencePanel";
import { GcnTicker } from "@/components/GcnTicker";
import { Header } from "@/components/Header";
import { JwstPipWindow } from "@/components/JwstPipWindow";
import { ShiftStackPanel } from "@/components/ShiftStackPanel";
import { ShortcutsModal } from "@/components/ShortcutsModal";
import { SkyMapPanel } from "@/components/SkyMapPanel";
import { SolarSystem3DPanel } from "@/components/SolarSystem3DPanel";
import { SpectrumPanel } from "@/components/SpectrumPanel";
import { useI18n, type Lang } from "@/i18n/context";
import {
  DEMO_TARGETS,
  EPOCHS,
  getHealth,
  searchCatalog,
  type AstrometryPoint,
  type CatalogObject,
  type CrossmatchResult,
  type DataMode,
  type Epoch,
  type UiAction,
} from "@/lib/api";
import { generateAndDownloadDiscoveryPdf } from "@/lib/pdf-report";

export default function HomePage() {
  const { lang, dict, setLang } = useI18n();
  const [dataMode, setDataMode] = useState<DataMode | "checking">("checking");
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [diffOpen, setDiffOpen] = useState(true);
  const [stackOpen, setStackOpen] = useState(true);
  const [orbitOpen, setOrbitOpen] = useState(true);
  const [pipOpen, setPipOpen] = useState(false);
  const [pipOverlaps, setPipOverlaps] = useState<
    NonNullable<CrossmatchResult["mast_overlap"]>
  >([]);
  const [epoch, setEpoch] = useState<Epoch>("2026-Q1");
  const [coords, setCoords] = useState<{ ra: number; dec: number }>({
    ra: 133.79513,
    dec: -7.24514,
  });
  const [selectedObject, setSelectedObject] = useState<CatalogObject | null>(null);
  const [astrometry, setAstrometry] = useState<AstrometryPoint[]>([]);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [tourActive, setTourActive] = useState(false);
  const [tourStep, setTourStep] = useState<0 | 1 | 2>(0);

  const handleDownloadPdf = useCallback(async () => {
    setPdfBusy(true);
    try {
      await generateAndDownloadDiscoveryPdf({
        lang,
        coords,
        epoch,
        selectedObject,
        dataMode,
      });
    } finally {
      setPdfBusy(false);
    }
  }, [lang, coords, epoch, selectedObject, dataMode]);

  const applyTourStep = useCallback(async (step: 0 | 1 | 2) => {
    setTourStep(step);
    setTourActive(true);
    const cfg = DEMO_TARGETS[step] ?? DEMO_TARGETS[0];
    setEpoch(cfg.epoch);
    if (step === 2) {
      setStackOpen(true);
      setOrbitOpen(true);
    } else {
      setDiffOpen(true);
    }
    try {
      const { data } = await searchCatalog({ q: cfg.id, epoch: cfg.epoch });
      if (data.results[0]) {
        setSelectedObject(data.results[0]);
        setCoords({ ra: data.results[0].ra, dec: data.results[0].dec });
        return;
      }
    } catch {
      // fallback to coordinates
    }
    setCoords({ ra: cfg.ra, dec: cfg.dec });
  }, []);

  useEffect(() => {
    let active = true;
    getHealth().then(({ mode }) => {
      if (active) setDataMode(mode);
    });
    searchCatalog({ q: "wise-0855", epoch: "2026-Q1" })
      .then(({ data }) => {
        if (active && data.results[0]) {
          const hit = data.results[0];
          setSelectedObject(hit);
          setCoords({ ra: hit.ra, dec: hit.dec });
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setCmdOpen((prev) => !prev);
        return;
      }

      const target = e.target as HTMLElement | null;
      const isInput =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT" ||
        target?.isContentEditable;
      if (isInput) return;

      if (e.key === "?") {
        e.preventDefault();
        setShortcutsOpen((prev) => !prev);
      } else if (e.key === "d" || e.key === "D") {
        e.preventDefault();
        setDiffOpen((prev) => !prev);
      } else if (e.key === "s" || e.key === "S") {
        e.preventDefault();
        setStackOpen((prev) => !prev);
      } else if (e.key === "3") {
        e.preventDefault();
        setOrbitOpen((prev) => !prev);
      } else if (e.key === "p" || e.key === "P") {
        e.preventDefault();
        void handleDownloadPdf();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleDownloadPdf]);

  const executeUiActions = useCallback(
    async (actions: UiAction[]) => {
      for (const act of actions) {
        const p = act.params ?? {};
        switch (act.type) {
          case "FLY_TO": {
            const q =
              typeof p.target_id === "string"
                ? p.target_id
                : typeof p.q === "string"
                  ? p.q
                  : null;
            const ra = typeof p.ra === "number" ? p.ra : undefined;
            const dec = typeof p.dec === "number" ? p.dec : undefined;
            if (q) {
              try {
                const { data } = await searchCatalog({ q, epoch });
                if (data.results[0]) {
                  setSelectedObject(data.results[0]);
                  setCoords({ ra: data.results[0].ra, dec: data.results[0].dec });
                  break;
                }
              } catch {
                // fallback to coords below
              }
            }
            if (ra !== undefined && dec !== undefined) {
              setCoords({ ra, dec });
            }
            break;
          }
          case "SET_EPOCH": {
            const ep = p.epoch as Epoch | undefined;
            if (ep && EPOCHS.includes(ep)) {
              setEpoch(ep);
            }
            break;
          }
          case "TOGGLE_DIFF": {
            setDiffOpen(typeof p.open === "boolean" ? p.open : true);
            break;
          }
          case "RUN_SHIFT_STACK":
          case "RUN_BLIND_SEARCH": {
            setStackOpen(true);
            break;
          }
          case "OPEN_SPECTRUM": {
            document
              .getElementById("aeon-spectrum-panel")
              ?.scrollIntoView({ behavior: "smooth" });
            break;
          }
          case "OPEN_CROSSMATCH": {
            document
              .getElementById("aeon-crossmatch-panel")
              ?.scrollIntoView({ behavior: "smooth" });
            break;
          }
          case "OPEN_3D_ORBIT": {
            setOrbitOpen(true);
            break;
          }
          case "OPEN_JWST": {
            setPipOpen(true);
            break;
          }
          case "SET_COLORMAP": {
            break;
          }
          case "SET_LANG": {
            if (p.lang === "tr" || p.lang === "en") {
              setLang(p.lang as Lang);
            }
            break;
          }
          case "GENERATE_PDF": {
            await handleDownloadPdf();
            break;
          }
          case "START_DEMO_TOUR": {
            await applyTourStep(0);
            break;
          }
          default:
            break;
        }
      }
    },
    [epoch, setLang, handleDownloadPdf, applyTourStep]
  );

  return (
    <div className="flex min-h-screen flex-col">
      <Header
        dataMode={dataMode}
        onOpenShortcuts={() => setShortcutsOpen(true)}
        onOpenCmdPalette={() => setCmdOpen(true)}
        onStartDemoTour={() => void applyTourStep(0)}
        onDownloadPdf={() => void handleDownloadPdf()}
        pdfBusy={pdfBusy}
      />
      <GcnTicker
        onFlyTo={(ra, dec) => {
          setSelectedObject(null);
          setCoords({ ra, dec });
        }}
      />
      <DemoTourBar
        active={tourActive}
        step={tourStep}
        onSelectStep={(s) => void applyTourStep((s as 0 | 1 | 2))}
        onClose={() => setTourActive(false)}
        onDownloadPdf={() => void handleDownloadPdf()}
      />
      <main className="mx-auto w-full max-w-[1600px] flex-1 space-y-5 px-4 py-5 sm:px-6">
        <SkyMapPanel
          selectedObject={selectedObject}
          onSelectObject={(obj, nextCoords) => {
            setSelectedObject(obj);
            setCoords(nextCoords);
          }}
          epoch={epoch}
          onEpochChange={setEpoch}
          coords={coords}
        />

        {/* Mode Toolbar */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setDiffOpen((prev) => !prev)}
            className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-medium transition ${
              diffOpen
                ? "border-amber-400/50 bg-amber-500/20 text-amber-200"
                : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
            }`}
          >
            <Layers className="h-3.5 w-3.5" />
            <span>{dict.diff.toggle}</span>
          </button>

          <button
            type="button"
            onClick={() => setStackOpen((prev) => !prev)}
            className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-medium transition ${
              stackOpen
                ? "border-violet-400/50 bg-violet-500/20 text-violet-200"
                : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
            }`}
          >
            <Radar className="h-3.5 w-3.5" />
            <span>{dict.stack.toggle}</span>
          </button>

          <button
            type="button"
            onClick={() => setOrbitOpen((prev) => !prev)}
            className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-medium transition ${
              orbitOpen
                ? "border-cyan-400/50 bg-cyan-500/20 text-cyan-200"
                : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
            }`}
          >
            <Orbit className="h-3.5 w-3.5" />
            <span>{dict.orbit.toggle}</span>
          </button>

          <button
            type="button"
            onClick={() => setCmdOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-violet-400/35 bg-violet-500/15 px-3 py-1.5 text-xs font-medium text-violet-200 transition hover:bg-violet-500/25"
          >
            <Sparkles className="h-3.5 w-3.5" />
            <span>{dict.header.cmdPalette} (⌘K)</span>
          </button>

          <button
            type="button"
            onClick={() => void handleDownloadPdf()}
            disabled={pdfBusy}
            className="inline-flex items-center gap-1.5 rounded-xl border border-cyan-400/35 bg-cyan-500/15 px-3 py-1.5 text-xs font-medium text-cyan-200 transition hover:bg-cyan-500/25 disabled:opacity-50"
          >
            <FileDown className="h-3.5 w-3.5" />
            <span>{dict.header.pdfReport} (P)</span>
          </button>
        </div>

        {diffOpen && (
          <DifferencePanel coords={coords} selectedObject={selectedObject} />
        )}

        <div id="aeon-spectrum-panel">
          <SpectrumPanel
            coords={coords}
            epoch={epoch}
            selectedObject={selectedObject}
          />
        </div>

        <ClassificationCard
          coords={coords}
          selectedObject={selectedObject}
        />

        <div id="aeon-crossmatch-panel">
          <CrossmatchSedPanel
            coords={coords}
            selectedObject={selectedObject}
            onOpenPip={(overlaps) => {
              setPipOverlaps(overlaps);
              setPipOpen(true);
            }}
          />
        </div>

        {stackOpen && (
          <ShiftStackPanel
            coords={coords}
            selectedObject={selectedObject}
            onAstrometryReady={setAstrometry}
          />
        )}

        {orbitOpen && (
          <SolarSystem3DPanel
            coords={coords}
            selectedObject={selectedObject}
            astrometry={astrometry}
          />
        )}

        <CandidatePoolPanel
          coords={coords}
          selectedObject={selectedObject}
          onInspectCoords={(ra, dec) => {
            setSelectedObject(null);
            setCoords({ ra, dec });
          }}
        />
      </main>

      <JwstPipWindow
        open={pipOpen}
        onClose={() => setPipOpen(false)}
        overlaps={pipOverlaps}
        coords={coords}
      />

      <AstroLlmModal
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        context={{
          ra: coords.ra,
          dec: coords.dec,
          epoch,
          target_id: selectedObject?.id,
        }}
        onExecuteActions={executeUiActions}
      />

      <ShortcutsModal
        open={shortcutsOpen}
        onClose={() => setShortcutsOpen(false)}
      />
    </div>
  );
}
