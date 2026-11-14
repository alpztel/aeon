"use client";

import React from "react";
import { FileDown, HelpCircle, Loader2, Play, Sparkles } from "lucide-react";
import { useI18n } from "@/i18n/context";
import type { CatalogObject, DataMode, Epoch } from "@/lib/api";
import { AlertsMenu } from "./AlertsMenu";
import { SearchBox } from "./SearchBox";

type Coords = { ra: number; dec: number };

interface TopBarProps {
  dataMode: DataMode | "checking";
  epoch: Epoch;
  selectedObject: CatalogObject | null;
  onSelectObject: (obj: CatalogObject | null, coords: Coords, refCoords?: Coords) => void;
  onFlyTo: (ra: number, dec: number) => void;
  onStartTour: () => void;
  onOpenCmd: () => void;
  onOpenShortcuts: () => void;
  onDownloadPdf: () => void;
  pdfBusy: boolean;
}

const MODE_DOT: Record<DataMode | "checking", string> = {
  fits_archive: "bg-[var(--aeon-ok)]",
  physical_model: "bg-ice",
  offline_cache: "bg-[var(--aeon-warn)]",
  checking: "bg-white/40 animate-pulse",
};

export function TopBar(props: TopBarProps) {
  const { lang, setLang, dict } = useI18n();
  const { dataMode } = props;

  return (
    <header className="pointer-events-none fixed inset-x-0 top-0 z-40 bg-gradient-to-b from-black/70 via-black/30 to-transparent">
      <div className="pointer-events-auto flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-3 md:flex-nowrap md:px-5">
        {/* brand + tour */}
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={props.onStartTour}
            aria-label={dict.shell.tour}
            title={dict.shell.tour}
            className="flex h-9 w-9 items-center justify-center rounded-full border border-white/70 text-foreground transition hover:border-signal hover:text-signal"
          >
            <Play className="ml-0.5 h-3.5 w-3.5 fill-current" />
          </button>
          <div className="leading-none">
            <span className="block text-[15px] font-semibold tracking-[0.42em] text-foreground">AEON</span>
            <span className="aeon-label mt-1 hidden text-[9px] lg:block">{dict.app.subtitle}</span>
          </div>
        </div>

        {/* actions (right on desktop, top-right on mobile) */}
        <div className="order-2 ml-auto flex shrink-0 items-center gap-0.5 md:order-3">
          <span
            className="mr-1.5 hidden items-center gap-1.5 text-[11px] text-muted lg:inline-flex"
            title={dict.header.dataMode[dataMode]}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${MODE_DOT[dataMode]}`} />
            {dict.header.dataMode[dataMode]}
          </span>
          <AlertsMenu onFlyTo={props.onFlyTo} />
          <button
            type="button"
            onClick={props.onDownloadPdf}
            disabled={props.pdfBusy}
            aria-label={dict.header.pdfReport}
            title={dict.header.pdfReport}
            className="aeon-icon-btn disabled:opacity-40"
          >
            {props.pdfBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
          </button>
          <div role="group" aria-label="Language" className="mx-1 flex items-center rounded-full border border-line p-0.5 text-[11px]">
            {(["tr", "en"] as const).map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => setLang(l)}
                aria-pressed={lang === l}
                className={`rounded-full px-2 py-0.5 font-medium uppercase transition ${
                  lang === l ? "bg-white/12 text-foreground" : "text-muted hover:text-foreground"
                }`}
              >
                {l}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={props.onOpenShortcuts}
            aria-label={dict.header.shortcuts}
            title={`${dict.header.shortcuts} (?)`}
            className="aeon-icon-btn"
          >
            <HelpCircle className="h-4 w-4" />
          </button>
          <button type="button" onClick={props.onOpenCmd} className="aeon-btn aeon-btn-line ml-1 hidden sm:inline-flex">
            <Sparkles className="h-3.5 w-3.5 text-signal" />
            {dict.header.cmdPalette}
            <kbd className="aeon-kbd">⌘K</kbd>
          </button>
          <button
            type="button"
            onClick={props.onOpenCmd}
            aria-label={dict.header.cmdPalette}
            className="aeon-icon-btn sm:hidden"
          >
            <Sparkles className="h-4 w-4 text-signal" />
          </button>
        </div>

        {/* search: full width row on mobile, centred on desktop */}
        <div className="order-3 w-full md:order-2 md:mx-auto md:w-[min(520px,40vw)]">
          <SearchBox epoch={props.epoch} selectedObject={props.selectedObject} onSelectObject={props.onSelectObject} />
        </div>
      </div>
    </header>
  );
}
