"""Shared trajectory representation used by every input source.

Coordinate convention (all sources): normalized 2D, x to the right, y UP,
nominally in [0, 1]. Webcam sources convert from image space (y down);
mouse and WebXR sources map into the same space before sending.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class Sample:
    t: float               # seconds, monotonic clock of the producing source
    x: float
    y: float
    confidence: float = 1.0

    def is_finite(self) -> bool:
        return all(math.isfinite(v) for v in (self.t, self.x, self.y, self.confidence))


def samples_to_arrays(samples: Sequence[Sample]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (t[n], xy[n,2], confidence[n]) as float64 arrays."""
    n = len(samples)
    t = np.empty(n)
    xy = np.empty((n, 2))
    c = np.empty(n)
    for i, s in enumerate(samples):
        t[i] = s.t
        xy[i, 0] = s.x
        xy[i, 1] = s.y
        c[i] = s.confidence
    return t, xy, c


def samples_from_rows(rows: Iterable[Sequence[float]]) -> list[Sample]:
    """Build samples from [t, x, y, confidence?] rows (fixture and protocol format)."""
    out = []
    for row in rows:
        if len(row) < 3:
            raise ValueError("sample row needs at least t, x, y")
        conf = float(row[3]) if len(row) > 3 else 1.0
        out.append(Sample(float(row[0]), float(row[1]), float(row[2]), conf))
    return out
