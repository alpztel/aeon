"use client";

import React from "react";
import { ChevronLeft, ChevronRight, FileDown, Sparkles, X } from "lucide-react";
import { useI18n } from "@/i18n/context";

interface DemoTourBarProps {
  active: boolean;
  step: number;
  onSelectStep: (step: number) => void;
  onClose: () => void;
  onDownloadPdf: () => void;
}

export function DemoTourBar({
  active,
  step,
  onSelectStep,
  onClose,
  onDownloadPdf,
}: DemoTourBarProps) {
  const { dict } = useI18n();

  if (!active) return null;

  const steps = dict.tour.steps;
  const current = steps[step] ?? steps[0];

  return (
    <div className="border-b border-amber-400/35 bg-amber-500/10 px-4 py-3 backdrop-blur-xl sm:px-6">
      <div className="mx-auto flex max-w-[1600px] flex-col justify-between gap-3 lg:flex-row lg:items-center">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/50 bg-amber-500/20 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-200">
              <Sparkles className="h-3 w-3" />
              {dict.tour.badge}
            </span>
            <h3 className="text-xs font-semibold text-white">{current.title}</h3>
          </div>
          <p className="max-w-4xl text-xs leading-relaxed text-amber-100/90">
            {current.narration}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs">
          <button
            type="button"
            disabled={step === 0}
            onClick={() => onSelectStep(Math.max(0, step - 1))}
            className="inline-flex items-center gap-1 rounded-lg border border-white/15 bg-black/40 px-2.5 py-1.5 text-slate-200 transition hover:bg-black/60 disabled:opacity-40"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            <span>{dict.tour.prev}</span>
          </button>

          {step < steps.length - 1 ? (
            <button
              type="button"
              onClick={() => onSelectStep(step + 1)}
              className="inline-flex items-center gap-1 rounded-lg border border-amber-400/50 bg-amber-500/25 px-3 py-1.5 font-semibold text-amber-100 transition hover:bg-amber-500/35"
            >
              <span>{dict.tour.next}</span>
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onDownloadPdf}
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-400/50 bg-emerald-500/25 px-3 py-1.5 font-semibold text-emerald-100 transition hover:bg-emerald-500/35"
            >
              <FileDown className="h-3.5 w-3.5" />
              <span>{dict.tour.downloadPdf}</span>
            </button>
          )}

          <button
            type="button"
            onClick={onClose}
            aria-label={dict.tour.finish}
            className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-slate-300 transition hover:bg-white/10"
          >
            <X className="h-3.5 w-3.5" />
            <span>{dict.tour.finish}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
