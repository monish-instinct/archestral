"""Trajectory preprocessing pipeline.

Order (documented in docs/ARCHITECTURE.md):
  1. timestamp validation      - finite and strictly increasing
  2. invalid-sample rejection  - non-finite coords, out-of-range coords, low confidence
  3. coordinate normalization  - center + scale from calibration
  4. smoothing                 - One Euro filter (adaptive low-pass, keeps fast strokes sharp)
  5. gap handling              - gaps > threshold split segments; no interpolation across them
  6. resampling                - uniform rate inside each segment (linear interpolation)
  7. segmentation              - list of uniform segments
  8. template normalization    - see normalize_shape(), used by DTW
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from .config import AnalysisConfig
from .trajectory import Sample

COORD_LIMIT = 4.0  # accepted raw coordinate magnitude; anything larger is a tracking glitch


@dataclass
class ValidationReport:
    accepted: int = 0
    rejected_nonfinite: int = 0
    rejected_timestamp: int = 0
    rejected_range: int = 0
    rejected_confidence: int = 0

    @property
    def rejected(self) -> int:
        return self.rejected_nonfinite + self.rejected_timestamp + self.rejected_range + self.rejected_confidence


class SampleValidator:
    """Streaming validator. Keeps the last accepted timestamp so it works per-sample."""

    def __init__(self, min_confidence: float) -> None:
        self.min_confidence = min_confidence
        self.last_t: float | None = None
        self.report = ValidationReport()

    def check(self, s: Sample) -> str | None:
        """Return None if the sample is usable, else a rejection reason."""
        if not math.isfinite(s.t):
            self.report.rejected_timestamp += 1
            return "timestamp"
        if self.last_t is not None and s.t <= self.last_t:
            self.report.rejected_timestamp += 1
            return "timestamp"
        # A finite, increasing timestamp advances the clock even if the position
        # is unusable (e.g. "no hand in frame"), so gaps are measured correctly.
        self.last_t = s.t
        if not (math.isfinite(s.x) and math.isfinite(s.y) and math.isfinite(s.confidence)):
            self.report.rejected_nonfinite += 1
            return "nonfinite"
        if abs(s.x) > COORD_LIMIT or abs(s.y) > COORD_LIMIT:
            self.report.rejected_range += 1
            return "range"
        if s.confidence < self.min_confidence:
            self.report.rejected_confidence += 1
            return "confidence"
        self.report.accepted += 1
        return None


def validate_samples(samples: Sequence[Sample], min_confidence: float) -> tuple[list[Sample], ValidationReport]:
    v = SampleValidator(min_confidence)
    good = [s for s in samples if v.check(s) is None]
    return good, v.report


@dataclass
class Normalization:
    center: np.ndarray = field(default_factory=lambda: np.zeros(2))
    scale: float = 1.0

    def apply(self, xy: np.ndarray) -> np.ndarray:
        return (np.asarray(xy, dtype=float) - self.center) / self.scale

    def to_dict(self) -> dict:
        return {"center": [float(self.center[0]), float(self.center[1])], "scale": float(self.scale)}


def compute_normalization(xy: np.ndarray, min_range: float) -> Normalization | None:
    """Robust center/scale from calibration movement.

    center = per-axis midpoint of the 5th..95th percentile box,
    scale  = half of the larger percentile extent.
    Returns None when the movement is smaller than ``min_range`` (insufficient movement).
    """
    xy = np.asarray(xy, dtype=float)
    if xy.ndim != 2 or xy.shape[0] < 5:
        return None
    lo = np.percentile(xy, 5, axis=0)
    hi = np.percentile(xy, 95, axis=0)
    extent = float(np.max(hi - lo))
    if not math.isfinite(extent) or extent < min_range:
        return None
    return Normalization(center=(lo + hi) / 2.0, scale=extent / 2.0)


class OneEuroFilter:
    """One Euro filter for 2D points (Casiez, Roussel & Vogel, CHI 2012).

    Cutoff rises with speed, so slow jitter is removed while fast strokes keep
    their timing - important for not blurring beat points.
    """

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self) -> None:
        self._t: float | None = None
        self._x: np.ndarray | None = None
        self._dx = np.zeros(2)

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, t: float, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        if self._t is None or self._x is None:
            self._t, self._x = t, x.copy()
            return x.copy()
        dt = t - self._t
        if dt <= 0:
            return self._x.copy()
        dx = (x - self._x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self._dx = a_d * dx + (1 - a_d) * self._dx
        cutoff = self.min_cutoff + self.beta * float(np.linalg.norm(self._dx))
        a = self._alpha(cutoff, dt)
        self._x = a * x + (1 - a) * self._x
        self._t = t
        return self._x.copy()


def smooth(t: np.ndarray, xy: np.ndarray, cfg: AnalysisConfig) -> np.ndarray:
    f = OneEuroFilter(cfg.smoothing_min_cutoff_hz, cfg.smoothing_beta, cfg.smoothing_d_cutoff_hz)
    out = np.empty_like(np.asarray(xy, dtype=float))
    for i in range(len(t)):
        out[i] = f(float(t[i]), xy[i])
    return out


def split_segments(t: np.ndarray, gap_threshold: float) -> list[tuple[int, int]]:
    """Index ranges [start, end) with no internal gap larger than ``gap_threshold``."""
    n = len(t)
    if n == 0:
        return []
    breaks = np.nonzero(np.diff(t) > gap_threshold)[0] + 1
    starts = np.concatenate(([0], breaks))
    ends = np.concatenate((breaks, [n]))
    return [(int(s), int(e)) for s, e in zip(starts, ends)]


def find_gaps(t: np.ndarray, gap_threshold: float) -> list[tuple[float, float]]:
    d = np.diff(t)
    idx = np.nonzero(d > gap_threshold)[0]
    return [(float(t[i]), float(t[i + 1])) for i in idx]


def resample_uniform(t: np.ndarray, xy: np.ndarray, rate_hz: float) -> tuple[np.ndarray, np.ndarray]:
    """Linear resampling of one gap-free segment to a uniform rate."""
    t = np.asarray(t, dtype=float)
    xy = np.asarray(xy, dtype=float)
    if len(t) < 2:
        return t.copy(), xy.copy()
    step = 1.0 / rate_hz
    tu = np.arange(t[0], t[-1] + 1e-9, step)
    out = np.column_stack([np.interp(tu, t, xy[:, k]) for k in range(xy.shape[1])])
    return tu, out


def resample_n(xy: np.ndarray, n: int) -> np.ndarray:
    """Resample a sequence to exactly n points by index (time-uniform input assumed)."""
    xy = np.asarray(xy, dtype=float)
    if len(xy) == 0:
        raise ValueError("cannot resample an empty sequence")
    if len(xy) == 1:
        return np.repeat(xy, n, axis=0)
    src = np.linspace(0.0, 1.0, len(xy))
    dst = np.linspace(0.0, 1.0, n)
    return np.column_stack([np.interp(dst, src, xy[:, k]) for k in range(xy.shape[1])])


def normalize_shape(xy: np.ndarray) -> np.ndarray:
    """Translation/scale invariant shape: subtract mean, divide by RMS radius."""
    xy = np.asarray(xy, dtype=float)
    c = xy - xy.mean(axis=0)
    r = math.sqrt(float(np.mean(np.sum(c * c, axis=1))))
    if r < 1e-9:
        return c
    return c / r


@dataclass
class PreprocessResult:
    segments: list[tuple[np.ndarray, np.ndarray]]
    report: ValidationReport
    gaps: list[tuple[float, float]]


def preprocess(samples: Sequence[Sample], cfg: AnalysisConfig, norm: Normalization | None = None) -> PreprocessResult:
    """Batch pipeline (steps 1-7). Used for offline analysis and tests."""
    good, report = validate_samples(samples, cfg.min_confidence)
    if not good:
        return PreprocessResult([], report, [])
    t = np.array([s.t for s in good])
    xy = np.array([[s.x, s.y] for s in good])
    if norm is not None:
        xy = norm.apply(xy)
    gaps = find_gaps(t, cfg.gap_threshold_s)
    segments = []
    for s, e in split_segments(t, cfg.gap_threshold_s):
        ts, xs = t[s:e], smooth(t[s:e], xy[s:e], cfg)
        segments.append(resample_uniform(ts, xs, cfg.resample_hz))
    return PreprocessResult(segments, report, gaps)
