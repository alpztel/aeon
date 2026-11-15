"use client";

import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Loader2 } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { fill } from "@/components/DataFacts";
import {
  EPOCHS,
  EXAMPLE_TARGET_IDS,
  getBestEpochSpectrum,
  searchCatalog,
  spectrumPipeline,
  type CatalogObject,
  type Epoch,
  type ObjectClass,
} from "@/lib/api";

interface ExamplesPanelProps {
  currentId: string | null;
  /** Fly to a catalog object; bestEpoch = the quarter with its best real SPHEREx data, if any. */
  onPick: (id: string, bestEpoch: Epoch | null) => void;
}

/** What the archive holds for one target, from the backend's automatic epoch choice. */
interface Coverage {
  best: Epoch | null;
  perEpoch: Partial<Record<Epoch, { real: boolean; bands?: number; observed?: string | null; reason?: string }>>;
}

type Status = { state: "loading" } | { state: "ready"; coverage: Coverage } | { state: "error" };

const CLASS_ORDER: ObjectClass[] = [
  "cold_brown_dwarf",
  "planet_x_candidate",
  "young_variable_star",
  "main_sequence_star",
  "high_z_galaxy",
];

/** "(need 34; 36 frames, 36 rejected)" -> most frames rejected = saturated (or flagged) frames. */
function rejectedShare(reason: string | undefined): number | null {
  const m = reason?.match(/(\d+) frames, (\d+) rejected/);
  if (!m) return null;
  const n = Number(m[1]);
  return n > 0 ? Number(m[2]) / n : null;
}

function readCoverage(raw: unknown): Coverage {
  const sel = (raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {}) as {
    chosen?: unknown;
    candidates?: Record<string, Record<string, unknown>>;
  };
  const perEpoch: Coverage["perEpoch"] = {};
  let best: Epoch | null = null;
  for (const ep of EPOCHS) {
    const c = sel.candidates?.[ep];
    if (!c) continue;
    const real = c.data_mode === "fits_archive";
    perEpoch[ep] = {
      real,
      bands: typeof c.n_bands_measured === "number" ? c.n_bands_measured : undefined,
      observed: typeof c.observed_quarter === "string" ? c.observed_quarter : null,
      reason: typeof c.reason === "string" ? c.reason : undefined,
    };
  }
  if (typeof sel.chosen === "string" && perEpoch[sel.chosen as Epoch]?.real) best = sel.chosen as Epoch;
  return { best, perEpoch };
}

export function ExamplesPanel({ currentId, onPick }: ExamplesPanelProps) {
  const { dict, bilingual } = useI18n();
  const [entries, setEntries] = useState<CatalogObject[] | null>(null);
  const [status, setStatus] = useState<Record<string, Status>>({});
  const [onlyReal, setOnlyReal] = useState(false);

  // Catalog entries (reference epoch) for every example the backend knows.
  useEffect(() => {
    let active = true;
    Promise.all(
      EXAMPLE_TARGET_IDS.map((id) =>
        searchCatalog({ q: id, limit: 5 })
          .then(({ data, fromCache }) => (fromCache ? null : data.results.find((r) => r.id === id) ?? null))
          .catch(() => null)
      )
    ).then((rows) => {
      if (active) setEntries(rows.filter((r): r is CatalogObject => r !== null));
    });
    return () => {
      active = false;
    };
  }, []);

  // Archive coverage, two targets at a time (each asks the backend to compare the four quarters).
  useEffect(() => {
    if (!entries) return;
    let active = true;
    const queue = [...entries];
    const next = async (): Promise<void> => {
      const e = queue.shift();
      if (!e || !active) return;
      setStatus((s) => ({ ...s, [e.id]: { state: "loading" } }));
      try {
        const spec = await getBestEpochSpectrum(e.ra, e.dec);
        const coverage = readCoverage(spectrumPipeline(spec).epoch_selection);
        if (active) setStatus((s) => ({ ...s, [e.id]: { state: "ready", coverage } }));
      } catch {
        if (active) setStatus((s) => ({ ...s, [e.id]: { state: "error" } }));
      }
      await next();
    };
    void Promise.all([next(), next()]);
    return () => {
      active = false;
    };
  }, [entries]);

  const groups = useMemo(() => {
    const list = (entries ?? []).filter((e) => {
      if (!onlyReal) return true;
      const st = status[e.id];
      return st?.state === "ready" && st.coverage.best !== null;
    });
    return CLASS_ORDER.map((cls) => ({ cls, items: list.filter((e) => e.object_class === cls) })).filter((g) => g.items.length > 0);
  }, [entries, status, onlyReal]);

  const nReal = (entries ?? []).filter((e) => {
    const st = status[e.id];
    return st?.state === "ready" && st.coverage.best !== null;
  }).length;

  return (
    <section className="aeon-panel rounded-2xl p-4 @xl:p-5" aria-busy={entries === null}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-300">
          {entries === null ? dict.examples.loading : fill(dict.examples.summary, { n: entries.length, r: nReal })}
        </p>
        <div className="inline-flex rounded-lg border border-white/10 bg-black/30 p-0.5 text-[11px]">
          {[false, true].map((v) => (
            <button
              key={String(v)}
              type="button"
              aria-pressed={onlyReal === v}
              onClick={() => setOnlyReal(v)}
              className={`rounded-md px-2.5 py-1 transition ${onlyReal === v ? "bg-white/10 text-foreground" : "text-slate-400 hover:text-slate-200"}`}
            >
              {v ? dict.examples.filterReal : dict.examples.filterAll}
            </button>
          ))}
        </div>
      </div>

      {entries === null && (
        <div className="flex items-center gap-2 py-6 text-xs text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" /> {dict.examples.loading}
        </div>
      )}
      {entries !== null && entries.length === 0 && <p className="py-4 text-xs text-slate-400">{dict.examples.empty}</p>}

      <div className="space-y-5">
        {groups.map((g) => (
          <div key={g.cls}>
            <h3 className="aeon-label mb-2 normal-case">
              {dict.classes[g.cls]} · {g.items.length}
            </h3>
            <ul className="grid grid-cols-1 gap-2.5 @2xl:grid-cols-2">
              {g.items.map((e) => (
                <ExampleCard
                  key={e.id}
                  entry={e}
                  status={status[e.id]}
                  current={currentId === e.id}
                  onPick={onPick}
                  description={bilingual(e.description)}
                />
              ))}
            </ul>
          </div>
        ))}
      </div>
      <p className="mt-4 text-[11px] leading-relaxed text-slate-500">{dict.examples.footnote}</p>
    </section>
  );
}

function ExampleCard({
  entry,
  status,
  current,
  onPick,
  description,
}: {
  entry: CatalogObject;
  status: Status | undefined;
  current: boolean;
  onPick: ExamplesPanelProps["onPick"];
  description: string;
}) {
  const { dict } = useI18n();
  const cov = status?.state === "ready" ? status.coverage : null;
  const pm =
    typeof entry.pm_ra_cosdec_arcsec_yr === "number"
      ? Math.hypot(entry.pm_ra_cosdec_arcsec_yr, entry.pm_dec_arcsec_yr ?? 0)
      : null;
  const distance =
    typeof entry.distance_au === "number"
      ? `${entry.distance_au} AU`
      : typeof entry.distance_pc === "number"
        ? `${entry.distance_pc} pc`
        : null;

  // Why there is no real spectrum: mostly rejected frames = saturated (bright) source.
  const reasons = cov ? Object.values(cov.perEpoch).filter((p) => p && !p.real).map((p) => p?.reason) : [];
  const saturated = reasons.some((r) => (rejectedShare(r) ?? 0) >= 0.6);
  const covered = reasons.some((r) => r && !r.startsWith("no SPHEREx frame"));
  const bestInfo = cov?.best ? cov.perEpoch[cov.best] : null;

  let dataLine: React.ReactNode;
  if (!status || status.state === "loading") {
    dataLine = <span className="text-slate-500">{dict.examples.checking}</span>;
  } else if (status.state === "error") {
    dataLine = <span className="text-slate-500">{dict.examples.unknown}</span>;
  } else if (cov?.best && bestInfo) {
    dataLine = (
      <span className="text-cyan-200">
        {fill(dict.examples.realIn, { q: cov.best.slice(5) })}
        {typeof bestInfo.bands === "number" ? ` · ${fill(dict.examples.bands, { n: bestInfo.bands })}` : ""}
        {bestInfo.observed && bestInfo.observed !== cov.best ? ` · ${dict.data.observedQuarter} ${bestInfo.observed}` : ""}
      </span>
    );
  } else if (saturated) {
    dataLine = <span className="text-[var(--aeon-warn)]">{dict.examples.saturated}</span>;
  } else if (covered) {
    dataLine = <span className="text-slate-400">{dict.examples.sparse}</span>;
  } else {
    dataLine = <span className="text-slate-400">{dict.examples.noCoverage}</span>;
  }

  return (
    <li>
      <button
        type="button"
        onClick={() => onPick(entry.id, cov?.best ?? null)}
        aria-current={current ? "true" : undefined}
        className={`group flex h-full w-full flex-col gap-1.5 rounded-xl border p-3 text-left transition ${
          current ? "border-signal/60 bg-signal/10" : "border-white/10 bg-black/25 hover:border-white/25 hover:bg-white/[0.04]"
        }`}
      >
        <div className="flex items-start justify-between gap-2">
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-medium text-foreground">{entry.name}</span>
            {entry.aliases && entry.aliases.length > 0 && (
              <span className="block truncate text-[11px] text-slate-500">{entry.aliases.slice(0, 2).join(" · ")}</span>
            )}
          </span>
          <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500 transition group-hover:translate-x-0.5 group-hover:text-signal" />
        </div>

        {entry.is_synthetic && (
          <span className="inline-flex w-fit items-center gap-1 rounded-full border border-rose-500/40 bg-rose-500/15 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
            <AlertTriangle className="h-3 w-3" />
            {dict.badges.synthetic}
          </span>
        )}

        <span className="aeon-mono flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-300">
          {distance && <span>{distance}</span>}
          {typeof entry.mag_ab_w2 === "number" && <span>W2 {entry.mag_ab_w2.toFixed(1)}</span>}
          {typeof entry.teff_k === "number" && <span>{entry.teff_k} K</span>}
          {pm !== null && pm > 0.05 && <span>{pm.toFixed(2)}″/yr</span>}
        </span>

        {/* Quarter chips: filled = real SPHEREx spectrum, hollow = physical model */}
        <span className="flex items-center gap-1.5" aria-label={dict.examples.quarters}>
          {EPOCHS.map((ep) => {
            const p = cov?.perEpoch[ep];
            return (
              <span
                key={ep}
                title={p ? (p.real ? `${ep}: ${dict.data.realSpherex}` : `${ep}: ${p.reason ?? dict.data.physicalModel}`) : ep}
                className={`aeon-mono inline-flex h-5 items-center rounded px-1.5 text-[10px] ${
                  p?.real
                    ? "bg-cyan-400/20 text-cyan-100"
                    : p
                      ? "border border-white/15 text-slate-500"
                      : "border border-white/5 text-slate-600"
                }`}
              >
                {ep.slice(5)}
              </span>
            );
          })}
          <span className="ml-1 text-[11px]">{dataLine}</span>
        </span>

        {description && <span className="line-clamp-2 text-[11px] leading-relaxed text-slate-400">{description}</span>}
      </button>
    </li>
  );
}
