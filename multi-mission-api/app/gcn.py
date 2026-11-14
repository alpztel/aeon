"""NASA GCN alerts provider (Kafka / GCN Circulars / archival cache fallback)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

FIXTURES_GCN_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "gcn_alerts.json"
_MEMORY_ALERTS: list[dict[str, Any]] = []


def _load_cached_alerts() -> list[dict[str, Any]]:
    raw = json.loads(FIXTURES_GCN_PATH.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for item in raw:
        entry = dict(item)
        title = str(entry.get("title", "GCN Alert"))
        if "önbellek" not in title.lower():
            entry["title"] = f"{title} (önbellek / cached)"
        out.append(entry)
    return out


def fetch_gcn_alerts(limit: int = 20) -> list[dict[str, Any]]:
    """Return the latest NASA GCN alerts (newest first), falling back to cached archival alerts."""
    if _MEMORY_ALERTS:
        return _MEMORY_ALERTS[:limit]

    gcn_url = os.environ.get("AEON_GCN_ARCHIVE_URL", "").strip()
    if gcn_url:
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(gcn_url)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and data:
                        return data[:limit]
        except Exception:
            pass

    cached = _load_cached_alerts()
    cached.sort(key=lambda a: a.get("time_utc", ""), reverse=True)
    return cached[:limit]
