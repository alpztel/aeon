"use client";

import React from "react";
import { useI18n } from "@/i18n/context";
import { EPOCHS, EPOCH_DECIMAL, type Epoch } from "@/lib/api";

export type EpochCoverage = Partial<Record<Epoch, "real" | "model">>;

interface EpochScrubberProps {
  epoch: Epoch;
  onChange: (epoch: Epoch) => void;
  /** Which epochs the backend serves from real SPHEREx frames for the current target. */
  coverage?: EpochCoverage;
}

/** Survey-epoch strip: a ruler with four stops. ← / → also step through it (handled by the page). */
export function EpochScrubber({ epoch, onChange, coverage }: EpochScrubberProps) {
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
                aria-label={`${dict.shell.epoch} ${ep}${
                  coverage?.[ep] === "real" ? ` · ${dict.shell.realData}` : coverage?.[ep] === "model" ? ` · ${dict.shell.modelData}` : ""
                }`}
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
                <span className={`aeon-mono flex items-center gap-1 text-[11px] ${active ? "text-foreground" : "text-muted group-hover:text-foreground"}`}>
                  {ep.slice(5)}
                  {coverage?.[ep] && (
                    <span
                      aria-hidden="true"
                      className={`inline-block h-1.5 w-1.5 rounded-full ${
                        coverage[ep] === "real" ? "bg-ice" : "border border-white/40"
                      }`}
                    />
                  )}
                </span>
              </button>
            );
          })}
        </div>
      </div>
      {coverage && Object.keys(coverage).length > 0 && (
        <p className="aeon-label mt-2 flex items-center justify-center gap-3 normal-case">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-ice" />
            {dict.shell.coverageLegendReal}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full border border-white/40" />
            {dict.shell.coverageLegendModel}
          </span>
        </p>
      )}
    </div>
  );
}
