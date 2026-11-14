"""SPHEREx-like 102-band definition (single source of truth for band centres).

Six detector arrays, 17 channels each, log-spaced within the array. Array edges and
resolving powers follow the published SPHEREx design (R~41 for 0.75-2.42 um, R~35 for
2.42-3.82 um, R~110 for 3.82-4.42 um, R~130 for 4.42-5.00 um).
"""

from __future__ import annotations

import numpy as np

ARRAY_EDGES_UM = (0.75, 1.11, 1.64, 2.42, 3.82, 4.42, 5.00)
RESOLVING_POWER = (41.0, 41.0, 41.0, 35.0, 110.0, 130.0)
CHANNELS_PER_ARRAY = 17
N_BANDS = CHANNELS_PER_ARRAY * len(RESOLVING_POWER)

# 5-sigma point-source depth per band in AB mag (all-sky survey, single 6-month pass).
DEPTH_5SIGMA_AB = 19.5


def _build() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    centres, widths, arrays = [], [], []
    for i in range(len(RESOLVING_POWER)):
        lo, hi = ARRAY_EDGES_UM[i], ARRAY_EDGES_UM[i + 1]
        edges = np.geomspace(lo, hi, CHANNELS_PER_ARRAY + 1)
        centres.append(np.sqrt(edges[:-1] * edges[1:]))
        widths.append(np.diff(edges))
        arrays.append(np.full(CHANNELS_PER_ARRAY, i + 1))
    return np.concatenate(centres), np.concatenate(widths), np.concatenate(arrays)


WAVELENGTH_UM, BANDWIDTH_UM, ARRAY_ID = _build()


def ab_to_ujy(mag: float | np.ndarray) -> float | np.ndarray:
    """AB magnitude -> microjansky."""
    return 3631e6 * 10 ** (-0.4 * np.asarray(mag))


def ujy_to_ab(flux: float | np.ndarray) -> float | np.ndarray:
    return -2.5 * np.log10(np.maximum(np.asarray(flux, dtype=float), 1e-12) / 3631e6)


# 1-sigma point-source noise per band in uJy.
POINT_SOURCE_SIGMA_UJY = float(ab_to_ujy(DEPTH_5SIGMA_AB)) / 5.0

assert N_BANDS == 102 and WAVELENGTH_UM.shape == (102,)
