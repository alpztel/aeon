"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle, Cpu, Sparkles } from "lucide-react";
import { useI18n } from "@/i18n/context";
import {
  classifyTarget,
  type AiClassifyResponse,
  type CatalogObject,
  type ObjectClass,
} from "@/lib/api";

interface ClassificationCardProps {
  coords: { ra: number; dec: number };
  selectedObject: CatalogObject | null;
}

const ALL_CLASSES: ObjectClass[] = [
  "cold_brown_dwarf",
  "planet_x_candidate",
  "young_variable_star",
  "main_sequence_star",
  "high_z_galaxy",
];

export function ClassificationCard({
  coords,
  selectedObject,
}: ClassificationCardProps) {
  const { dict } = useI18n();

  const [result, setResult] = useState<AiClassifyResponse | null>(null);
  const [fromCache, setFromCache] = useState(false);

  useEffect(() => {
    let active = true;
    classifyTarget({ ra: coords.ra, dec: coords.dec })
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setResult(data);
        setFromCache(cached);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [coords.ra, coords.dec]);

  const anomaly = result?.anomaly_score ?? 0;
  const topClass = result?.top_class;

  return (
    <section className="aeon-panel rounded-2xl p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2.5">
          <Cpu className="h-4 w-4 text-violet-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
            {dict.ai.classifyTitle}
          </h2>
          {selectedObject?.is_synthetic && (
            <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/40 bg-rose-500/15 px-2.5 py-0.5 text-[10px] font-semibold text-rose-300">
              <AlertTriangle className="h-3 w-3" />
              {dict.badges.synthetic}
            </span>
          )}
          {fromCache && (
            <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300">
              {dict.header.dataMode.offline_cache}
            </span>
          )}
        </div>

        {topClass && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-violet-400/40 bg-violet-500/20 px-3 py-0.5 text-xs font-semibold text-violet-200">
            <Sparkles className="h-3.5 w-3.5" />
            <span>
              {dict.ai.topClass}: {dict.classes[topClass]}
            </span>
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
        {/* 5 Class Probability Bars */}
        <div className="space-y-2.5 md:col-span-8">
          {ALL_CLASSES.map((cls) => {
            const p = result?.probabilities?.[cls] ?? 0;
            const pct = Math.round(p * 100);
            const isTop = cls === topClass;
            return (
              <div key={cls} className="space-y-1 text-xs">
                <div className="flex justify-between">
                  <span
                    className={
                      isTop ? "font-semibold text-amber-200" : "text-slate-300"
                    }
                  >
                    {dict.classes[cls]}
                  </span>
                  <span className="aeon-mono text-slate-300">{pct}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                  <div
                    className={`h-full rounded-full transition-all ${
                      isTop ? "bg-amber-400" : "bg-cyan-400/60"
                    }`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* PatchAnomalyViT Gauge */}
        <div className="flex flex-col justify-between rounded-xl border border-white/10 bg-black/40 p-4 md:col-span-4">
          <div>
            <span className="text-xs font-medium text-slate-400">
              {dict.ai.anomalyScore}
            </span>
            <div className="mt-2 flex items-baseline gap-2">
              <span
                className={`aeon-mono text-3xl font-bold ${
                  anomaly >= 0.85 ? "text-rose-400" : "text-cyan-300"
                }`}
              >
                {anomaly.toFixed(2)}
              </span>
              <span className="text-xs text-slate-400">/ 1.00</span>
            </div>
            <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className={`h-full rounded-full ${
                  anomaly >= 0.85 ? "bg-rose-500" : "bg-cyan-400"
                }`}
                style={{ width: `${Math.min(100, Math.round(anomaly * 100))}%` }}
              />
            </div>
            <p className="mt-2 text-xs text-slate-300">
              {anomaly >= 0.85 ? dict.ai.highAnomaly : dict.ai.normalAnomaly}
            </p>
          </div>

          {result?.model_versions && (
            <div className="aeon-mono mt-3 border-t border-white/10 pt-2 text-[10px] text-slate-500">
              {Object.entries(result.model_versions)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · ")}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
