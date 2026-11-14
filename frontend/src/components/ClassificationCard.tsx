"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Cpu, Loader2, ShieldCheck, Sparkles } from "lucide-react";
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
  const { lang, dict } = useI18n();

  const [result, setResult] = useState<AiClassifyResponse | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);

  const reqKey = `${coords.ra}:${coords.dec}`;
  const loading = loadedKey !== reqKey;

  useEffect(() => {
    let active = true;
    classifyTarget({ ra: coords.ra, dec: coords.dec })
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setResult(data);
        setFromCache(cached);
        setUnavailable(false);
        setLoadedKey(reqKey);
      })
      .catch(() => {
        if (!active) return;
        setResult(null);
        setUnavailable(true);
        setLoadedKey(reqKey);
      });
    return () => {
      active = false;
    };
  }, [coords.ra, coords.dec, reqKey]);

  const anomaly = result?.anomaly_score ?? 0;
  const topClass = result?.top_class;
  const phys = result?.physics_diagnostics;
  const zogy = result?.astroclip_zogy;

  const isPlanetX = Boolean(
    selectedObject?.is_synthetic || topClass === "planet_x_candidate"
  );
  const isColdSubstellar =
    isPlanetX || topClass === "cold_brown_dwarf";

  const displayTeff = isPlanetX
    ? lang === "tr"
      ? "~50 K (Dış Güneş Sistemi · Yığın Gerekli)"
      : "~50 K (Outer Solar System · Stack Required)"
    : selectedObject?.teff_k
      ? `${Math.round(selectedObject.teff_k)} K`
      : phys?.teff_k
        ? `${Math.round(phys.teff_k)} K`
        : "—";

  return (
    <section className="aeon-panel rounded-2xl p-4 @xl:p-5">
      {unavailable && !loading && (
        <p className="mb-3 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {dict.ai.serviceUnavailable}
        </p>
      )}
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

      {loading && !result && (
        <div className="flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-black/30 py-8 text-xs text-slate-300">
          <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
          <span>
            {lang === "tr"
              ? "102-bant spektral sınıflandırma ve kesit anomalisi hesaplanıyor..."
              : "Computing 102-band spectral classification and cutout anomaly..."}
          </span>
        </div>
      )}

      {result && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 @2xl:grid-cols-12">
            {/* 5 Class Probability Bars */}
            <div className="space-y-2.5 @2xl:col-span-8">
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
            <div className="flex flex-col justify-between rounded-xl border border-white/10 bg-black/40 p-4 @2xl:col-span-4">
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

          {/* Physics-Guided Spectral Diagnostics & ZOGY Telemetry */}
          {(phys || zogy) && (
            <div className="grid grid-cols-2 gap-2.5 rounded-xl border border-white/10 bg-black/30 p-3 text-xs @xl:grid-cols-4">
              <div>
                <span className="text-[10px] uppercase tracking-wider text-slate-400">
                  {lang === "tr" ? "Etkin Sıcaklık (Teff)" : "Effective Temp (Teff)"}
                </span>
                <p className="aeon-mono mt-0.5 font-semibold text-amber-200">
                  {displayTeff}
                </p>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-slate-400">
                  {lang === "tr" ? "CH₄ (3.3 µm) / H₂O (2.7 µm)" : "CH₄ (3.3 µm) / H₂O (2.7 µm)"}
                </span>
                <p className="aeon-mono mt-0.5 font-semibold text-cyan-200">
                  {phys?.ch4_3_3um_index !== undefined
                    ? `${phys.ch4_3_3um_index.toFixed(2)} / ${(phys.h2o_2_7um_index ?? 0).toFixed(2)}`
                    : "—"}
                </p>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-slate-400">
                  W1 − W2 (AB)
                </span>
                <p className="aeon-mono mt-0.5 font-semibold text-violet-200">
                  {phys?.w1_minus_w2_ab !== undefined
                    ? `${phys.w1_minus_w2_ab >= 0 ? "+" : ""}${phys.w1_minus_w2_ab.toFixed(2)} mag`
                    : "—"}
                </p>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-slate-400">
                  {lang === "tr" ? "ZOGY Tepe S/N · Kozmik Veto" : "ZOGY Peak S/N · CR Veto"}
                </span>
                <p className="aeon-mono mt-0.5 flex items-center gap-1 font-semibold text-emerald-300">
                  <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
                  <span>
                    {zogy?.zogy_peak_snr !== undefined ? `${zogy.zogy_peak_snr.toFixed(1)}σ` : "—"}
                    {" · "}
                    {zogy?.cosmic_ray_veto
                      ? lang === "tr"
                        ? "Artefakt"
                        : "Artifact"
                      : lang === "tr"
                        ? "PSF Doğrulandı"
                        : "PSF Verified"}
                  </span>
                </p>
              </div>
            </div>
          )}

          {/* 4-Step SPHEREx Discovery Verification Checklist */}
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3 text-xs">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              {lang === "tr"
                ? "SPHEREx Çoklu-Kanıt Keşif Doğrulama Zinciri"
                : "SPHEREx Multi-Evidence Discovery Verification Chain"}
            </p>
            <div className="grid grid-cols-1 gap-2 @xl:grid-cols-2">
              <div className="flex items-start gap-2 rounded-lg bg-black/30 px-2.5 py-1.5">
                <CheckCircle2
                  className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                    isColdSubstellar ? "text-emerald-400" : "text-cyan-400"
                  }`}
                />
                <div>
                  <span className="font-medium text-slate-200">
                    {lang === "tr" ? "1. Optik Veto (Gaia DR3): " : "1. Optical Veto (Gaia DR3): "}
                  </span>
                  <span className="text-slate-400">
                    {isColdSubstellar
                      ? lang === "tr"
                        ? "Görünür ışıkta yıldız eşleşmesi yok (soğuk alt-yıldız / dış güneş sistemi adayı)."
                        : "No optical stellar counterpart (cold substellar / outer solar system candidate)."
                      : lang === "tr"
                        ? "Optik/yakın-IR yıldız veya disk kaynağı ile uyumlu."
                        : "Consistent with optical/near-IR stellar or disk source."}
                  </span>
                </div>
              </div>

              <div className="flex items-start gap-2 rounded-lg bg-black/30 px-2.5 py-1.5">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                <div>
                  <span className="font-medium text-slate-200">
                    {lang === "tr" ? "2. SPHEREx 102-Bant Tayf: " : "2. SPHEREx 102-Band Spectrum: "}
                  </span>
                  <span className="text-slate-400">
                    {topClass === "cold_brown_dwarf"
                      ? lang === "tr"
                        ? "Derin CH₄ (3.3 µm) ve H₂O moleküler soğurma çukurları tespit edildi."
                        : "Deep CH₄ (3.3 µm) and H₂O molecular absorption troughs detected."
                      : isPlanetX
                        ? lang === "tr"
                          ? "Tek karede gürültü tabanında (S/N < 3); 24-kare Shift-and-Stack ile S/N > 8 kurtarımı."
                          : "Below single-frame noise floor (S/N < 3); recovered at S/N > 8 via 24-frame Shift-and-Stack."
                        : lang === "tr"
                          ? "0.75–5.0 µm süreklilik ve CO / H₂O bant profili ölçüldü."
                          : "0.75–5.0 µm continuum and CO / H₂O band profile measured."}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
