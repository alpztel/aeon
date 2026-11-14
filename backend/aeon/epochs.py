"""Survey epochs (quarters) and decimal-year helpers."""

from __future__ import annotations

EPOCHS: dict[str, float] = {
    "2026-Q1": 2026.125,
    "2026-Q2": 2026.375,
    "2026-Q3": 2026.625,
    "2026-Q4": 2026.875,
}
DEFAULT_EPOCH = "2026-Q1"
SURVEY_START = 2026.0
SURVEY_END = 2027.0


def epoch_year(epoch: str) -> float:
    try:
        return EPOCHS[epoch]
    except KeyError as exc:
        raise ValueError(f"Unknown epoch {epoch!r}; expected one of {list(EPOCHS)}") from exc
