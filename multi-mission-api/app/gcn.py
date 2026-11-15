"""NASA GCN alerts: GCN Kafka (Circulars) when credentials exist, otherwise an optional JSON archive URL.

Only real notices are ever returned. Alerts received from Kafka are kept in memory and in a small
on-disk cache (so a restart still shows recent real alerts). With no source configured the endpoint
returns an empty list - the frontend then hides the ticker instead of showing invented alerts.

Configuration (environment):
  GCN_CLIENT_ID / GCN_CLIENT_SECRET   credentials from https://gcn.nasa.gov (Kafka, topic gcn.circulars)
  AEON_GCN_ARCHIVE_URL                optional URL returning a JSON list in the contract's alert shape
  AEON_GCN_CACHE                      cache file (default .cache_gcn/alerts.json)
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CACHE_PATH = Path(os.environ.get("AEON_GCN_CACHE", str(Path(__file__).resolve().parents[1] / ".cache_gcn" / "alerts.json")))
MAX_KEEP = 200
_ALERTS: list[dict[str, Any]] = []
_LOCK = threading.Lock()
_CONSUMER_STARTED = False

_KIND_PATTERNS = (
    (r"\bGRB\b|gamma-ray burst", "GRB"),
    (r"IceCube|neutrino", "neutrino"),
    (r"\bS\d{6}[a-z]+\b|LIGO|Virgo|KAGRA|gravitational", "GW"),
    (r"\bSN\s?\d{4}|supernova", "SN"),
    (r"\bEP\d{6}|Einstein Probe", "X-ray transient"),
    (r"\bFRB\b", "FRB"),
)


_COORD_BODY_RE = re.compile(
    r"RA\s*(?:\(J2000\))?\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*(?:deg|d|°)?[,;\s]+"
    r"Dec\s*(?:\(J2000\))?\s*[:=]\s*([+-]?[0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


def circular_to_alert(c: dict[str, Any]) -> dict[str, Any] | None:
    """Map a GCN Circular JSON record to the contract's alert shape."""
    try:
        cid = int(c["circularId"])
    except (KeyError, TypeError, ValueError):
        return None
    subject = str(c.get("subject") or "").strip()
    kind = next((k for pat, k in _KIND_PATTERNS if re.search(pat, subject, re.IGNORECASE)), "circular")
    created = c.get("createdOn")
    try:
        t = datetime.fromtimestamp(float(created) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None
    out: dict[str, Any] = {
        "id": f"GCN-{cid}",
        "kind": kind,
        "time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": subject,
        "url": f"https://gcn.nasa.gov/circulars/{cid}",
    }
    body_txt = c.get("body")
    if isinstance(body_txt, str):
        m = _COORD_BODY_RE.search(body_txt)
        if m:
            ra_v, dec_v = float(m.group(1)), float(m.group(2))
            if 0.0 <= ra_v <= 360.0 and -90.0 <= dec_v <= 90.0:
                out["ra"] = round(ra_v, 4)
                out["dec"] = round(dec_v, 4)
    return out


def _store(alert: dict[str, Any]) -> None:
    with _LOCK:
        if any(a["id"] == alert["id"] for a in _ALERTS):
            return
        _ALERTS.append(alert)
        _ALERTS.sort(key=lambda a: a["time_utc"], reverse=True)
        del _ALERTS[MAX_KEEP:]
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(_ALERTS, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


def _load_cache() -> None:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for a in data if isinstance(data, list) else []:
        if isinstance(a, dict) and {"id", "kind", "time_utc"} <= a.keys():
            _store(a)


def _consume_forever(client_id: str, client_secret: str) -> None:  # pragma: no cover - network loop
    try:
        from gcn_kafka import Consumer
    except ImportError:
        logger.warning("gcn-kafka not installed; GCN Kafka disabled")
        return
    consumer = Consumer(client_id=client_id, client_secret=client_secret)
    consumer.subscribe(["gcn.circulars"])
    while True:
        try:
            for message in consumer.consume(timeout=5):
                if message.error():
                    continue
                alert = circular_to_alert(json.loads(message.value()))
                if alert:
                    _store(alert)
        except Exception as exc:
            logger.warning("GCN Kafka error: %s", exc)


def start_consumer() -> None:
    """Start the Kafka consumer once, if credentials are configured (not under pytest)."""
    global _CONSUMER_STARTED
    if _CONSUMER_STARTED or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _CONSUMER_STARTED = True
    _load_cache()
    cid, secret = os.environ.get("GCN_CLIENT_ID", "").strip(), os.environ.get("GCN_CLIENT_SECRET", "").strip()
    if cid and secret:
        threading.Thread(target=_consume_forever, args=(cid, secret), daemon=True, name="gcn-kafka").start()


def fetch_gcn_alerts(limit: int = 20) -> list[dict[str, Any]]:
    """Newest-first real alerts (Kafka cache, then optional archive URL); [] when no source exists."""
    start_consumer()
    with _LOCK:
        if _ALERTS:
            return [dict(a) for a in _ALERTS[:limit]]
    url = os.environ.get("AEON_GCN_ARCHIVE_URL", "").strip()
    if url:
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(url)
            data = resp.json() if resp.status_code == 200 else None
            if isinstance(data, list):
                good = [a for a in data if isinstance(a, dict) and {"id", "kind", "time_utc"} <= a.keys()]
                good.sort(key=lambda a: str(a["time_utc"]), reverse=True)
                return good[:limit]
        except (httpx.HTTPError, ValueError):
            pass
    return []
