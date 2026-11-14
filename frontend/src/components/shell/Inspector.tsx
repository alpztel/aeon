"use client";

import React, { useEffect } from "react";
import { Maximize2, Minimize2, X } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { TOOLS, type ToolId } from "./tools";

interface InspectorProps {
  tool: ToolId;
  wide: boolean;
  onToggleWide: () => void;
  onClose: () => void;
  children: React.ReactNode;
}

/**
 * The single detail panel. Modules render inside an @container, so their layouts respond to the
 * panel's width (narrow by default, wide on demand) rather than to the window.
 */
export function Inspector({ tool, wide, onToggleWide, onClose, children }: InspectorProps) {
  const { dict } = useI18n();
  const index = TOOLS.findIndex((t) => t.id === tool);
  const def = TOOLS[index];
  const Icon = def.icon;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        const t = e.target as HTMLElement | null;
        if (t?.closest("[role=dialog]")) return;
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      key={tool}
      aria-label={dict.shell.toolNames[tool]}
      className={`aeon-panel aeon-slide-in fixed inset-x-0 bottom-[60px] z-30 flex h-[74dvh] flex-col rounded-b-none shadow-2xl md:inset-x-auto md:bottom-4 md:right-[76px] md:top-[72px] md:h-auto md:rounded-b-[14px] ${
        wide ? "md:w-[min(1100px,calc(100vw-120px))]" : "md:w-[min(560px,calc(100vw-120px))]"
      }`}
    >
      <header className="flex items-start gap-3 border-b border-line px-5 py-4">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-line text-signal">
          <Icon className="h-4 w-4" strokeWidth={1.75} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="aeon-label">
            {String(index + 1).padStart(2, "0")} / {String(TOOLS.length).padStart(2, "0")}
          </p>
          <h2 className="aeon-display mt-1 text-xl text-foreground">{dict.shell.toolNames[tool]}</h2>
          <p className="aeon-caption mt-1 text-[15px] text-muted">{dict.shell.toolHints[tool]}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onToggleWide}
            aria-label={wide ? dict.shell.collapse : dict.shell.expand}
            title={wide ? dict.shell.collapse : dict.shell.expand}
            className="aeon-icon-btn hidden md:inline-flex"
          >
            {wide ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label={dict.shell.close}
            title={`${dict.shell.close} (Esc)`}
            className="aeon-icon-btn"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>
      <div className="aeon-inspector aeon-scroll @container min-h-0 flex-1 overflow-y-auto px-5 py-5">{children}</div>
    </aside>
  );
}
