"""Dynamic Time Warping for multidimensional sequences.

Distance metric: Euclidean distance between points. Optional Sakoe-Chiba band
(widened to at least |n - m| so a path always exists). The reported
``normalized`` value is total cost divided by warping-path length, so longer
sequences do not automatically score worse. It is a raw shape distance, not a grade.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DTWResult:
    status: str                 # "ok" | "empty" | "invalid"
    distance: float | None      # accumulated cost along the optimal path
    normalized: float | None    # distance / path length
    path_length: int
    message: str = ""


def _as_sequence(a) -> np.ndarray | None:
    try:
        arr = np.asarray(a, dtype=float)
    except (TypeError, ValueError):
        return None
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.ndim != 2:
        return None
    return arr


def dtw(a, b, band: int | None = None) -> DTWResult:
    A, B = _as_sequence(a), _as_sequence(b)
    if A is None or B is None:
        return DTWResult("invalid", None, None, 0, "inputs must be numeric 1D or 2D sequences")
    if len(A) == 0 or len(B) == 0:
        return DTWResult("empty", None, None, 0, "empty sequence")
    if A.shape[1] != B.shape[1]:
        return DTWResult("invalid", None, None, 0, "dimension mismatch")
    if not (np.all(np.isfinite(A)) and np.all(np.isfinite(B))):
        return DTWResult("invalid", None, None, 0, "non-finite values")

    n, m = len(A), len(B)
    r = max(n, m) if band is None else max(int(band), abs(n - m))
    cost = np.sqrt(((A[:, None, :] - B[None, :, :]) ** 2).sum(axis=2))
    inf = math.inf
    D = np.full((n + 1, m + 1), inf)
    L = np.zeros((n + 1, m + 1), dtype=np.int64)   # path length of the chosen predecessor chain
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        j_lo = max(1, i - r)
        j_hi = min(m, i + r)
        for j in range(j_lo, j_hi + 1):
            choices = (D[i - 1, j - 1], D[i - 1, j], D[i, j - 1])
            k = int(np.argmin(choices))
            prev = choices[k]
            if prev == inf:
                continue
            D[i, j] = cost[i - 1, j - 1] + prev
            pi, pj = ((i - 1, j - 1), (i - 1, j), (i, j - 1))[k]
            L[i, j] = L[pi, pj] + 1
    total = float(D[n, m])
    if not math.isfinite(total):
        return DTWResult("invalid", None, None, 0, "no warping path inside band")
    length = int(L[n, m])
    return DTWResult("ok", total, total / length, length)
