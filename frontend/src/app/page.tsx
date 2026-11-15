"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { AstroLlmModal } from "@/components/AstroLlmModal";
import { CandidatePoolPanel } from "@/components/CandidatePoolPanel";
import { ClassificationCard } from "@/components/ClassificationCard";
import { CrossmatchSedPanel } from "@/components/CrossmatchSedPanel";
import { DifferencePanel } from "@/components/DifferencePanel";
import { JwstPipWindow } from "@/components/JwstPipWindow";
import { ShiftStackPanel } from "@/components/ShiftStackPanel";
import { ShortcutsModal } from "@/components/ShortcutsModal";
import { SolarSystem3DPanel } from "@/components/SolarSystem3DPanel";
import { SpectrumPanel } from "@/components/SpectrumPanel";
import { EpochScrubber, type EpochCoverage } from "@/components/shell/EpochScrubber";
import { Inspector } from "@/components/shell/Inspector";
import { Onboarding } from "@/components/shell/Onboarding";
import { SkyStage } from "@/components/shell/SkyStage";
import { Starfield } from "@/components/shell/Starfield";
import { TargetCard } from "@/components/shell/TargetCard";
import { ToolRail } from "@/components/shell/ToolRail";
import { TopBar } from "@/components/shell/TopBar";
import { TourCaption } from "@/components/shell/TourCaption";
import type { ToolId } from "@/components/shell/tools";
import { useI18n, type Lang } from "@/i18n/context";
import {
  DEMO_TARGETS,
  EPOCHS,
  getHealth,
  getSkyCutout,
  imageProvenance,
  searchCatalog,
  type AstrometryPoint,
  type CatalogObject,
  type CrossmatchResult,
  type DataMode,
  type HealthResponse,
  type Epoch,
  type UiAction,
} from "@/lib/api";
import { generateAndDownloadDiscoveryPdf } from "@/lib/pdf-report";

type Coords = { ra: number; dec: number };

/** Which tool each guided-tour step opens. */
const TOUR_TOOLS: ToolId[] = ["diff", "spectrum", "stack"];

export default function HomePage() {
  const { lang, setLang } = useI18n();
  const [dataMode, setDataMode] = useState<DataMode | "checking">("checking");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [tool, setTool] = useState<ToolId | null>(null);
  const [wide, setWide] = useState(false);
  const [pipOpen, setPipOpen] = useState(false);
  const [pipOverlaps, setPipOverlaps] = useState<NonNullable<CrossmatchResult["mast_overlap"]>>([]);
  const [epoch, setEpoch] = useState<Epoch>(DEMO_TARGETS[0].epoch);
  const [coords, setCoords] = useState<Coords>(DEMO_TARGETS[0].epochCoords[DEMO_TARGETS[0].epoch]);
  const [refCoords, setRefCoords] = useState<Coords>({ ra: DEMO_TARGETS[0].refRa, dec: DEMO_TARGETS[0].refDec });
  const [selectedObject, setSelectedObject] = useState<CatalogObject | null>(null);
  const [astrometry, setAstrometry] = useState<AstrometryPoint[]>([]);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [tourActive, setTourActive] = useState(false);
  const [tourStep, setTourStep] = useState(0);
  const epochSeqRef = useRef(0);

  // Real-vs-model coverage of the four epochs for the current target: the same cutout request the
  // stage makes, so the marks match what the visitor will see. Re-fetched only when the target changes.
  const demoMeta = selectedObject ? DEMO_TARGETS.find((d) => d.id === selectedObject.id) : undefined;
  const coverageKey = demoMeta ? demoMeta.id : `${refCoords.ra.toFixed(5)},${refCoords.dec.toFixed(5)}`;
  const [coverage, setCoverage] = useState<{ key: string; map: EpochCoverage; obsStart: Partial<Record<Epoch, string>> }>({
    key: "",
    map: {},
    obsStart: {},
  });
  useEffect(() => {
    let active = true;
    const meta = demoMeta;
    const base = { ...refCoords };
    Promise.all(
      EPOCHS.map((ep) => {
        const pos = meta?.epochCoords[ep] ?? base;
        return getSkyCutout({ ra: pos.ra, dec: pos.dec, epoch: ep, size_px: 64, pixel_scale_arcsec: 6.2 })
          .then(({ data, fromCache }) => {
            const mode = fromCache ? undefined : data.data_mode === "fits_archive" ? ("real" as const) : ("model" as const);
            const start = mode === "real" ? imageProvenance(data).obs_date_range?.[0] : undefined;
            return [ep, mode, typeof start === "string" ? start : undefined] as const;
          })
          .catch(() => [ep, undefined, undefined] as const);
      })
    ).then((rows) => {
      if (!active) return;
      const map: EpochCoverage = {};
      const obsStart: Partial<Record<Epoch, string>> = {};
      for (const [ep, mode, start] of rows) {
        if (mode) map[ep] = mode;
        if (start) obsStart[ep] = start;
      }
      setCoverage({ key: coverageKey, map, obsStart });
    });
    return () => {
      active = false;
    };
    // demoMeta / refCoords are captured through coverageKey on purpose
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coverageKey]);
  const epochCoverage = coverage.key === coverageKey ? coverage.map : {};
  const obsStart = coverage.key === coverageKey ? coverage.obsStart : {};
  // Real frames are filed by season, whatever the year (a 2025-11 frame serves "2026-Q4"): order the
  // real epochs by when they were really observed, so the default difference runs forward in time.
  const realEpochs = EPOCHS.filter((ep) => epochCoverage[ep] === "real").sort((a, b) => {
    const ta = obsStart[a];
    const tb = obsStart[b];
    return ta && tb ? ta.localeCompare(tb) : EPOCHS.indexOf(a) - EPOCHS.indexOf(b);
  });
  const diffEpochs: [Epoch, Epoch] =
    realEpochs.length >= 2 ? [realEpochs[0], realEpochs[realEpochs.length - 1]] : ["2026-Q1", "2026-Q3"];

  const toggleTool = useCallback((id: ToolId) => setTool((cur) => (cur === id ? null : id)), []);
  const closeTool = useCallback(() => setTool(null), []);

  const selectObject = useCallback((obj: CatalogObject | null, next: Coords, nextRef?: Coords) => {
    setSelectedObject(obj);
    setCoords(next);
    setRefCoords(nextRef ?? next);
  }, []);

  const flyToCoords = useCallback((ra: number, dec: number) => {
    setSelectedObject(null);
    setCoords({ ra, dec });
    setRefCoords({ ra, dec });
  }, []);

  const handleEpochChange = useCallback(
    async (nextEpoch: Epoch) => {
      const seq = ++epochSeqRef.current;
      if (selectedObject && selectedObject.source !== "field") {
        const demoMeta = DEMO_TARGETS.find((d) => d.id === selectedObject.id);
        if (demoMeta?.epochCoords[nextEpoch]) {
          const pre = demoMeta.epochCoords[nextEpoch];
          setSelectedObject((prev) => (prev ? { ...prev, ra: pre.ra, dec: pre.dec } : prev));
          setCoords({ ra: pre.ra, dec: pre.dec });
          setEpoch(nextEpoch);
          return;
        }
        try {
          const { data } = await searchCatalog({ q: selectedObject.id, epoch: nextEpoch });
          if (seq !== epochSeqRef.current) return;
          const hit = data.results[0];
          if (hit) {
            setSelectedObject(hit);
            setCoords({ ra: hit.ra, dec: hit.dec });
            setEpoch(nextEpoch);
            return;
          }
        } catch {
          if (seq !== epochSeqRef.current) return;
        }
      }
      setEpoch(nextEpoch);
    },
    [selectedObject]
  );

  const handleDownloadPdf = useCallback(async () => {
    setPdfBusy(true);
    try {
      await generateAndDownloadDiscoveryPdf({ lang, coords: refCoords, epoch, selectedObject, dataMode });
    } finally {
      setPdfBusy(false);
    }
  }, [lang, refCoords, epoch, selectedObject, dataMode]);

  const applyTourStep = useCallback(async (step: number) => {
    const s = Math.max(0, Math.min(DEMO_TARGETS.length - 1, step));
    setTourStep(s);
    setTourActive(true);
    const cfg = DEMO_TARGETS[s];
    setEpoch(cfg.epoch);
    // On wide screens the tour opens the matching tool beside the narration; on smaller screens
    // the inspector would cover the narration, so the visitor opens it from the rail.
    if (window.matchMedia("(min-width: 1024px)").matches) setTool(TOUR_TOOLS[s] ?? null);
    try {
      const [epRes, refRes] = await Promise.all([searchCatalog({ q: cfg.id, epoch: cfg.epoch }), searchCatalog({ q: cfg.id })]);
      const hit = epRes.data.results[0];
      const refHit = refRes.data.results[0];
      if (hit) {
        setSelectedObject(hit);
        setCoords({ ra: hit.ra, dec: hit.dec });
        setRefCoords({ ra: refHit?.ra ?? cfg.refRa, dec: refHit?.dec ?? cfg.refDec });
        return;
      }
    } catch {
      // fall back to the stored coordinates
    }
    setCoords(cfg.epochCoords[cfg.epoch] ?? { ra: cfg.ra, dec: cfg.dec });
    setRefCoords({ ra: cfg.refRa, dec: cfg.refDec });
  }, []);

  useEffect(() => {
    let active = true;
    getHealth().then(({ mode, health: h }) => {
      if (!active) return;
      setDataMode(mode);
      setHealth(mode === "offline_cache" ? null : h);
    });
    Promise.all([searchCatalog({ q: "wise-0855", epoch: DEMO_TARGETS[0].epoch }), searchCatalog({ q: "wise-0855" })])
      .then(([epRes, refRes]) => {
        const hit = epRes.data.results[0];
        if (!active || !hit) return;
        const refHit = refRes.data.results[0];
        setSelectedObject(hit);
        setCoords({ ra: hit.ra, dec: hit.dec });
        setRefCoords({ ra: refHit?.ra ?? DEMO_TARGETS[0].refRa, dec: refHit?.dec ?? DEMO_TARGETS[0].refDec });
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
      if (isInput || e.metaKey || e.ctrlKey || e.altKey) return;
      if (target?.closest("[role=dialog]")) return;

      const k = e.key;
      if (k === "?") {
        e.preventDefault();
        setShortcutsOpen((prev) => !prev);
      } else if (k === "d" || k === "D") {
        e.preventDefault();
        toggleTool("diff");
      } else if (k === "s" || k === "S") {
        e.preventDefault();
        toggleTool("stack");
      } else if (k === "3") {
        e.preventDefault();
        toggleTool("orbit");
      } else if (k === "p" || k === "P") {
        e.preventDefault();
        void handleDownloadPdf();
      } else if (k === "ArrowLeft" || k === "ArrowRight") {
        // epoch stepping, but never while a 3D view or chart has focus
        if (target && target !== document.body && target.tagName !== "BUTTON") return;
        const i = EPOCHS.indexOf(epoch);
        const next = EPOCHS[Math.max(0, Math.min(EPOCHS.length - 1, i + (k === "ArrowRight" ? 1 : -1)))];
        if (next !== epoch) {
          e.preventDefault();
          void handleEpochChange(next);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleDownloadPdf, handleEpochChange, epoch, toggleTool]);

  const executeUiActions = useCallback(
    async (actions: UiAction[]) => {
      for (const act of actions) {
        const p = act.params ?? {};
        switch (act.type) {
          case "FLY_TO": {
            const q = typeof p.target_id === "string" ? p.target_id : typeof p.q === "string" ? p.q : null;
            const ra = typeof p.ra === "number" ? p.ra : undefined;
            const dec = typeof p.dec === "number" ? p.dec : undefined;
            if (q) {
              try {
                const [epRes, refRes] = await Promise.all([searchCatalog({ q, epoch }), searchCatalog({ q })]);
                const hit = epRes.data.results[0];
                const refHit = refRes.data.results[0];
                if (hit) {
                  selectObject(hit, { ra: hit.ra, dec: hit.dec }, { ra: refHit?.ra ?? hit.ra, dec: refHit?.dec ?? hit.dec });
                  break;
                }
              } catch {
                // fall back to coordinates below
              }
            }
            if (ra !== undefined && dec !== undefined) flyToCoords(ra, dec);
            break;
          }
          case "SET_EPOCH": {
            const ep = p.epoch as Epoch | undefined;
            if (ep && EPOCHS.includes(ep)) await handleEpochChange(ep);
            break;
          }
          case "TOGGLE_DIFF":
            if (p.open === false) setTool((cur) => (cur === "diff" ? null : cur));
            else setTool("diff");
            break;
          case "RUN_SHIFT_STACK":
          case "RUN_BLIND_SEARCH":
            setTool("stack");
            break;
          case "OPEN_SPECTRUM":
            setTool("spectrum");
            break;
          case "OPEN_CROSSMATCH":
            setTool("crossmatch");
            break;
          case "OPEN_3D_ORBIT":
            setTool("orbit");
            break;
          case "OPEN_JWST":
            setPipOpen(true);
            break;
          case "SET_LANG":
            if (p.lang === "tr" || p.lang === "en") setLang(p.lang as Lang);
            break;
          case "GENERATE_PDF":
            await handleDownloadPdf();
            break;
          case "START_DEMO_TOUR":
            await applyTourStep(0);
            break;
          default:
            break;
        }
      }
    },
    [epoch, setLang, handleDownloadPdf, applyTourStep, handleEpochChange, selectObject, flyToCoords]
  );

  const renderTool = (id: ToolId) => {
    switch (id) {
      case "diff":
        return (
          <DifferencePanel
            key={diffEpochs.join("-")}
            coords={refCoords}
            selectedObject={selectedObject}
            defaultEpochs={diffEpochs}
          />
        );
      case "spectrum":
        return <SpectrumPanel coords={coords} epoch={epoch} selectedObject={selectedObject} />;
      case "classify":
        return <ClassificationCard coords={refCoords} selectedObject={selectedObject} />;
      case "crossmatch":
        return (
          <CrossmatchSedPanel
            coords={refCoords}
            selectedObject={selectedObject}
            onOpenPip={(overlaps) => {
              setPipOverlaps(overlaps);
              setPipOpen(true);
            }}
          />
        );
      case "stack":
        return <ShiftStackPanel coords={refCoords} selectedObject={selectedObject} onAstrometryReady={setAstrometry} />;
      case "orbit":
        return <SolarSystem3DPanel coords={refCoords} selectedObject={selectedObject} astrometry={astrometry} />;
      case "candidates":
        return (
          <CandidatePoolPanel
            coords={refCoords}
            selectedObject={selectedObject}
            onInspectCoords={(ra, dec) => flyToCoords(ra, dec)}
          />
        );
      default:
        return null;
    }
  };

  // Keep the observation window centred in the space the inspector leaves free.
  const stageInset = tool ? (wide ? "md:pr-[min(1180px,calc(100vw-40px))]" : "md:pr-[min(640px,calc(100vw-40px))]") : "md:pr-[76px]";

  return (
    <div className="relative min-h-dvh overflow-x-hidden">
      <Starfield />

      <TopBar
        dataMode={dataMode}
        health={health}
        epoch={epoch}
        selectedObject={selectedObject}
        onSelectObject={selectObject}
        onFlyTo={flyToCoords}
        onStartTour={() => void applyTourStep(0)}
        onOpenCmd={() => setCmdOpen(true)}
        onOpenShortcuts={() => setShortcutsOpen(true)}
        onDownloadPdf={() => void handleDownloadPdf()}
        pdfBusy={pdfBusy}
      />

      <main className="relative flex min-h-dvh flex-col pb-[76px] pt-[118px] md:block md:pb-0 md:pt-0">
        {/* stage */}
        <div className={`order-1 flex items-center justify-center px-4 transition-[padding] duration-300 md:fixed md:inset-0 md:pl-6 md:pt-[84px] ${tourActive ? "md:pb-[340px]" : "md:pb-[260px]"} ${stageInset}`}>
          <SkyStage coords={coords} epoch={epoch} fit={tool ? (tourActive ? "tour" : "compact") : "full"} />
        </div>

        {/* object readout or tour narration — bottom left, always the same place */}
        <div
          className={`z-10 order-3 px-4 pt-6 md:fixed md:bottom-6 md:left-6 md:w-[min(440px,calc(100vw-140px))] md:px-0 md:pt-0 ${
            tool ? (wide ? "md:hidden" : "md:max-lg:hidden") : ""
          }`}
        >
          {tourActive ? (
            <TourCaption
              step={tourStep}
              onStep={(s) => void applyTourStep(s)}
              onClose={() => setTourActive(false)}
              onDownloadPdf={() => void handleDownloadPdf()}
            />
          ) : (
            <TargetCard selectedObject={selectedObject} coords={coords} compact={Boolean(tool)} />
          )}
        </div>

        {/* epoch strip — bottom centre */}
        <div
          className={`order-2 flex justify-center px-4 pt-6 transition-[padding] duration-300 md:pointer-events-none md:fixed md:inset-x-0 md:bottom-6 md:px-6 md:pt-0 ${
            tool ? (wide ? "md:hidden" : "md:pl-[480px] md:pr-[660px] max-xl:md:hidden") : "md:pl-[480px] md:pr-[96px] max-lg:md:pl-6 max-lg:md:justify-end"
          }`}
        >
          <div className="w-full max-w-[420px] md:pointer-events-auto">
            <EpochScrubber epoch={epoch} onChange={(ep) => void handleEpochChange(ep)} coverage={epochCoverage} />
          </div>
        </div>
      </main>

      <ToolRail active={tool} onSelect={toggleTool} />

      {tool && (
        <Inspector tool={tool} wide={wide} onToggleWide={() => setWide((w) => !w)} onClose={closeTool}>
          {renderTool(tool)}
        </Inspector>
      )}

      <JwstPipWindow open={pipOpen} onClose={() => setPipOpen(false)} overlaps={pipOverlaps} coords={coords} />

      <AstroLlmModal
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        context={{ ra: coords.ra, dec: coords.dec, epoch, target_id: selectedObject?.id }}
        onExecuteActions={executeUiActions}
      />

      <ShortcutsModal open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />

      <Onboarding onStartTour={() => void applyTourStep(0)} />
    </div>
  );
}
