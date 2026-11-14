"use client";

import React from "react";
import { useI18n } from "@/i18n/context";
import { TOOLS, type ToolId } from "./tools";

interface ToolRailProps {
  active: ToolId | null;
  onSelect: (id: ToolId) => void;
}

/** Right-hand tool rail (desktop) / bottom tab bar (mobile). One tool open at a time. */
export function ToolRail({ active, onSelect }: ToolRailProps) {
  const { dict } = useI18n();
  return (
    <nav
      aria-label={dict.shell.tools}
      className="aeon-glass fixed inset-x-0 bottom-0 z-40 flex justify-around gap-1 border-x-0 border-b-0 px-2 py-1.5 md:inset-x-auto md:bottom-auto md:right-4 md:top-1/2 md:-translate-y-1/2 md:flex-col md:justify-start md:rounded-full md:border md:p-1.5"
    >
      {TOOLS.map((t, i) => {
        const Icon = t.icon;
        const isActive = active === t.id;
        const name = dict.shell.toolNames[t.id];
        return (
          <div key={t.id} className="group relative">
            <button
              type="button"
              onClick={() => onSelect(t.id)}
              aria-pressed={isActive}
              aria-label={t.key ? `${name} (${t.key})` : name}
              className={`relative flex h-11 w-11 items-center justify-center rounded-full transition ${
                isActive ? "bg-signal text-[#140803]" : "text-muted hover:bg-white/[0.08] hover:text-foreground"
              }`}
            >
              <Icon className="h-[18px] w-[18px]" strokeWidth={1.75} />
              <span className="sr-only">{i + 1}</span>
            </button>
            {/* tooltip (desktop only) */}
            <span
              role="tooltip"
              className={`aeon-panel pointer-events-none absolute right-14 top-1/2 hidden -translate-y-1/2 whitespace-nowrap px-3 py-1.5 text-xs text-foreground opacity-0 shadow-xl transition-opacity group-hover:opacity-100 ${isActive ? "" : "md:block"}`}
            >
              {name}
              {t.key && <kbd className="aeon-kbd ml-2">{t.key}</kbd>}
            </span>
          </div>
        );
      })}
    </nav>
  );
}
