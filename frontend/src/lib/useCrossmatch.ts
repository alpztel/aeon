"use client";

import { useEffect, useState } from "react";
import { getCrossmatchShared, type CrossmatchResult } from "@/lib/api";

interface State {
  key: string;
  data: CrossmatchResult | null;
  fromCache: boolean;
  failed: boolean;
}

/** The cross-match answer for a position, shared between the panels that show parts of it. */
export function useCrossmatch(ra: number, dec: number) {
  const [state, setState] = useState<State>({ key: "", data: null, fromCache: false, failed: false });
  const reqKey = `${ra}:${dec}`;

  useEffect(() => {
    let active = true;
    getCrossmatchShared(ra, dec)
      .then(({ data, fromCache }) => {
        if (active) setState({ key: reqKey, data, fromCache, failed: false });
      })
      .catch(() => {
        if (active) setState({ key: reqKey, data: null, fromCache: false, failed: true });
      });
    return () => {
      active = false;
    };
  }, [ra, dec, reqKey]);

  const ready = state.key === reqKey;
  return {
    loading: !ready,
    data: ready ? state.data : null,
    fromCache: ready && state.fromCache,
    failed: ready && state.failed,
  };
}
