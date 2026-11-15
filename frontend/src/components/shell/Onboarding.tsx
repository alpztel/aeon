"use client";

import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ArrowRight, Play } from "lucide-react";
import { useI18n } from "@/i18n/context";

const KEY = "aeon_onboarded_v1";
const EVENT = "aeon-onboarding-change";

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}
function readSeen(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return true; // storage blocked: never trap the visitor behind the dialog
  }
}
function markSeen() {
  try {
    window.localStorage.setItem(KEY, "1");
  } catch {
    // ignore
  }
  window.dispatchEvent(new Event(EVENT));
}

interface OnboardingProps {
  onStartTour: () => void;
}

/** First-visit welcome: two clear choices, like a planetarium lobby. Server render = hidden. */
export function Onboarding({ onStartTour }: OnboardingProps) {
  const { dict } = useI18n();
  const seen = useSyncExternalStore(subscribe, readSeen, () => true);
  const [dismissed, setDismissed] = useState(false);
  const [dontShow, setDontShow] = useState(true);
  const primaryRef = useRef<HTMLButtonElement | null>(null);
  const open = !seen && !dismissed;

  useEffect(() => {
    if (open) primaryRef.current?.focus();
  }, [open]);

  if (!open) return null;

  const close = () => {
    if (dontShow) markSeen();
    setDismissed(true);
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/55 p-4 backdrop-blur-[2px]"
      onKeyDown={(e) => {
        if (e.key === "Escape") close();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="aeon-welcome-title"
        className="aeon-panel aeon-fade-up w-full max-w-[620px] p-7 shadow-2xl md:p-9"
      >
        <div className="flex items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/aeon-mark.svg" alt="" aria-hidden="true" className="h-9 w-9 shrink-0 select-none" />
          <p className="aeon-label text-signal">{dict.shell.welcomeKicker}</p>
        </div>
        <h2 id="aeon-welcome-title" className="aeon-display mt-3 text-[32px] text-foreground md:text-[44px]">
          {dict.shell.welcomeTitle}
        </h2>
        <p className="mt-4 text-[14px] leading-relaxed text-muted">{dict.shell.welcomeBody}</p>

        <ol className="mt-6 space-y-2.5 border-t border-line pt-5">
          {dict.shell.howTo.map((line, i) => (
            <li key={line} className="flex gap-3 text-[13px] text-foreground/90">
              <span className="aeon-mono w-6 shrink-0 text-signal">{String(i + 1).padStart(2, "0")}</span>
              <span>{line}</span>
            </li>
          ))}
        </ol>

        <div className="mt-7 flex flex-wrap items-center gap-3">
          <button
            ref={primaryRef}
            type="button"
            onClick={() => {
              close();
              onStartTour();
            }}
            className="aeon-btn aeon-btn-primary h-10 px-5"
          >
            <Play className="h-3.5 w-3.5 fill-current" />
            {dict.shell.startTour}
          </button>
          <button type="button" onClick={close} className="aeon-btn aeon-btn-line h-10 px-5">
            {dict.shell.explore}
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
          <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted">
            <input
              type="checkbox"
              checked={dontShow}
              onChange={(e) => setDontShow(e.target.checked)}
              className="h-3.5 w-3.5 accent-[var(--aeon-signal)]"
            />
            {dict.shell.dontShow}
          </label>
        </div>
      </div>
    </div>
  );
}
