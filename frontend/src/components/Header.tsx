"use client";

import React from "react";
import { Compass, FileDown, HelpCircle, Play, Radio, Sparkles } from "lucide-react";
import { useI18n } from "@/i18n/context";
import type { DataMode } from "@/lib/api";

interface HeaderProps {
  dataMode: DataMode | "checking";
  onOpenShortcuts: () => void;
  onOpenCmdPalette?: () => void;
  onStartDemoTour?: () => void;
  onDownloadPdf?: () => void;
  pdfBusy?: boolean;
}

export function Header({
  dataMode,
  onOpenShortcuts,
  onOpenCmdPalette,
  onStartDemoTour,
  onDownloadPdf,
  pdfBusy,
}: HeaderProps) {
  const { lang, setLang, dict } = useI18n();

  const modeBadgeClass =
    dataMode === "fits_archive"
      ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-300"
      : dataMode === "physical_model"
        ? "border-cyan-400/30 bg-cyan-500/10 text-cyan-300"
        : dataMode === "offline_cache"
          ? "border-amber-400/30 bg-amber-500/10 text-amber-300"
          : "border-white/15 bg-white/5 text-slate-300";

  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-[#030712]/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-amber-400/30 bg-amber-500/10 text-amber-400 shadow-[0_0_20px_rgba(245,158,11,0.18)]">
            <Compass className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold tracking-wider text-white">
                {dict.app.name}
              </span>
              <span className="hidden rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-medium uppercase tracking-widest text-slate-300 sm:inline-block">
                {dict.app.challenge}
              </span>
            </div>
            <p className="text-xs text-slate-400">{dict.app.subtitle}</p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          {/* Data Mode Badge */}
          <div
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${modeBadgeClass}`}
            title={dict.header.dataMode[dataMode]}
          >
            <Radio className="h-3.5 w-3.5" />
            <span>{dict.header.dataMode[dataMode]}</span>
          </div>

          {/* Demo Tour Button */}
          <button
            type="button"
            onClick={onStartDemoTour}
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/35 bg-amber-500/15 px-3 py-1.5 text-xs font-medium text-amber-200 transition hover:bg-amber-500/25 focus-visible:outline-2 focus-visible:outline-amber-400"
          >
            <Play className="h-3.5 w-3.5 fill-current" />
            <span>{dict.header.demoTour}</span>
          </button>

          {/* PDF Discovery Report Button */}
          <button
            type="button"
            onClick={onDownloadPdf}
            disabled={pdfBusy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-400/35 bg-cyan-500/15 px-2.5 py-1.5 text-xs font-medium text-cyan-200 transition hover:bg-cyan-500/25 disabled:opacity-50"
            title={dict.shortcuts.items.p}
          >
            <FileDown className="h-3.5 w-3.5 text-cyan-300" />
            <span>{dict.header.pdfReport}</span>
          </button>

          {/* Cmd+K Button */}
          <button
            type="button"
            onClick={onOpenCmdPalette}
            className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/30 bg-violet-500/15 px-2.5 py-1.5 text-xs font-medium text-violet-200 transition hover:bg-violet-500/25"
            title={dict.shortcuts.items.k}
          >
            <Sparkles className="h-3.5 w-3.5 text-violet-300" />
            <span>{dict.header.cmdPalette}</span>
            <kbd className="aeon-mono rounded border border-white/15 bg-black/40 px-1 text-[10px] text-slate-300">
              ⌘K
            </kbd>
          </button>

          {/* TR | EN Toggle */}
          <div
            role="group"
            aria-label="Language"
            className="inline-flex items-center rounded-lg border border-white/10 bg-white/5 p-0.5 text-xs"
          >
            <button
              type="button"
              onClick={() => setLang("tr")}
              className={`rounded-md px-2 py-1 font-medium transition ${
                lang === "tr"
                  ? "bg-cyan-500/20 text-cyan-200"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              TR
            </button>
            <button
              type="button"
              onClick={() => setLang("en")}
              className={`rounded-md px-2 py-1 font-medium transition ${
                lang === "en"
                  ? "bg-cyan-500/20 text-cyan-200"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              EN
            </button>
          </div>

          {/* Shortcuts Help */}
          <button
            type="button"
            onClick={onOpenShortcuts}
            aria-label={dict.header.shortcuts}
            title={`${dict.header.shortcuts} (?)`}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-300 transition hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-cyan-400"
          >
            <HelpCircle className="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
