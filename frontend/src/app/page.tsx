"use client";

import React, { useEffect, useState } from "react";
import { Layers, Radar } from "lucide-react";
import { DifferencePanel } from "@/components/DifferencePanel";
import { Header } from "@/components/Header";
import { ShiftStackPanel } from "@/components/ShiftStackPanel";
import { ShortcutsModal } from "@/components/ShortcutsModal";
import { SkyMapPanel } from "@/components/SkyMapPanel";
import { SpectrumPanel } from "@/components/SpectrumPanel";
import { useI18n } from "@/i18n/context";
import {
  getHealth,
  searchCatalog,
  type CatalogObject,
  type DataMode,
  type Epoch,
} from "@/lib/api";

export default function HomePage() {
  const { dict } = useI18n();
  const [dataMode, setDataMode] = useState<DataMode | "checking">("checking");
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [diffOpen, setDiffOpen] = useState(true);
  const [stackOpen, setStackOpen] = useState(true);
  const [epoch, setEpoch] = useState<Epoch>("2026-Q1");
  const [coords, setCoords] = useState<{ ra: number; dec: number }>({
    ra: 133.79513,
    dec: -7.24514,
  });
  const [selectedObject, setSelectedObject] = useState<CatalogObject | null>(null);

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
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="flex min-h-screen flex-col">
      <Header
        dataMode={dataMode}
        onOpenShortcuts={() => setShortcutsOpen(true)}
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
        </div>

        {diffOpen && (
          <DifferencePanel coords={coords} selectedObject={selectedObject} />
        )}

        <SpectrumPanel
          coords={coords}
          epoch={epoch}
          selectedObject={selectedObject}
        />

        {stackOpen && (
          <ShiftStackPanel coords={coords} selectedObject={selectedObject} />
        )}
      </main>
      <ShortcutsModal
        open={shortcutsOpen}
        onClose={() => setShortcutsOpen(false)}
      />
    </div>
  );
}
