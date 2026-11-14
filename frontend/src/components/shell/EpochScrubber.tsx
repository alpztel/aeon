"use client";

import React from "react";
import { useI18n } from "@/i18n/context";
import { EPOCHS, EPOCH_DECIMAL, type Epoch } from "@/lib/api";

interface EpochScrubberProps {
  epoch: Epoch;
  onChange: (epoch: Epoch) => void;
}

/** Survey-epoch strip: a ruler with four stops. ← / → also step through it (handled by the page). */
export function EpochScrubber({ epoch, onChange }: EpochScrubberProps) {
  const { dict } = useI18n();
  const idx = Math.max(0, EPOCHS.indexOf(epoch));
  return (
    <div className="w-full max-w-[420px]" role="group" aria-label={dict.shell.epoch}>
      <div className="mb-2 flex items-baseline justify-between">
        <span className="aeon-label">{dict.shell.epoch}</span>
        <span className="aeon-mono text-[11px] text-muted">
          {epoch} · {EPOCH_DECIMAL[epoch].toFixed(3)}
        </span>
      </div>
      <div className="relative">
        <div className="absolute inset-x-[12.5%] top-[11px] h-px bg-white/15" aria-hidden="true" />
        <div
          className="absolute left-[12.5%] top-[11px] h-px bg-signal transition-all duration-300"
          style={{ width: `${(idx / (EPOCHS.length - 1)) * 75}%` }}
          aria-hidden="true"
        />
        <div className="relative grid grid-cols-4">
          {EPOCHS.map((ep, i) => {
            const active = ep === epoch;
            return (
              <button
                key={ep}
                type="button"
                onClick={() => onChange(ep)}
                aria-pressed={active}
                aria-label={`${dict.shell.epoch} ${ep}`}
                className="group flex flex-col items-center gap-2 py-0.5 focus-visible:outline-offset-4"
              >
                <span
                  className={`block rounded-full transition-all ${
                    active
                      ? "h-[22px] w-[22px] border-2 border-signal bg-[#140803]"
                      : i <= idx
                        ? "mt-[7px] h-2 w-2 bg-signal"
                        : "mt-[7px] h-2 w-2 bg-white/35 group-hover:bg-white/70"
                  }`}
                />
                <span className={`aeon-mono text-[11px] ${active ? "text-foreground" : "text-muted group-hover:text-foreground"}`}>
                  {ep.slice(5)}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
