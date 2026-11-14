"use client";

import React, { useEffect, useRef, useState } from "react";
import { CornerDownLeft, Loader2, Search } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { DEMO_TARGETS, searchCatalog, type CatalogObject, type Epoch } from "@/lib/api";

type Coords = { ra: number; dec: number };

interface SearchBoxProps {
  epoch: Epoch;
  selectedObject: CatalogObject | null;
  onSelectObject: (obj: CatalogObject | null, coords: Coords, refCoords?: Coords) => void;
}

const COORD_RE = /^\s*([+-]?\d+(?:\.\d+)?)\s*[,;\s]\s*([+-]?\d+(?:\.\d+)?)\s*$/;

/** Catalog / coordinate search with demo-target suggestions. Press "/" anywhere to focus it. */
export function SearchBox({ epoch, selectedObject, onSelectObject }: SearchBoxProps) {
  const { dict } = useI18n();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seqRef = useRef(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = t?.tagName === "INPUT" || t?.tagName === "TEXTAREA" || t?.isContentEditable;
      if (e.key === "/" && !typing) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    const onDown = (e: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, []);

  const resolveById = async (id: string, fallback: Coords, fallbackRef?: Coords) => {
    const seq = ++seqRef.current;
    setError(null);
    setBusy(true);
    try {
      const [ep, ref] = await Promise.all([searchCatalog({ q: id, epoch }), searchCatalog({ q: id })]);
      if (seq !== seqRef.current) return;
      const hit = ep.data.results[0];
      const refHit = ref.data.results[0];
      if (hit) {
        onSelectObject(hit, { ra: hit.ra, dec: hit.dec }, {
          ra: refHit?.ra ?? fallbackRef?.ra ?? hit.ra,
          dec: refHit?.dec ?? fallbackRef?.dec ?? hit.dec,
        });
      } else {
        onSelectObject(null, fallback, fallbackRef ?? fallback);
      }
    } catch {
      if (seq === seqRef.current) onSelectObject(null, fallback, fallbackRef ?? fallback);
    } finally {
      if (seq === seqRef.current) setBusy(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const raw = query.trim();
    if (!raw) return;
    const seq = ++seqRef.current;
    setError(null);
    setBusy(true);

    const m = raw.match(COORD_RE);
    if (m) {
      const ra = Number(m[1]);
      const dec = Number(m[2]);
      if (ra < 0 || ra > 360 || dec < -90 || dec > 90) {
        setError(dict.errors.invalidCoords);
        setBusy(false);
        return;
      }
      try {
        const { data } = await searchCatalog({ ra, dec, radius_arcmin: 5, include_field: true, epoch });
        if (seq !== seqRef.current) return;
        const hit = data.results[0] ?? null;
        if (hit && hit.source !== "field") {
          try {
            const { data: refData } = await searchCatalog({ q: hit.id });
            if (seq !== seqRef.current) return;
            const refHit = refData.results[0];
            onSelectObject(hit, { ra, dec }, { ra: refHit?.ra ?? ra, dec: refHit?.dec ?? dec });
            setOpen(false);
            return;
          } catch {
            // fall through to the plain field selection
          }
        }
        onSelectObject(hit, { ra, dec }, { ra, dec });
        setOpen(false);
      } catch {
        if (seq === seqRef.current) onSelectObject(null, { ra, dec }, { ra, dec });
      } finally {
        if (seq === seqRef.current) setBusy(false);
      }
      return;
    }

    try {
      const [ep, ref] = await Promise.all([searchCatalog({ q: raw, epoch }), searchCatalog({ q: raw })]);
      if (seq !== seqRef.current) return;
      const hit = ep.data.results[0];
      const refHit = ref.data.results[0];
      if (!hit) {
        setError(dict.sky.noResults);
      } else {
        onSelectObject(hit, { ra: hit.ra, dec: hit.dec }, { ra: refHit?.ra ?? hit.ra, dec: refHit?.dec ?? hit.dec });
        setOpen(false);
      }
    } catch {
      if (seq === seqRef.current) setError(dict.errors.network);
    } finally {
      if (seq === seqRef.current) setBusy(false);
    }
  };

  return (
    <div ref={wrapRef} className="relative w-full">
      <form onSubmit={submit} role="search" className="aeon-glass flex h-10 items-center gap-2 rounded-full pl-3.5 pr-1.5">
        {busy ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-ice" />
        ) : (
          <Search className="h-4 w-4 shrink-0 text-muted" />
        )}
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setError(null);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setOpen(false);
              inputRef.current?.blur();
            }
          }}
          placeholder={dict.shell.searchPlaceholder}
          aria-label={dict.shell.searchPlaceholder}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls="aeon-search-suggestions"
          className="min-w-0 flex-1 bg-transparent text-[13px] text-foreground placeholder:text-muted focus:outline-none"
        />
        <kbd className="aeon-kbd hidden sm:inline">/</kbd>
        <button
          type="submit"
          disabled={busy || !query.trim()}
          aria-label={dict.sky.searchButton}
          className="aeon-icon-btn h-7 w-7 disabled:opacity-30"
        >
          <CornerDownLeft className="h-3.5 w-3.5" />
        </button>
      </form>

      {open && (
        <div
          id="aeon-search-suggestions"
          className="aeon-panel aeon-fade-up absolute inset-x-0 top-12 z-50 overflow-hidden p-1.5 shadow-2xl"
        >
          {error && <p className="px-3 py-2 text-xs text-[var(--aeon-danger)]">{error}</p>}
          <p className="aeon-label px-3 pb-1 pt-2">{dict.shell.quickTargets}</p>
          <ul>
            {DEMO_TARGETS.map((t) => {
              const ep = t.epochCoords[epoch] ?? { ra: t.ra, dec: t.dec };
              const active = selectedObject?.id === t.id;
              return (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      setQuery("");
                      void resolveById(t.id, ep, { ra: t.refRa, dec: t.refDec });
                    }}
                    className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-[13px] transition hover:bg-white/[0.06] ${
                      active ? "text-signal" : "text-foreground"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className={`h-1.5 w-1.5 rounded-full ${active ? "bg-signal" : "bg-white/25"}`} />
                      {t.label}
                      {t.synthetic && (
                        <span className="aeon-label rounded border border-[var(--aeon-danger)]/50 px-1 text-[9px] text-[var(--aeon-danger)]">
                          SYN
                        </span>
                      )}
                    </span>
                    <span className="aeon-mono text-[11px] text-muted">
                      {ep.ra.toFixed(3)}° {ep.dec >= 0 ? "+" : ""}
                      {ep.dec.toFixed(3)}°
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="border-t border-line px-3 py-2 text-[11px] text-muted">{dict.shell.searchHint}</p>
        </div>
      )}
    </div>
  );
}
