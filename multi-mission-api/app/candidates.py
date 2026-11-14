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


def _neutralise(text: Any, limit: int) -> str:
    """User text in issue bodies: no @mentions, no code fences, no rendered links, bounded length."""
    t = str(text or "")[:limit]
    t = t.replace("`", "'").replace("@", "@\u200b")
    return t.replace("http://", "hxxp://").replace("https://", "hxxps://")


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
        self._issue_times: list[float] = []
        self._seed_initial_candidates()

    def reset_for_tests(self) -> None:
        with self._lock:
            self._col.delete_many({})
            self._ip_hits.clear()
            self._issue_times.clear()
            self._seed_initial_candidates()

    def _seed_initial_candidates(self) -> None:
        """The pool starts empty: every entry must come from a real submission."""
        return

    def _issue_quota_ok(self) -> bool:
        """At most AEON_MAX_ISSUES_PER_HOUR automated issues per hour (default 3)."""
        limit = int(os.environ.get("AEON_MAX_ISSUES_PER_HOUR", "3"))
        now = time.time()
        self._issue_times = [t for t in self._issue_times if now - t < 3600.0]
        if len(self._issue_times) >= limit:
            return False
        self._issue_times.append(now)
        return True

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
                    if spec_data.get("snr_median") is not None:
                        cand["snr"] = float(spec_data["snr_median"])
                    matched = spec_data.get("matched_object") or {}
                    if matched.get("is_synthetic"):
                        is_synthetic = True
                    if matched.get("object_class") in OBJECT_CLASSES:
                        cand["object_class"] = matched["object_class"]
        except Exception:
            pass

        # Classification only from a real spectrum, never from a placeholder.
        if flux_ujy:
            try:
                with httpx.Client(timeout=2.0) as client:
                    cls_resp = client.post(f"{ai_url}/api/v1/ai/classify", json={"flux_ujy": flux_ujy})
                    if cls_resp.status_code == 200:
                        cls_data = cls_resp.json()
                        if not cand.get("object_class") and cls_data.get("top_class") in OBJECT_CLASSES:
                            cand["object_class"] = cls_data["top_class"]
                        if cls_data.get("anomaly_score") is not None:
                            cand["anomaly_score"] = float(cls_data["anomaly_score"])
            except Exception:
                pass

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

        if not self._issue_quota_ok():
            logger.warning("Issue quota reached; not opening an issue for %s", cand.get("id"))
            return None

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
            f"- **Gönderen:** `{_neutralise(cand.get('submitted_by', 'anonymous'), 64)}`\n"
            f"- **Notlar (kullanıcı metni):**\n\n```text\n{_neutralise(cand.get('notes', '-'), 1000)}\n```\n"
            f"- **AEON Gökyüzü Bağlantısı:** https://www.a-eon.engineer/?ra={ra:.5f}&dec={dec:.5f}\n"
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
            # Scores, class, votes, ids and issue links are server-side facts; client values are ignored.
            record: dict[str, Any] = {
                "id": f"cand-{uuid.uuid4().hex[:8]}",
                "ra": ra,
                "dec": dec,
                "object_class": None,
                "anomaly_score": None,
                "snr": None,
                "votes": 1,
                "submitted_by": str(candidate_data.get("submitted_by") or "citizen-scientist")[:64],
                "created_utc": now_iso,
                "github_issue_url": None,
                "notes": str(candidate_data.get("notes") or "")[:1000],
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
