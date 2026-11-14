"""Astro-LLM function-calling dispatcher and bilingual (TR/EN) rule-based fallback parser."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

UI_ACTION_TYPES = (
    "FLY_TO",
    "SET_EPOCH",
    "TOGGLE_DIFF",
    "RUN_SHIFT_STACK",
    "RUN_BLIND_SEARCH",
    "OPEN_SPECTRUM",
    "OPEN_3D_ORBIT",
    "OPEN_JWST",
    "OPEN_CROSSMATCH",
    "SET_COLORMAP",
    "SET_LANG",
    "GENERATE_PDF",
    "START_DEMO_TOUR",
)

# Reference coordinates at 2026-Q1 for offline fallback when AEON_CORE_URL is unreachable.
KNOWN_TARGETS: dict[str, dict[str, Any]] = {
    "wise-0855": {
        "id": "wise-0855",
        "name": "WISE J085510.83-071442.5",
        "ra": 133.7607,
        "dec": -7.24219,
        "object_class": "cold_brown_dwarf",
        "is_synthetic": False,
        "patterns": (r"wise[\s\-]*0855", r"w0855", r"0855"),
    },
    "rw-aur": {
        "id": "rw-aur",
        "name": "RW Aurigae",
        "ra": 76.95642,
        "dec": 30.40142,
        "object_class": "young_variable_star",
        "is_synthetic": False,
        "patterns": (r"rw[\s\-]*aur(?:igae)?", r"hd[\s\-]*240764"),
    },
    "px-2026-09": {
        "id": "px-2026-09",
        "name": "PX-2026-09",
        "ra": 51.295473,
        "dec": 14.8325559,
        "object_class": "planet_x_candidate",
        "is_synthetic": True,
        "rate_arcsec_yr": 110.0,
        "pa_deg": 62.0,
        "distance_au": 520.0,
        "patterns": (
            r"px[\s\-]*2026[\s\-]*09",
            r"planet[\s\-]*(?:x|9|nine)",
            r"gezegen[\s\-]*(?:x|9|dokuz)",
        ),
    },
    "luhman-16": {
        "id": "luhman-16",
        "name": "Luhman 16",
        "ra": 162.3077,
        "dec": -53.31686,
        "object_class": "cold_brown_dwarf",
        "is_synthetic": False,
        "patterns": (r"luhman[\s\-]*16", r"wise[\s\-]*1049"),
    },
    "wise-1828": {
        "id": "wise-1828",
        "name": "WISEPA J182831.08+265037.8",
        "ra": 277.13447,
        "dec": 26.84459,
        "object_class": "cold_brown_dwarf",
        "is_synthetic": False,
        "patterns": (r"wise[\s\-]*1828", r"1828"),
    },
    "barnard": {
        "id": "barnard",
        "name": "Barnard's Star",
        "ra": 269.44631,
        "dec": 4.76818,
        "object_class": "main_sequence_star",
        "is_synthetic": False,
        "patterns": (r"barnard", r"gj[\s\-]*699"),
    },
    "tw-hya": {
        "id": "tw-hya",
        "name": "TW Hydrae",
        "ra": 165.46587,
        "dec": -34.70473,
        "object_class": "young_variable_star",
        "is_synthetic": False,
        "patterns": (r"tw[\s\-]*hya", r"tw[\s\-]*hydrae"),
    },
    "18-sco": {
        "id": "18-sco",
        "name": "18 Scorpii",
        "ra": 243.90529,
        "dec": -8.36944,
        "object_class": "main_sequence_star",
        "is_synthetic": False,
        "patterns": (r"18[\s\-]*sco(?:rpii)?", r"hd[\s\-]*146233"),
    },
}

SYSTEM_PROMPT = (
    "You are AEON Astro-LLM, the astrophysical assistant for the AEON discovery OS "
    "(NASA Space Apps Challenge 2026: Planet X and SPHEREx). "
    "Convert the user's Turkish (tr) or English (en) command into ordered UI tool calls. "
    "Demo targets: wise-0855 (cold brown dwarf), rw-aur (young variable star), and "
    "px-2026-09 (injected synthetic test candidate, is_synthetic=true — always state that it is synthetic). "
    "Coordinates are ICRS degrees (ra 0..360, dec -90..90), fluxes uJy, wavelengths um. "
    "Never invent coordinates: call search_catalog first when a target is named."
)


def _tool_def(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required or list(properties.keys()),
            "additionalProperties": False,
        },
    }


LLM_TOOLS: list[dict[str, Any]] = [
    # Knowledge tools (executed on server)
    _tool_def(
        "search_catalog",
        "Search the AEON core catalog by object name or query string.",
        {"q": {"type": "string"}},
        ["q"],
    ),
    _tool_def(
        "get_spectrum",
        "Fetch the 102-band SPHEREx spectrum at (ra, dec) from the core backend.",
        {"ra": {"type": "number"}, "dec": {"type": "number"}, "epoch": {"type": "string", "enum": ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]}},
        ["ra", "dec", "epoch"],
    ),
    _tool_def(
        "crossmatch",
        "Query multi-mission Gaia DR3 / WISE / MAST crossmatch at (ra, dec).",
        {"ra": {"type": "number"}, "dec": {"type": "number"}, "radius_arcsec": {"type": "number"}},
        ["ra", "dec", "radius_arcsec"],
    ),
    # UI Action tools (collected into actions[])
    _tool_def(
        "FLY_TO",
        "Slew the sky map to target coordinates or target_id.",
        {"ra": {"type": "number"}, "dec": {"type": "number"}, "target_id": {"type": "string"}, "name": {"type": "string"}},
        ["ra", "dec", "target_id", "name"],
    ),
    _tool_def(
        "SET_EPOCH",
        "Switch the active survey quarter epoch.",
        {"epoch": {"type": "string", "enum": ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]}},
        ["epoch"],
    ),
    _tool_def(
        "TOGGLE_DIFF",
        "Enable or toggle image differencing I(t2)-I(t1).",
        {
            "enabled": {"type": "boolean"},
            "epoch_1": {"type": "string", "enum": ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]},
            "epoch_2": {"type": "string", "enum": ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]},
        },
        ["enabled", "epoch_1", "epoch_2"],
    ),
    _tool_def(
        "RUN_SHIFT_STACK",
        "Run digital shift-and-stack along a trial motion vector.",
        {"rate_arcsec_yr": {"type": "number"}, "pa_deg": {"type": "number"}, "distance_au": {"type": ["number", "null"]}},
        ["rate_arcsec_yr", "pa_deg", "distance_au"],
    ),
    _tool_def(
        "RUN_BLIND_SEARCH",
        "Run the 5x5 blind velocity grid search for moving objects.",
        {"grid": {"type": "integer"}},
        ["grid"],
    ),
    _tool_def(
        "OPEN_SPECTRUM",
        "Open the 102-band infrared spectrum analyser panel.",
        {"ra": {"type": ["number", "null"]}, "dec": {"type": ["number", "null"]}, "target_id": {"type": ["string", "null"]}},
        ["ra", "dec", "target_id"],
    ),
    _tool_def(
        "OPEN_3D_ORBIT",
        "Open the 3D solar system and REBOUND orbit forecast view.",
        {"target_id": {"type": ["string", "null"]}, "horizons_years": {"type": "array", "items": {"type": "number"}}},
        ["target_id", "horizons_years"],
    ),
    _tool_def(
        "OPEN_JWST",
        "Open the JWST/HST MAST picture-in-picture overlay.",
        {"ra": {"type": ["number", "null"]}, "dec": {"type": ["number", "null"]}},
        ["ra", "dec"],
    ),
    _tool_def(
        "OPEN_CROSSMATCH",
        "Open the Gaia DR3 + WISE multi-mission crossmatch and SED panel.",
        {"ra": {"type": ["number", "null"]}, "dec": {"type": ["number", "null"]}, "radius_arcsec": {"type": "number"}},
        ["ra", "dec", "radius_arcsec"],
    ),
    _tool_def(
        "SET_COLORMAP",
        "Change the active FITS image colormap.",
        {"colormap": {"type": "string", "enum": ["inferno", "viridis", "magma", "grayscale"]}},
        ["colormap"],
    ),
    _tool_def(
        "SET_LANG",
        "Switch the UI language between Turkish (tr) and English (en).",
        {"lang": {"type": "string", "enum": ["tr", "en"]}},
        ["lang"],
    ),
    _tool_def(
        "GENERATE_PDF",
        "Generate and download the AEON PDF Discovery Report.",
        {"include_spectrum": {"type": "boolean"}},
        ["include_spectrum"],
    ),
    _tool_def(
        "START_DEMO_TOUR",
        "Start the guided Jury Demo Tour across wise-0855, rw-aur, and synthetic px-2026-09.",
        {"step": {"type": "integer"}},
        ["step"],
    ),
]


def tr_lower(text: str) -> str:
    """Lower-case for TR/EN matching: 'İ' -> 'i' (no combining dot), other letters as usual."""
    return text.replace("\u0130", "i").lower().replace("\u0307", "")


def detect_lang(message: str, explicit_lang: str | None = None) -> str:
    if explicit_lang in ("tr", "en"):
        return explicit_lang
    text = tr_lower(message)
    tr_chars = any(ch in text for ch in "çğıöşü")
    tr_words = re.search(
        r"\b(git|uç|fark|modu|modunu|aç|kapat|yığ|tayf|spektrum|yörünge|rapor|tur|başlat|renk|dönem|kör|tarama|eşleştir|göster|dil|türkçe|ingilizce|gezegen)\b",
        text,
    )
    if tr_chars or tr_words:
        return "tr"
    return "en"


def _lookup_catalog_remote_or_local(query: str) -> dict[str, Any] | None:
    core_url = os.environ.get("AEON_CORE_URL", "http://localhost:8000").rstrip("/")
    try:
        with httpx.Client(timeout=1.5) as client:
            resp = client.get(f"{core_url}/api/v1/catalog/search", params={"q": query, "limit": 1})
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results") or []
                if results:
                    return results[0]
    except Exception:
        pass
    q_low = query.lower()
    for tid, info in KNOWN_TARGETS.items():
        if tid == q_low or any(re.search(pat, q_low) for pat in info["patterns"]):
            return dict(info)
    return None


def _execute_knowledge_tool(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    core_url = os.environ.get("AEON_CORE_URL", "http://localhost:8000").rstrip("/")
    missions_url = os.environ.get("AEON_MISSIONS_URL", "http://localhost:8200").rstrip("/")
    try:
        with httpx.Client(timeout=2.5) as client:
            if name == "search_catalog":
                q = str(tool_input.get("q", ""))
                hit = _lookup_catalog_remote_or_local(q)
                return {"results": [hit] if hit else [], "count": 1 if hit else 0}
            if name == "get_spectrum":
                resp = client.get(
                    f"{core_url}/api/v1/spectrum",
                    params={
                        "ra": tool_input.get("ra", 133.795),
                        "dec": tool_input.get("dec", -7.245),
                        "epoch": tool_input.get("epoch", "2026-Q1"),
                    },
                )
                if resp.status_code == 200:
                    spec = resp.json()
                    return {
                        "snr_median": spec.get("snr_median"),
                        "matched_object": spec.get("matched_object"),
                        "absorption_features": spec.get("absorption_features", []),
                    }
            if name == "crossmatch":
                resp = client.get(
                    f"{missions_url}/api/v1/missions/crossmatch",
                    params={
                        "ra": tool_input.get("ra", 133.795),
                        "dec": tool_input.get("dec", -7.245),
                        "radius_arcsec": tool_input.get("radius_arcsec", 6.0),
                    },
                )
                if resp.status_code == 200:
                    return resp.json()
    except Exception as exc:
        return {"status": "offline_fallback", "detail": str(exc)}
    return {"status": "ok"}


def _extract_target(text: str) -> dict[str, Any] | None:
    low = text.lower().replace("i\u0307", "i")
    for tid, info in KNOWN_TARGETS.items():
        if any(re.search(pat, low) for pat in info["patterns"]):
            remote = _lookup_catalog_remote_or_local(tid)
            if remote:
                merged = dict(info)
                merged.update({k: v for k, v in remote.items() if v is not None})
                return merged
            return dict(info)
    return None


def _parse_sexagesimal(text: str) -> tuple[float, float] | None:
    """Parse HMS + DMS coordinates such as '08h55m10.83s -07d14m42.5s' or '05:07:49.54 +30:24:05.1'."""
    m_hms = re.search(
        r"\b([0-2]?[0-9])\s*[h:]\s*([0-5][0-9])\s*[m:]\s*([0-5][0-9](?:\.[0-9]+)?)\s*s?\s+"
        r"([+\-])\s*([0-8]?[0-9]|90)\s*[d°:]\s*([0-5][0-9])\s*[m':]\s*([0-5][0-9](?:\.[0-9]+)?)\s*[s\"]?",
        text,
        re.IGNORECASE,
    )
    if not m_hms:
        return None
    rh, rm, rs = float(m_hms.group(1)), float(m_hms.group(2)), float(m_hms.group(3))
    sign = -1.0 if m_hms.group(4) == "-" else 1.0
    dd, dm, ds = float(m_hms.group(5)), float(m_hms.group(6)), float(m_hms.group(7))
    if rh >= 24.0 or dd > 90.0 or (dd == 90.0 and (dm > 0 or ds > 0)):
        return None
    ra_deg = round(15.0 * (rh + rm / 60.0 + rs / 3600.0), 6)
    dec_deg = round(sign * (dd + dm / 60.0 + ds / 3600.0), 6)
    if 0.0 <= ra_deg <= 360.0 and -90.0 <= dec_deg <= 90.0:
        return ra_deg, dec_deg
    return None


def _extract_coords(text: str) -> tuple[float, float] | None:
    sexag = _parse_sexagesimal(text)
    if sexag is not None:
        return sexag
    m_labeled = re.search(
        r"ra\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*[,;/\s]+\s*dec\s*[:=]?\s*([+\-]?[0-9]+(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    )
    if m_labeled:
        ra, dec = float(m_labeled.group(1)), float(m_labeled.group(2))
        if 0.0 <= ra <= 360.0 and -90.0 <= dec <= 90.0:
            return ra, dec
    m_pair = re.search(
        r"(?:koordinat|coordinates?|konum|at|to)\s*[:(\s]+([0-9]{1,3}(?:\.[0-9]+)?)\s*[,;\s]\s*([+\-]?[0-9]{1,2}(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    )
    if m_pair:
        ra, dec = float(m_pair.group(1)), float(m_pair.group(2))
        if 0.0 <= ra <= 360.0 and -90.0 <= dec <= 90.0:
            return ra, dec
    m_bare = re.match(
        r"^\s*([0-9]{1,3}\.[0-9]+)\s*[,;\s]+\s*([+\-]?[0-9]{1,2}\.[0-9]+)\s*$",
        text,
    )
    if m_bare:
        ra, dec = float(m_bare.group(1)), float(m_bare.group(2))
        if 0.0 <= ra <= 360.0 and -90.0 <= dec <= 90.0:
            return ra, dec
    return None


def parse_rule_based(message: str, lang: str | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deterministic bilingual (TR/EN) command parser used when ANTHROPIC_API_KEY is absent or LLM fails."""
    resolved_lang = detect_lang(message, lang)
    ctx = context or {}
    text = message.strip()
    low = tr_lower(text)

    target = _extract_target(text)
    coords = _extract_coords(text)

    # Fallback to context target if no explicit target or coordinate is in the message
    ctx_target_id = ctx.get("target_id") or ctx.get("selected_target")
    if target is None and coords is None and isinstance(ctx_target_id, str) and ctx_target_id in KNOWN_TARGETS:
        ctx_t = dict(KNOWN_TARGETS[ctx_target_id])
    else:
        ctx_t = None

    ra = target["ra"] if target else (coords[0] if coords else (ctx.get("ra") if ctx.get("ra") is not None else (ctx_t["ra"] if ctx_t else None)))
    dec = target["dec"] if target else (coords[1] if coords else (ctx.get("dec") if ctx.get("dec") is not None else (ctx_t["dec"] if ctx_t else None)))
    target_id = target["id"] if target else (ctx_target_id if isinstance(ctx_target_id, str) else None)

    candidates: list[tuple[int, dict[str, Any]]] = []

    def add_action(match: re.Match[str] | None, action_type: str, params: dict[str, Any]) -> None:
        if match is not None:
            candidates.append((match.start(), {"type": action_type, "params": params}))

    # 1. FLY_TO
    m_fly = re.search(
        r"\b(git|uç|odaklan|merkezle|bul|göster|fly\s*to|go\s*to|slew\s*to|navigate\s*to|center\s*on|focus\s*on|point\s*to)\b",
        low,
    )
    if target is not None:
        pos = m_fly.start() if m_fly else 0
        candidates.append(
            (
                pos,
                {
                    "type": "FLY_TO",
                    "params": {
                        "target_id": target["id"],
                        "name": target["name"],
                        "ra": float(target["ra"]),
                        "dec": float(target["dec"]),
                        "is_synthetic": bool(target.get("is_synthetic", False)),
                    },
                },
            )
        )
    elif coords is not None:
        pos = m_fly.start() if m_fly else 0
        candidates.append(
            (
                pos,
                {
                    "type": "FLY_TO",
                    "params": {"ra": float(coords[0]), "dec": float(coords[1])},
                },
            )
        )

    # 2. TOGGLE_DIFF (check before SET_EPOCH so Q1 vs Q3 in diff doesn't double-fire unless requested)
    m_diff = re.search(
        r"(fark\s*modu|görüntü\s*fark|fark[ıi]\s*(?:aç|göster|hesapla)|fark\s*al|difference\s*mode|image\s*differenc|toggle\s*diff|subtract\s*frames|\bdiff\b)",
        low,
    )
    epochs_in_text = re.findall(r"(?:2026[\s\-]*)?q([1-4])", low, re.IGNORECASE)
    if m_diff:
        ep1 = f"2026-Q{epochs_in_text[0]}" if len(epochs_in_text) >= 1 else "2026-Q1"
        ep2 = f"2026-Q{epochs_in_text[1]}" if len(epochs_in_text) >= 2 else "2026-Q3"
        enabled = not bool(re.search(r"\b(kapat|gizle|disable|off|hide)\b", low))
        add_action(m_diff, "TOGGLE_DIFF", {"enabled": enabled, "epoch_1": ep1, "epoch_2": ep2})

    # 3. SET_EPOCH
    m_epoch = re.search(r"(?:2026[\s\-]*)?q([1-4])\b", low)
    if m_epoch and (not m_diff or len(epochs_in_text) == 1):
        add_action(m_epoch, "SET_EPOCH", {"epoch": f"2026-Q{m_epoch.group(1)}"})

    # 4. RUN_SHIFT_STACK
    m_stack = re.search(
        r"(kaydır[\s\-]*ve[\s\-]*yığ|kaydır\s*yığ|yığma|shift[\s\-]*(?:and[\s\-]*)?stack|\bstack\b)",
        low,
    )
    if m_stack:
        rate_m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:\"|''|arcsec|yay\s*saniye)", low)
        pa_m = re.search(r"(?:pa|ka|açı|angle)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)", low)
        dist_m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*au\b", low)
        rate_val = float(rate_m.group(1)) if rate_m else float(target.get("rate_arcsec_yr", 110.0) if target else 110.0)
        pa_val = float(pa_m.group(1)) if pa_m else float(target.get("pa_deg", 62.0) if target else 62.0)
        dist_val = float(dist_m.group(1)) if dist_m else (float(target["distance_au"]) if target and target.get("distance_au") else 520.0)
        # Enforce physical bounds matching backend AnalysisRequest
        rate_val = max(0.0, min(5000.0, rate_val))
        pa_val = round(pa_val % 360.0, 4)
        dist_val = max(1.0, min(1e6, dist_val))
        add_action(
            m_stack,
            "RUN_SHIFT_STACK",
            {"rate_arcsec_yr": rate_val, "pa_deg": pa_val, "distance_au": dist_val},
        )

    # 5. RUN_BLIND_SEARCH
    m_blind = re.search(
        r"(kör\s*(?:hız\s*)?tarama|kör\s*arama|hız\s*ızgara|blind\s*(?:velocity\s*)?search|grid\s*search|5x5)",
        low,
    )
    if m_blind:
        add_action(m_blind, "RUN_BLIND_SEARCH", {"grid": 5})

    # 6. OPEN_SPECTRUM
    m_spec = re.search(
        r"(tayf|spektrum|102[\s\-]*bant|soğurma|spectrum|spectral|sonification|sonifikasyon)",
        low,
    )
    if m_spec:
        spec_params: dict[str, Any] = {}
        if ra is not None and dec is not None:
            spec_params["ra"] = float(ra)
            spec_params["dec"] = float(dec)
        if target_id:
            spec_params["target_id"] = target_id
        add_action(m_spec, "OPEN_SPECTRUM", spec_params)

    # 7. OPEN_3D_ORBIT
    m_orbit = re.search(
        r"(3d|3\s*boyut|yörünge|rebound|güneş\s*sistemi|orbit|trajectory|solar\s*system)",
        low,
    )
    if m_orbit:
        orb_params: dict[str, Any] = {"horizons_years": [1, 5, 10]}
        if target_id:
            orb_params["target_id"] = target_id
        add_action(m_orbit, "OPEN_3D_ORBIT", orb_params)

    # 8. OPEN_JWST
    m_jwst = re.search(r"(jwst|james\s*webb|hubble|\bhst\b|picture[\s\-]*in[\s\-]*picture|\bpip\b)", low)
    if m_jwst:
        jwst_params: dict[str, Any] = {}
        if ra is not None and dec is not None:
            jwst_params["ra"] = float(ra)
            jwst_params["dec"] = float(dec)
        add_action(m_jwst, "OPEN_JWST", jwst_params)

    # 9. OPEN_CROSSMATCH
    m_xmatch = re.search(
        r"(çapraz\s*eşleş|eşleştir|gaia|catwise|allwise|\bsed\b|cross[\s\-]*match|multi[\s\-]*mission|archival)",
        low,
    )
    if m_xmatch:
        xm_params: dict[str, Any] = {"radius_arcsec": 6.0}
        if ra is not None and dec is not None:
            xm_params["ra"] = float(ra)
            xm_params["dec"] = float(dec)
        add_action(m_xmatch, "OPEN_CROSSMATCH", xm_params)

    # 10. SET_COLORMAP
    m_cmap = re.search(r"\b(inferno|viridis|magma|grayscale|gri\s*ton(?:lama)?)\b", low)
    if m_cmap:
        raw_cmap = m_cmap.group(1)
        cmap = "grayscale" if raw_cmap.startswith("gri") else raw_cmap
        add_action(m_cmap, "SET_COLORMAP", {"colormap": cmap})

    # 11. SET_LANG
    m_lang = re.search(
        r"(türkçe(?:'ye|\s*yap|\s*dil|\s*geç)?|ingilizce(?:'ye|\s*yap|\s*dil|\s*geç)?|switch\s*to\s*(?:turkish|english)|language\s*(?:to\s*)?(?:tr|en|turkish|english)|\bset\s*lang(?:uage)?\s*(?:to\s*)?(?:tr|en)\b)",
        low,
    )
    if m_lang:
        token = m_lang.group(0)
        new_lang = "tr" if ("türk" in token or "turkish" in token or token.endswith("tr")) else "en"
        add_action(m_lang, "SET_LANG", {"lang": new_lang})

    # 12. GENERATE_PDF
    m_pdf = re.search(r"(\bpdf\b|keşif\s*rapor|rapor\s*(?:oluştur|indir|üret|hazırla)|discovery\s*report|generate\s*report|export\s*pdf)", low)
    if m_pdf:
        add_action(m_pdf, "GENERATE_PDF", {"include_spectrum": True})

    # 13. START_DEMO_TOUR
    m_tour = re.search(r"(demo\s*tur|jüri\s*tur|turu?\s*başlat|tanıtım\s*tur|demo\s*tour|guided\s*tour|start\s*tour|jury\s*tour)", low)
    if m_tour:
        add_action(m_tour, "START_DEMO_TOUR", {"step": 0})

    # Sort by position in text and deduplicate by action type while preserving order
    candidates.sort(key=lambda item: item[0])
    actions: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for _, act in candidates:
        if act["type"] not in seen_types:
            seen_types.add(act["type"])
            actions.append(act)

    synth_note_tr = (
        " (Not: PX-2026-09 gerçek gökyüzünde bulunmayan, boru hattını doğrulamak için enjekte edilmiş sentetik bir test adayıdır; is_synthetic=true.)"
        if target and target.get("is_synthetic")
        else ""
    )
    synth_note_en = (
        " (Note: PX-2026-09 is an injected synthetic test candidate used to validate the pipeline; is_synthetic=true.)"
        if target and target.get("is_synthetic")
        else ""
    )

    if resolved_lang == "tr":
        if actions:
            summary = ", ".join(a["type"] for a in actions)
            target_str = f" Hedef: {target['name']}." if target else ""
            reply = f"[Kural tabanlı mod] Komut ayrıştırıldı ve {len(actions)} aksiyon üretildi ({summary}).{target_str}{synth_note_tr}"
        else:
            reply = (
                "[Kural tabanlı mod] Komutta doğrudan bir arayüz aksiyonu tespit edilemedi. "
                "Örnek: 'WISE 0855'e git ve fark modunu aç' veya 'PX-2026-09 için kör tarama çalıştır'."
            )
    else:
        if actions:
            summary = ", ".join(a["type"] for a in actions)
            target_str = f" Target: {target['name']}." if target else ""
            reply = f"[Rule-based fallback mode] Parsed command into {len(actions)} UI action(s) ({summary}).{target_str}{synth_note_en}"
        else:
            reply = (
                "[Rule-based fallback mode] No specific UI action matched. "
                "Try: 'Fly to WISE 0855 and toggle difference mode' or 'Run blind search on PX-2026-09'."
            )

    return {"reply": reply, "lang": resolved_lang, "actions": actions}


def run_command_dispatcher(
    message: str,
    lang: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute Astro-LLM via Anthropic Claude function calling when ANTHROPIC_API_KEY is set,
    falling back cleanly to the deterministic bilingual rule-based parser."""
    resolved_lang = detect_lang(message, lang)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return parse_rule_based(message, resolved_lang, context)

    try:
        import anthropic

        model_name = os.environ.get("AEON_LLM_MODEL", "claude-opus-5-5").strip() or "claude-opus-5-5"
        client = anthropic.Anthropic(api_key=api_key)

        user_content = message
        if context:
            user_content = f"Context: {json.dumps(context, ensure_ascii=False)}\nUser ({resolved_lang}): {message}"

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
        ui_actions: list[dict[str, Any]] = []
        reply_parts: list[str] = []

        for _ in range(3):
            kwargs: dict[str, Any] = {
                "model": model_name,
                "max_tokens": 1024,
                "system": SYSTEM_PROMPT,
                "tools": LLM_TOOLS,
                "tool_choice": {"type": "auto"},
                "messages": messages,
                "output_config": {"effort": "low"},
            }
            try:
                response = client.messages.create(**kwargs)
            except TypeError:
                # In case an older SDK version does not accept output_config
                kwargs.pop("output_config", None)
                response = client.messages.create(**kwargs)

            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason == "refusal":
                refusal_msg = (
                    "[Astro-LLM] Bu isteği güvenlik politikaları nedeniyle yerine getiremiyorum."
                    if resolved_lang == "tr"
                    else "[Astro-LLM] I cannot fulfill this request due to safety policies."
                )
                return {"reply": refusal_msg, "lang": resolved_lang, "actions": []}

            assistant_blocks: list[Any] = []
            tool_results: list[dict[str, Any]] = []

            for block in getattr(response, "content", []):
                btype = getattr(block, "type", None)
                if btype == "text":
                    text_val = getattr(block, "text", "")
                    if text_val:
                        reply_parts.append(text_val)
                    assistant_blocks.append({"type": "text", "text": text_val})
                elif btype == "tool_use":
                    tname = getattr(block, "name", "")
                    tinput = dict(getattr(block, "input", {}) or {})
                    tid = getattr(block, "id", "tool_1")
                    assistant_blocks.append({"type": "tool_use", "id": tid, "name": tname, "input": tinput})
                    if tname in UI_ACTION_TYPES:
                        clean_params = {k: v for k, v in tinput.items() if v is not None}
                        ui_actions.append({"type": tname, "params": clean_params})
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tid,
                                "content": json.dumps({"queued_ui_action": tname}),
                            }
                        )
                    else:
                        k_res = _execute_knowledge_tool(tname, tinput)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tid,
                                "content": json.dumps(k_res, ensure_ascii=False),
                            }
                        )

            if not tool_results or stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        if not ui_actions:
            fallback = parse_rule_based(message, resolved_lang, context)
            ui_actions = fallback["actions"]

        final_reply = " ".join(reply_parts).strip()
        if not final_reply:
            summary = ", ".join(a["type"] for a in ui_actions) if ui_actions else "OK"
            final_reply = (
                f"[Astro-LLM · {model_name}] Komut işlendi ({summary})."
                if resolved_lang == "tr"
                else f"[Astro-LLM · {model_name}] Command processed ({summary})."
            )
        elif "[Astro-LLM" not in final_reply:
            final_reply = f"[Astro-LLM · {model_name}] {final_reply}"

        return {"reply": final_reply, "lang": resolved_lang, "actions": ui_actions}
    except Exception:
        return parse_rule_based(message, resolved_lang, context)
