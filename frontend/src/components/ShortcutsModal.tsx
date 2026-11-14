"use client";

import React, { useEffect } from "react";
import { X } from "lucide-react";
import { useI18n } from "@/i18n/context";

interface ShortcutsModalProps {
  open: boolean;
  onClose: () => void;
}

export function ShortcutsModal({ open, onClose }: ShortcutsModalProps) {
  const { dict } = useI18n();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const rows = [
    { key: "D", label: dict.shortcuts.items.d },
    { key: "S", label: dict.shortcuts.items.s },
    { key: "3", label: dict.shortcuts.items["3"] },
    { key: "P", label: dict.shortcuts.items.p },
    { key: "Cmd / Ctrl + K", label: dict.shortcuts.items.k },
    { key: "?", label: dict.shortcuts.items.q },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={dict.shortcuts.title}
      onClick={onClose}
    >
      <div
        className="aeon-panel w-full max-w-md rounded-2xl p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
            {dict.shortcuts.title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={dict.shortcuts.close}
            className="rounded-lg p-1 text-slate-400 transition hover:bg-white/10 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <ul className="space-y-2.5">
          {rows.map((row) => (
            <li
              key={row.key}
              className="flex items-center justify-between gap-4 rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2 text-xs"
            >
              <span className="text-slate-300">{row.label}</span>
              <kbd className="aeon-mono shrink-0 rounded-md border border-white/15 bg-black/50 px-2 py-0.5 text-[11px] text-cyan-300">
                {row.key}
              </kbd>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
