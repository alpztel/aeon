"use client";

import React from "react";
import { ArrowLeft, ArrowRight, FileDown, X } from "lucide-react";
import { useI18n } from "@/i18n/context";

interface TourCaptionProps {
  step: number;
  onStep: (step: number) => void;
  onClose: () => void;
  onDownloadPdf: () => void;
}

/** Guided tour told as a caption over the sky: kicker, title, italic narration, step dots. */
export function TourCaption({ step, onStep, onClose, onDownloadPdf }: TourCaptionProps) {
  const { dict } = useI18n();
  const steps = dict.tour.steps;
  const current = steps[step] ?? steps[0];
  // "Step 1 / 3 — WISE 0855…" → keep the object part; the step counter is shown separately.
  const title = current.title.includes(" — ") ? current.title.split(" — ").slice(1).join(" — ") : current.title;
  const last = step >= steps.length - 1;

  return (
    <section
      key={step}
      aria-live="polite"
      aria-label={dict.shell.tour}
      className="aeon-panel aeon-fade-up w-full max-w-[600px] px-5 pb-4 pt-4 shadow-2xl"
    >
      <div className="flex items-center justify-between gap-3">
        <p className="aeon-label text-signal">
          {dict.shell.tour} · {dict.shell.step} {step + 1}/{steps.length}
        </p>
        <button type="button" onClick={onClose} aria-label={dict.tour.finish} title={dict.tour.finish} className="aeon-icon-btn h-8 w-8">
          <X className="h-4 w-4" />
        </button>
      </div>
      <h2 className="aeon-display mt-1 text-lg text-foreground md:text-xl">{title}</h2>
      <p className="aeon-caption mt-2 text-[17px] leading-snug text-foreground/85 md:text-[19px]">{current.narration}</p>

      <div className="mt-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5" role="tablist" aria-label={dict.shell.tour}>
          {steps.map((s, i) => (
            <button
              key={s.title}
              type="button"
              role="tab"
              aria-selected={i === step}
              aria-label={`${dict.shell.step} ${i + 1}`}
              onClick={() => onStep(i)}
              className={`h-1.5 rounded-full transition-all ${i === step ? "w-6 bg-signal" : "w-1.5 bg-white/30 hover:bg-white/60"}`}
            />
          ))}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" disabled={step === 0} onClick={() => onStep(step - 1)} className="aeon-btn aeon-btn-ghost">
            <ArrowLeft className="h-3.5 w-3.5" />
            {dict.tour.prev}
          </button>
          {last ? (
            <button type="button" onClick={onDownloadPdf} className="aeon-btn aeon-btn-primary">
              <FileDown className="h-3.5 w-3.5" />
              {dict.tour.downloadPdf}
            </button>
          ) : (
            <button type="button" onClick={() => onStep(step + 1)} className="aeon-btn aeon-btn-primary">
              {dict.tour.next}
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
