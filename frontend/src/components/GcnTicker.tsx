"use client";

import React, { useEffect, useState } from "react";
import { Bell, Crosshair } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { getGcnAlerts, type GcnAlert } from "@/lib/api";

interface GcnTickerProps {
  onFlyTo: (ra: number, dec: number) => void;
}

export function GcnTicker({ onFlyTo }: GcnTickerProps) {
  const { dict } = useI18n();
  const [alerts, setAlerts] = useState<GcnAlert[]>([]);
  const [fromCache, setFromCache] = useState(false);

  useEffect(() => {
    let active = true;
    getGcnAlerts(8)
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setAlerts(data);
        setFromCache(cached);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  if (alerts.length === 0) return null;

  return (
    <div className="border-b border-white/10 bg-[#090D16]/90 px-4 py-1.5 text-xs sm:px-6">
      <div className="mx-auto flex max-w-[1600px] items-center gap-3 overflow-x-auto">
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-rose-500/40 bg-rose-500/15 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-rose-300">
          <Bell className="h-3 w-3" />
          <span>{dict.community.gcnLabel}</span>
        </span>

        {fromCache && (
          <span className="shrink-0 rounded border border-amber-400/30 bg-amber-500/10 px-1.5 py-0.2 text-[10px] text-amber-300">
            {dict.header.dataMode.offline_cache}
          </span>
        )}

        <div className="flex items-center gap-4">
          {alerts.map((al) => (
            <div
              key={al.id}
              className="flex shrink-0 items-center gap-2 rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-1"
            >
              <span className="aeon-mono rounded bg-cyan-500/20 px-1.5 py-0.2 text-[10px] font-bold text-cyan-300">
                {al.kind}
              </span>
              <span className="text-slate-300">{al.title ?? al.id}</span>
              {al.ra !== undefined && al.dec !== undefined && (
                <button
                  type="button"
                  onClick={() => onFlyTo(al.ra!, al.dec!)}
                  className="aeon-mono inline-flex items-center gap-1 text-[11px] text-amber-300 hover:underline"
                >
                  <Crosshair className="h-3 w-3" />
                  <span>
                    {al.ra.toFixed(2)}°, {al.dec.toFixed(2)}°
                  </span>
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
