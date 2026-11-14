"use client";

import React, { useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { ShortcutsModal } from "@/components/ShortcutsModal";
import { SkyMapPanel } from "@/components/SkyMapPanel";
import {
  getHealth,
  searchCatalog,
  type CatalogObject,
  type DataMode,
  type Epoch,
} from "@/lib/api";

export default function HomePage() {
  const [dataMode, setDataMode] = useState<DataMode | "checking">("checking");
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
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
      .catch(() => {
        // Initial catalog load can fail if API & cache are both absent; SkyMapPanel handles fallback
      });
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
        target?.isContentEditable;
      if (isInput) return;

      if (e.key === "?") {
        e.preventDefault();
        setShortcutsOpen((prev) => !prev);
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
      </main>
      <ShortcutsModal
        open={shortcutsOpen}
        onClose={() => setShortcutsOpen(false)}
      />
    </div>
  );
}
