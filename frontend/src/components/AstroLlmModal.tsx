"use client";

import React, { useEffect, useState } from "react";
import { Loader2, Send, Sparkles, Terminal, X } from "lucide-react";
import { useI18n } from "@/i18n/context";
import {
  sendAiCommand,
  type Epoch,
  type UiAction,
} from "@/lib/api";

interface AstroLlmModalProps {
  open: boolean;
  onClose: () => void;
  context: {
    ra: number;
    dec: number;
    epoch: Epoch;
    target_id?: string;
  };
  onExecuteActions: (actions: UiAction[]) => void;
}

export function AstroLlmModal({
  open,
  onClose,
  context,
  onExecuteActions,
}: AstroLlmModalProps) {
  const { lang, dict } = useI18n();

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [reply, setReply] = useState<string | null>(null);
  const [executed, setExecuted] = useState<UiAction[]>([]);
  const [fromCache, setFromCache] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const handleRun = async (msg: string) => {
    const trimmed = msg.trim();
    if (!trimmed) return;
    setLoading(true);
    try {
      const { data, fromCache: cached } = await sendAiCommand({
        message: trimmed,
        lang,
        context,
      });
      setReply(data.reply);
      setExecuted(data.actions);
      setFromCache(cached);
      if (data.actions.length > 0) {
        onExecuteActions(data.actions);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/75 p-4 pt-20 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={dict.ai.paletteTitle}
      onClick={onClose}
    >
      <div
        className="aeon-panel w-full max-w-2xl rounded-2xl p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-violet-400" />
            <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
              {dict.ai.paletteTitle}
            </h2>
            {fromCache && (
              <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                {dict.header.dataMode.offline_cache}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 transition hover:bg-white/10 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleRun(input);
          }}
          className="flex items-center gap-2"
        >
          <div className="relative flex-1">
            <Terminal className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-violet-400" />
            <input
              type="text"
              autoFocus
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={dict.ai.placeholder}
              className="w-full rounded-xl border border-white/15 bg-black/50 py-2.5 pl-9 pr-3 text-xs text-white placeholder:text-slate-500 focus:border-violet-400 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-xl border border-violet-400/40 bg-violet-500/20 px-4 py-2.5 text-xs font-semibold text-violet-100 transition hover:bg-violet-500/30 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            <span>{loading ? dict.ai.running : dict.ai.send}</span>
          </button>
        </form>

        {/* Suggested examples */}
        <div className="mt-3">
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-slate-400">
            {dict.ai.examplesTitle}:
          </p>
          <div className="flex flex-wrap gap-1.5">
            {dict.ai.examples.map((ex, i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  setInput(ex);
                  handleRun(ex);
                }}
                className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-left text-xs text-slate-300 transition hover:border-violet-400/40 hover:bg-violet-500/15 hover:text-white"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>

        {/* Reply & Executed Actions */}
        {reply && (
          <div className="mt-4 space-y-2.5 rounded-xl border border-violet-400/30 bg-violet-500/10 p-3.5 text-xs">
            <p className="font-medium text-violet-100">{reply}</p>
            {executed.length > 0 && (
              <div>
                <span className="text-[11px] text-slate-400">
                  {dict.ai.executedActions}:
                </span>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {executed.map((act, idx) => (
                    <span
                      key={idx}
                      className="aeon-mono rounded border border-cyan-400/30 bg-black/50 px-2 py-0.5 text-[11px] text-cyan-200"
                    >
                      {act.type}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
