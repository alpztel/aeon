"""Active Anomaly Discovery (AAD) for citizen-science candidate ranking & online re-weighting.

Inspired by:
- `snad-space/coniferest` (Active Anomaly Discovery / PineForest online weight updates from human feedback)
- `MichelleLochner/astronomaly` (Human-in-the-loop anomaly prioritization in astronomical surveys)
"""

from __future__ import annotations

import math
import threading
from typing import Any

import numpy as np

from .sed_fitter import icrs_to_ecliptic_deg

CLASS_DISCOVERY_PRIOR: dict[str, float] = {
    "planet_x_candidate": 0.96,
    "cold_brown_dwarf": 0.85,
    "young_variable_star": 0.65,
    "high_z_galaxy": 0.60,
    "main_sequence_star": 0.20,
}


class ActiveAnomalyDiscoveryEngine:
    """Thread-safe online Active Anomaly Discovery (AAD) scorer updated by citizen-science votes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # 4-feature normalized weights: [anomaly_score, snr_factor, ecliptic_proximity, class_prior]
        self._weights = np.array([0.45, 0.25, 0.15, 0.15], dtype=np.float64)
        self._feedback_count = 0

    def extract_features(self, doc: dict[str, Any]) -> np.ndarray:
        """Map a candidate document to a bounded 4D feature vector in [0, 1]^4."""
        anom = float(doc.get("anomaly_score") or 0.5)
        if not math.isfinite(anom):
            anom = 0.5
        anom = max(0.0, min(1.0, anom))

        snr_raw = float(doc.get("snr") or 5.0)
        if not math.isfinite(snr_raw) or snr_raw <= 0.0:
            snr_factor = 0.0
        else:
            # Sub-linear saturation so SNR=1e9 cannot dominate or overflow
            snr_factor = float(math.tanh(snr_raw / 12.0))

        ra_raw = doc.get("ra")
        dec_raw = doc.get("dec")
        ra = float(ra_raw) if isinstance(ra_raw, (int, float)) and math.isfinite(ra_raw) else 0.0
        dec = float(dec_raw) if isinstance(dec_raw, (int, float)) and math.isfinite(dec_raw) else 0.0
        _, beta_ecl = icrs_to_ecliptic_deg(ra, dec)
        # Outer solar system candidates cluster within |beta| < 35 deg of the ecliptic
        ecl_prox = float(math.exp(-((beta_ecl / 40.0) ** 2)))

        cls_name = str(doc.get("object_class") or "main_sequence_star")
        cls_prior = CLASS_DISCOVERY_PRIOR.get(cls_name, 0.40)

        return np.array([anom, snr_factor, ecl_prox, cls_prior], dtype=np.float64)

    def score_candidate(self, doc: dict[str, Any]) -> float:
        """Compute active-learning priority score in [0.0, 1.0], combining AAD linear projection + Wilson vote boost."""
        feats = self.extract_features(doc)
        v_raw = doc.get("votes")
        if isinstance(v_raw, (int, float)) and math.isfinite(v_raw):
            votes = int(max(0.0, min(1_000_000.0, float(v_raw))))
        else:
            votes = 1

        with self._lock:
            base_score = float(np.dot(self._weights, feats))

        # Logarithmic Bayesian vote confidence (prevents vote-spam saturation while rewarding consensus)
        vote_boost = 0.08 * math.tanh(math.log1p(max(0, votes - 1)) / 3.0)
        final_score = max(0.0, min(1.0, 0.92 * base_score + vote_boost))
        return round(final_score, 4)

    def update_from_vote(self, doc: dict[str, Any]) -> dict[str, float]:
        """Online mirror-descent update of feature weights toward positively voted candidate characteristics."""
        feats = self.extract_features(doc)
        with self._lock:
            self._feedback_count += 1
            # Decaying step size eta_t = 0.04 / sqrt(t) for Robbins-Monro stochastic convergence
            eta = 0.04 / math.sqrt(float(self._feedback_count))
            updated = self._weights * np.exp(eta * (feats - np.mean(feats)))
            # Project onto simplex with box constraints [0.05, 0.70] so no feature ever collapses or monopolizes
            updated = np.clip(updated, 0.05, 0.70)
            updated = updated / np.sum(updated)
            self._weights = updated
            return {
                "anomaly_weight": round(float(self._weights[0]), 4),
                "snr_weight": round(float(self._weights[1]), 4),
                "ecliptic_weight": round(float(self._weights[2]), 4),
                "class_prior_weight": round(float(self._weights[3]), 4),
            }


_aad_engine: ActiveAnomalyDiscoveryEngine | None = None
_aad_init_lock = threading.Lock()


def get_aad_engine() -> ActiveAnomalyDiscoveryEngine:
    global _aad_engine
    if _aad_engine is None:
        with _aad_init_lock:
            if _aad_engine is None:
                _aad_engine = ActiveAnomalyDiscoveryEngine()
    return _aad_engine
