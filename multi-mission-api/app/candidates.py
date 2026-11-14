"""Citizen-science candidate pool (MongoDB Atlas / mongomock) and autonomous GitHub Issue bot."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import threading
import time
import uuid
from typing import Any

import httpx
import mongomock
import pymongo

from .active_learning import get_aad_engine
from .crossmatch import angular_sep_arcsec

logger = logging.getLogger("aeon.candidates")

OBJECT_CLASSES = (
    "cold_brown_dwarf",
    "planet_x_candidate",
    "young_variable_star",
    "main_sequence_star",
    "high_z_galaxy",
)

# Synthetic target PX-2026-09 reference (heliocentric) and 2026-Q1 geocentric (Earth parallax) coordinates
PX_SYNTHETIC_POSITIONS: tuple[tuple[float, float], ...] = (
    (51.20000, 14.80000),
    (51.295473, 14.8325559),
)


class CandidateStore:
    """Thread-safe MongoDB Atlas or in-memory mongomock repository for citizen-science candidates."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        uri = os.environ.get("MONGODB_URI", "").strip()
        if uri and not os.environ.get("PYTEST_CURRENT_TEST"):
            self._client: Any = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
        else:
            self._client = mongomock.MongoClient()
        self._db = self._client["aeon"]
        self._col = self._db["candidates"]
        self._ip_hits: dict[str, list[float]] = {}
        self._seed_initial_candidates()

    def reset_for_tests(self) -> None:
        with self._lock:
            self._col.delete_many({})
            self._ip_hits.clear()
            self._seed_initial_candidates()

    def _seed_initial_candidates(self) -> None:
        if self._col.count_documents({}) > 0:
            return
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        seeds = [
            {
                "id": "cand-wise-0855",
                "ra": 133.7607,
                "dec": -7.24219,
                "object_class": "cold_brown_dwarf",
                "anomaly_score": 0.88,
                "snr": 18.4,
                "votes": 14,
                "submitted_by": "aeon-pipeline",
                "created_utc": now_iso,
                "github_issue_url": None,
                "notes": "WISE J085510.83-071442.5 (~250 K Y dwarf dipole in Q1-Q3 difference image).",
            },
            {
                "id": "cand-px-2026-09",
                "ra": 51.20312,
                "dec": 14.80163,
                "object_class": "planet_x_candidate",
                "anomaly_score": 0.94,
                "snr": 8.6,
                "votes": 21,
                "submitted_by": "aeon-synthetic-validator",
                "created_utc": now_iso,
                "github_issue_url": None,
                "notes": "[SYNTHETIC TEST CANDIDATE / is_synthetic=true] Injected Planet X test target PX-2026-09 recovered via shift-and-stack.",
            },
        ]
        self._col.insert_many(seeds)

    def check_rate_limit(self, client_ip: str) -> bool:
        with self._lock:
            limit = int(os.environ.get("AEON_RATE_LIMIT_PER_MIN", "60"))
            now = time.time()
            window = [t for t in self._ip_hits.get(client_ip, []) if now - t < 60.0]
            if len(window) >= limit:
                self._ip_hits[client_ip] = window
                return False
            window.append(now)
            self._ip_hits[client_ip] = window
            return True

    @staticmethod
    def _clean(doc: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in doc.items() if k != "_id"}
        out["active_priority_score"] = get_aad_engine().score_candidate(out)
        return out

    def list_candidates(self, sort: str = "votes", limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            sort_field = {
                "votes": ("votes", pymongo.DESCENDING),
                "recent": ("created_utc", pymongo.DESCENDING),
                "anomaly": ("anomaly_score", pymongo.DESCENDING),
            }.get(sort, ("votes", pymongo.DESCENDING))
            cursor = self._col.find({}).sort([sort_field]).limit(int(limit))
            return [self._clean(doc) for doc in cursor]

    def find_within_arcsec(self, ra: float, dec: float, max_sep_arcsec: float = 3.0) -> dict[str, Any] | None:
        with self._lock:
            for doc in self._col.find({}):
                sep = angular_sep_arcsec(ra, dec, float(doc["ra"]), float(doc["dec"]))
                if sep <= max_sep_arcsec:
                    return self._clean(doc)
            return None

    def _enrich_candidate(self, cand: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        ra = float(cand["ra"])
        dec = float(cand["dec"])
        core_url = os.environ.get("AEON_CORE_URL", "http://localhost:8000").rstrip("/")
        ai_url = os.environ.get("AEON_AI_URL", "http://localhost:8100").rstrip("/")

        notes_str = str(cand.get("notes") or "")
        near_px = any(
            angular_sep_arcsec(ra, dec, px_ra, px_dec) <= 600.0
            for px_ra, px_dec in PX_SYNTHETIC_POSITIONS
        )
        is_synthetic = bool(
            cand.get("is_synthetic")
            or "synthetic" in notes_str.lower()
            or "sentetik" in notes_str.lower()
            or "px-2026-09" in notes_str.lower()
            or near_px
        )

        flux_ujy: list[float] | None = None
        try:
            with httpx.Client(timeout=2.0) as client:
                spec_resp = client.get(f"{core_url}/api/v1/spectrum", params={"ra": ra, "dec": dec, "epoch": "2026-Q1"})
                if spec_resp.status_code == 200:
                    spec_data = spec_resp.json()
                    flux_ujy = spec_data.get("flux_ujy")
                    if cand.get("snr") is None and spec_data.get("snr_median") is not None:
                        cand["snr"] = float(spec_data["snr_median"])
                    matched = spec_data.get("matched_object") or {}
                    if matched.get("is_synthetic"):
                        is_synthetic = True
                    if not cand.get("object_class") and matched.get("object_class") in OBJECT_CLASSES:
                        cand["object_class"] = matched["object_class"]
        except Exception:
            pass

        if flux_ujy is not None or cand.get("object_class") is None or cand.get("anomaly_score") is None:
            try:
                with httpx.Client(timeout=2.0) as client:
                    payload = {"flux_ujy": flux_ujy} if flux_ujy else {"flux_ujy": [10.0] * 102}
                    cls_resp = client.post(f"{ai_url}/api/v1/ai/classify", json=payload)
                    if cls_resp.status_code == 200:
                        cls_data = cls_resp.json()
                        if not cand.get("object_class") and cls_data.get("top_class") in OBJECT_CLASSES:
                            cand["object_class"] = cls_data["top_class"]
                        if cand.get("anomaly_score") is None and cls_data.get("anomaly_score") is not None:
                            cand["anomaly_score"] = float(cls_data["anomaly_score"])
            except Exception:
                pass

        if cand.get("object_class") not in OBJECT_CLASSES:
            cand["object_class"] = "planet_x_candidate" if is_synthetic else "cold_brown_dwarf"
        if cand.get("anomaly_score") is None:
            cand["anomaly_score"] = 0.92 if is_synthetic else 0.65
        if cand.get("snr") is None:
            cand["snr"] = 6.5

        if is_synthetic and "is_synthetic" not in notes_str and "SYNTHETIC" not in notes_str.upper():
            cand["notes"] = f"[SYNTHETIC TEST CANDIDATE / is_synthetic=true] {notes_str}".strip()

        return cand, is_synthetic

    def _maybe_open_github_issue(self, cand: dict[str, Any], is_synthetic: bool) -> str | None:
        """Open a GitHub Issue on alpztel/aeon when anomaly_score >= 0.90 and snr >= 5.0."""
        anomaly = float(cand.get("anomaly_score") or 0.0)
        snr = float(cand.get("snr") or 0.0)
        if anomaly < 0.90 or snr < 5.0:
            return None
        if cand.get("github_issue_url"):
            return str(cand["github_issue_url"])

        token = os.environ.get("GITHUB_TOKEN", "").strip()
        repo = os.environ.get("GITHUB_REPO", "alpztel/aeon").strip() or "alpztel/aeon"
        ra = float(cand["ra"])
        dec = float(cand["dec"])
        obj_cls = str(cand.get("object_class", "unknown"))

        title = f"[Keşif adayı] AEON J{ra:08.4f}{dec:+08.4f} — {obj_cls}"
        labels = ["discovery", "automated"]
        synth_banner = ""
        if is_synthetic:
            labels.append("synthetic-test")
            synth_banner = (
                "> ⚠️ **SENTETİK TEST ADAYI (`is_synthetic: true`):** Bu kayıt gerçek gökyüzünde var olmayan, "
                "AEON algılama boru hattını doğrulamak amacıyla enjekte edilmiş sentetik bir test nesnesidir.\n\n"
            )

        body = (
            f"{synth_banner}"
            f"## AEON Otonom Keşif Adayı Raporu\n\n"
            f"- **Aday Kimliği:** `{cand['id']}`\n"
            f"- **Koordinat (ICRS):** `RA = {ra:.5f}°`, `Dec = {dec:+.5f}°`\n"
            f"- **Sınıf (`object_class`):** `{obj_cls}`\n"
            f"- **Anomali Skoru (`anomaly_score`):** `{anomaly:.4f}`\n"
            f"- **Sinyal/Gürültü (`snr`):** `{snr:.2f}`\n"
            f"- **Gönderen:** `{cand.get('submitted_by', 'anonymous')}`\n"
            f"- **Notlar:** {cand.get('notes', '-')}\n"
            f"- **AEON Gökyüzü Bağlantısı:** https://aeon.tech/?ra={ra:.5f}&dec={dec:.5f}\n"
        )

        if not token:
            logger.info("GITHUB_TOKEN not set; skipping GitHub Issue creation for %s (labels=%s)", title, labels)
            return None

        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"https://api.github.com/repos/{repo}/issues",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={"title": title, "body": body, "labels": labels},
                )
                if resp.status_code in (200, 201):
                    return resp.json().get("html_url")
        except Exception as exc:
            logger.warning("GitHub issue creation failed: %s", exc)
        return None

    def submit(self, candidate_data: dict[str, Any]) -> dict[str, Any]:
        ra = float(candidate_data["ra"])
        dec = float(candidate_data["dec"])

        with self._lock:
            # Atomic deduplication within <= 3 arcsec
            existing = self.find_within_arcsec(ra, dec, max_sep_arcsec=3.0)
            if existing is not None:
                return existing

            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            record: dict[str, Any] = {
                "id": str(candidate_data.get("id") or f"cand-{uuid.uuid4().hex[:8]}"),
                "ra": ra,
                "dec": dec,
                "object_class": candidate_data.get("object_class"),
                "anomaly_score": candidate_data.get("anomaly_score"),
                "snr": candidate_data.get("snr"),
                "votes": int(candidate_data.get("votes") if candidate_data.get("votes") is not None else 1),
                "submitted_by": str(candidate_data.get("submitted_by") or "citizen-scientist"),
                "created_utc": str(candidate_data.get("created_utc") or now_iso),
                "github_issue_url": candidate_data.get("github_issue_url"),
                "notes": str(candidate_data.get("notes") or ""),
            }

            record, is_synthetic = self._enrich_candidate(record)
            issue_url = self._maybe_open_github_issue(record, is_synthetic=is_synthetic)
            if issue_url:
                record["github_issue_url"] = issue_url

            self._col.insert_one(dict(record))
            return self._clean(record)

    def vote(self, candidate_id: str) -> dict[str, Any] | None:
        with self._lock:
            doc = self._col.find_one_and_update(
                {"id": candidate_id},
                {"$inc": {"votes": 1}},
                return_document=pymongo.ReturnDocument.AFTER,
            )
            if doc is None:
                return None
            get_aad_engine().update_from_vote(doc)
            return self._clean(doc)


_store: CandidateStore | None = None


def get_store() -> CandidateStore:
    global _store
    if _store is None:
        _store = CandidateStore()
    return _store
