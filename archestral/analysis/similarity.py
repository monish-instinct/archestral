"""Gesture similarity between the user's most recent bar and a reference pattern.

Procedure:
  1. take the trajectory between the last ``beats_per_bar + 1`` detected beats
     (exactly one bar of the user's own tempo);
  2. resample both it and the template to ``dtw_points`` points and apply
     shape normalization (mean removed, divided by RMS radius);
  3. the bar may start on any beat, so DTW is run against every rotation of
     the template; the best rotation also yields a beat-in-bar labelling;
  4. the length-normalized DTW distance d is mapped linearly between two
     measured anchors and clipped to [0, 1]:
         estimate = (d_random - d) / (d_random - d_perfect)
     d_perfect (~0.03) is a clean textbook bar; d_random (~0.63) is the median
     distance of smooth random hand motion. So 0 means "no closer to the pattern
     than random movement" and 1 means "matches the textbook shape".

The estimate is a *prototype gesture-similarity indicator*. The anchors are
measured on synthetic data, not calibrated against human expert ratings, so it
must not be read as an accuracy percentage or grade. Real conductors' patterns
vary legitimately from the schematic template.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dtw import dtw
from .patterns import ConductingPattern
from .preprocessing import normalize_shape, resample_n


@dataclass(frozen=True)
class SimilarityResult:
    status: str                    # "ok" | "insufficient_data" | "invalid"
    normalized_distance: float | None
    estimate: float | None
    start_beat: int | None         # beat number (1-based) the analysed bar started on


def gesture_similarity(user_xy: np.ndarray, pattern: ConductingPattern, n_points: int,
                       band_fraction: float, d_perfect: float = 0.03, d_random: float = 0.63) -> SimilarityResult:
    user_xy = np.asarray(user_xy, dtype=float)
    if user_xy.ndim != 2 or len(user_xy) < 8:
        return SimilarityResult("insufficient_data", None, None, None)
    if not np.all(np.isfinite(user_xy)):
        return SimilarityResult("invalid", None, None, None)
    u = normalize_shape(resample_n(user_xy, n_points))
    band = max(1, int(round(band_fraction * n_points)))
    best: tuple[float, int] | None = None
    for k in range(pattern.beats_per_bar):
        ref = normalize_shape(resample_n(pattern.rotated(k), n_points))
        r = dtw(u, ref, band)
        if r.status == "ok" and (best is None or r.normalized < best[0]):
            best = (float(r.normalized), k)
    if best is None:
        return SimilarityResult("invalid", None, None, None)
    d, k = best
    estimate = min(1.0, max(0.0, (d_random - d) / (d_random - d_perfect)))
    return SimilarityResult("ok", d, estimate, k + 1)
