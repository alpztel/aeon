"use client";

import React from "react";
import { Telescope, X } from "lucide-react";
import { useI18n } from "@/i18n/context";
import type { CrossmatchResult } from "@/lib/api";

interface JwstPipWindowProps {
  open: boolean;
  onClose: () => void;
  overlaps: NonNullable<CrossmatchResult["mast_overlap"]>;
  coords: { ra: number; dec: number };
}

export function JwstPipWindow({
  open,
  onClose,
  overlaps,
  coords,
}: JwstPipWindowProps) {
  const { dict } = useI18n();

  if (!open) return null;

  return (
    <aside
      aria-label={dict.missions.pipTitle}
      className="aeon-panel fixed bottom-5 right-5 z-40 w-[340px] max-w-[calc(100vw-2.5rem)] rounded-2xl p-4 shadow-2xl"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Telescope className="h-4 w-4 text-amber-400" />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-white">
            {dict.missions.pipTitle}
          </h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1 text-slate-400 transition hover:bg-white/10 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <p className="aeon-mono mb-3 text-[11px] text-slate-400">
        ICRS {coords.ra.toFixed(4)}°, {coords.dec >= 0 ? "+" : ""}
        {coords.dec.toFixed(4)}°
      </p>

      {overlaps.length === 0 ? (
        <div className="rounded-xl border border-white/10 bg-black/40 p-3 text-xs text-slate-400">
          {dict.missions.pipNoOverlap}
        </div>
      ) : (
        <div className="space-y-2.5">
          {overlaps.map((item, idx) => (
            <div
              key={idx}
              className="rounded-xl border border-amber-400/30 bg-black/50 p-3 text-xs"
            >
              <div className="mb-1.5 flex items-center justify-between">
                <span className="rounded bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-300">
                  {item.mission ?? "MAST"}
                </span>
                <span className="aeon-mono text-[11px] text-cyan-200">
                  {item.instrument}
                </span>
              </div>

              <dl className="space-y-1 text-[11px]">
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-400">{dict.missions.obsId}:</dt>
                  <dd className="aeon-mono truncate text-slate-200">{item.obs_id}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-400">{dict.missions.filter}:</dt>
                  <dd className="aeon-mono text-amber-200">{item.filter}</dd>
                </div>
              </dl>

              {typeof (item as { preview_url?: unknown }).preview_url === "string" &&
              (item as { preview_url?: string }).preview_url ? (
                <div className="mt-2.5 overflow-hidden rounded-lg border border-white/10 bg-black">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={(item as { preview_url: string }).preview_url}
                    alt={`${item.mission ?? "MAST"} ${item.obs_id ?? ""}`}
                    className="h-28 w-full object-cover"
                  />
                </div>
              ) : (
                <div className="mt-2.5 flex h-16 items-center justify-center rounded-lg border border-white/10 bg-black/40 px-3 text-center text-[11px] text-slate-400">
                  {dict.missions.noPreview}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
