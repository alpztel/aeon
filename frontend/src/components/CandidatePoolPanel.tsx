"use client";

import React, { useEffect, useState } from "react";
import {
  Crosshair,
  ExternalLink,
  PlusCircle,
  ThumbsUp,
  Trophy,
} from "lucide-react";
import { useI18n } from "@/i18n/context";
import {
  classifyTarget,
  getCandidates,
  runDifference,
  submitOrVoteCandidate,
  type Candidate,
  type CatalogObject,
} from "@/lib/api";

interface CandidatePoolPanelProps {
  coords: { ra: number; dec: number };
  selectedObject: CatalogObject | null;
  onInspectCoords: (ra: number, dec: number) => void;
}

export function CandidatePoolPanel({
  coords,
  selectedObject,
  onInspectCoords,
}: CandidatePoolPanelProps) {
  const { dict } = useI18n();

  const [sort, setSort] = useState<"votes" | "anomaly" | "recent">("votes");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [fromCache, setFromCache] = useState(false);
  const [observer, setObserver] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    getCandidates(sort, 20)
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setCandidates(data);
        setFromCache(cached);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [sort]);

  const handleVote = async (id?: string) => {
    if (!id) return;
    const { data: updated } = await submitOrVoteCandidate({
      action: "vote",
      candidate_id: id,
    });
    setCandidates((prev) =>
      prev.map((c) => (c.id === id ? { ...c, votes: updated.votes } : c))
    );
  };

  const handleSubmitCandidate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const [aiRes, diffRes] = await Promise.all([
        classifyTarget({ ra: coords.ra, dec: coords.dec }).catch(() => null),
        runDifference({ ra: coords.ra, dec: coords.dec }).catch(() => null),
      ]);
      const measuredSnr = diffRes?.data.detections?.[0]?.snr ?? 5.0;
      const measuredAnomaly = aiRes?.data.anomaly_score ?? 0.5;
      const notePrefix = selectedObject?.is_synthetic ? "[SYNTHETIC TEST] " : "";
      const { data: created } = await submitOrVoteCandidate({
        action: "submit",
        candidate: {
          ra: coords.ra,
          dec: coords.dec,
          object_class:
            selectedObject?.object_class ?? aiRes?.data.top_class ?? "planet_x_candidate",
          anomaly_score: measuredAnomaly,
          snr: measuredSnr,
          submitted_by: observer.trim() || "Citizen-Scientist",
          notes: `${notePrefix}${notes.trim() || selectedObject?.name || "SPHEREx candidate"}`,
        },
      });
      setCandidates((prev) => [created, ...prev]);
      setNotes("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="aeon-panel rounded-2xl p-4 sm:p-5">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <Trophy className="h-4 w-4 text-amber-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
            {dict.community.poolTitle}
          </h2>
          {fromCache && (
            <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300">
              {dict.header.dataMode.offline_cache}
            </span>
          )}
        </div>

        <div className="inline-flex rounded-lg border border-white/10 bg-white/5 p-0.5 text-xs">
          <button
            type="button"
            onClick={() => setSort("votes")}
            className={`rounded-md px-2.5 py-1 transition ${
              sort === "votes" ? "bg-amber-500/20 text-amber-200" : "text-slate-400"
            }`}
          >
            {dict.community.sortVotes}
          </button>
          <button
            type="button"
            onClick={() => setSort("anomaly")}
            className={`rounded-md px-2.5 py-1 transition ${
              sort === "anomaly" ? "bg-amber-500/20 text-amber-200" : "text-slate-400"
            }`}
          >
            {dict.community.sortAnomaly}
          </button>
          <button
            type="button"
            onClick={() => setSort("recent")}
            className={`rounded-md px-2.5 py-1 transition ${
              sort === "recent" ? "bg-amber-500/20 text-amber-200" : "text-slate-400"
            }`}
          >
            {dict.community.sortRecent}
          </button>
        </div>
      </div>

      {/* Submit Current Target Form */}
      <form
        onSubmit={handleSubmitCandidate}
        className="mb-4 flex flex-col gap-2 rounded-xl border border-white/10 bg-black/30 p-3 sm:flex-row sm:items-center"
      >
        <input
          type="text"
          value={observer}
          onChange={(e) => setObserver(e.target.value)}
          placeholder={dict.community.observerPlaceholder}
          className="rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 text-xs text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none sm:w-44"
        />
        <input
          type="text"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder={dict.community.notesPlaceholder}
          className="flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 text-xs text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none"
        />
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-emerald-400/35 bg-emerald-500/15 px-3.5 py-1.5 text-xs font-medium text-emerald-200 transition hover:bg-emerald-500/25 disabled:opacity-50"
        >
          <PlusCircle className="h-3.5 w-3.5" />
          <span>
            {submitting ? dict.community.submitting : dict.community.submitCurrent}
          </span>
        </button>
      </form>

      {/* Candidates Leaderboard */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {candidates.map((c, idx) => (
          <div
            key={c.id ?? idx}
            className="flex flex-col justify-between gap-2.5 rounded-xl border border-white/10 bg-black/40 p-3.5 text-xs"
          >
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="aeon-mono font-semibold text-cyan-200">
                  ICRS {c.ra.toFixed(3)}°, {c.dec >= 0 ? "+" : ""}
                  {c.dec.toFixed(3)}°
                </span>
                {c.anomaly_score !== undefined && (
                  <span className="aeon-mono rounded border border-violet-400/30 bg-violet-500/15 px-2 py-0.5 text-[10px] font-semibold text-violet-200">
                    ViT {c.anomaly_score.toFixed(2)}
                  </span>
                )}
              </div>

              {c.object_class && (
                <p className="mt-1 text-[11px] font-medium text-amber-200">
                  {dict.classes[c.object_class]}
                </p>
              )}

              {c.notes && (
                <p className="mt-1.5 text-slate-300 leading-relaxed">{c.notes}</p>
              )}
            </div>

            <div className="flex items-center justify-between border-t border-white/10 pt-2.5">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleVote(c.id)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/35 bg-amber-500/15 px-2.5 py-1 font-medium text-amber-200 transition hover:bg-amber-500/25"
                >
                  <ThumbsUp className="h-3 w-3" />
                  <span className="aeon-mono">{c.votes ?? 0}</span>
                </button>

                <button
                  type="button"
                  onClick={() => onInspectCoords(c.ra, c.dec)}
                  className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-slate-300 transition hover:bg-white/10"
                >
                  <Crosshair className="h-3 w-3" />
                  <span>{dict.community.flyTo}</span>
                </button>
              </div>

              {c.github_issue_url && (
                <a
                  href={c.github_issue_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[11px] text-cyan-300 hover:underline"
                >
                  <span>{dict.community.issueOpened}</span>
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
