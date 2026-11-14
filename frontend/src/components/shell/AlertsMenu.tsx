"use client";

import React, { useEffect, useRef, useState } from "react";
import { Bell, Crosshair } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { getGcnAlerts, type GcnAlert } from "@/lib/api";

interface AlertsMenuProps {
  onFlyTo: (ra: number, dec: number) => void;
}

/** NASA GCN notices behind a bell instead of a permanent ticker. */
export function AlertsMenu({ onFlyTo }: AlertsMenuProps) {
  const { dict } = useI18n();
  const [alerts, setAlerts] = useState<GcnAlert[]>([]);
  const [fromCache, setFromCache] = useState(false);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let active = true;
    getGcnAlerts(8)
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setAlerts(data);
        setFromCache(cached);
      })
      .catch(() => {});
    const onDown = (e: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", onDown);
    return () => {
      active = false;
      window.removeEventListener("pointerdown", onDown);
    };
  }, []);

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`${dict.shell.alerts} (${alerts.length})`}
        title={dict.community.gcnLabel}
        className="aeon-icon-btn relative"
      >
        <Bell className="h-4 w-4" />
        {alerts.length > 0 && (
          <span className="aeon-mono absolute right-1 top-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-signal px-0.5 text-[9px] font-semibold text-[#140803]">
            {alerts.length}
          </span>
        )}
      </button>
      {open && (
        <div className="aeon-panel aeon-fade-up absolute right-0 top-12 z-50 w-[min(360px,calc(100vw-24px))] p-1.5 shadow-2xl">
          <div className="flex items-center justify-between px-3 pb-1 pt-2">
            <p className="aeon-label">{dict.community.gcnLabel}</p>
            {fromCache && <span className="aeon-label text-[var(--aeon-warn)]">{dict.header.dataMode.offline_cache}</span>}
          </div>
          {alerts.length === 0 ? (
            <p className="px-3 py-3 text-xs text-muted">{dict.shell.noAlerts}</p>
          ) : (
            <ul className="aeon-scroll max-h-[50vh] overflow-y-auto">
              {alerts.map((al) => (
                <li key={al.id} className="rounded-lg px-3 py-2 hover:bg-white/[0.05]">
                  <div className="flex items-center gap-2">
                    <span className="aeon-label rounded border border-line px-1 text-[9px] text-ice">{al.kind}</span>
                    <span className="truncate text-[13px] text-foreground">{al.title ?? al.id}</span>
                  </div>
                  {al.ra !== undefined && al.dec !== undefined && al.ra !== null && al.dec !== null && (
                    <button
                      type="button"
                      onClick={() => {
                        onFlyTo(al.ra as number, al.dec as number);
                        setOpen(false);
                      }}
                      className="aeon-mono mt-1 inline-flex items-center gap-1 text-[11px] text-signal hover:underline"
                    >
                      <Crosshair className="h-3 w-3" />
                      {(al.ra as number).toFixed(2)}°, {(al.dec as number).toFixed(2)}°
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
