"""Tempo estimation and timing metrics.

BPM = 60 / T where T is the median of the most recent valid beat intervals.
Intervals outside [60/max_bpm, 60/min_bpm] are rejected as implausible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class TempoEstimate:
    bpm: float | None
    intervals_used: int
    intervals_rejected: int
    status: str   # "ok" | "insufficient_beats"


def estimate_tempo(beat_times: Sequence[float], min_bpm: float, max_bpm: float,
                   window: int = 8, min_intervals: int = 3) -> TempoEstimate:
    times = [float(b) for b in beat_times if math.isfinite(b)]
    if len(times) < 2:
        return TempoEstimate(None, 0, 0, "insufficient_beats")
    intervals = np.diff(np.asarray(times))
    lo, hi = 60.0 / max_bpm, 60.0 / min_bpm
    valid = intervals[(intervals >= lo) & (intervals <= hi)]
    rejected = int(len(intervals) - len(valid))
    recent = valid[-window:]
    if len(recent) < min_intervals:
        return TempoEstimate(None, int(len(recent)), rejected, "insufficient_beats")
    period = float(np.median(recent))
    return TempoEstimate(60.0 / period, int(len(recent)), rejected, "ok")


def tempo_deviation_percent(estimated_bpm: float | None, target_bpm: float | None) -> float | None:
    """((estimated - target) / target) * 100. None when either value is missing or invalid."""
    if estimated_bpm is None or target_bpm is None:
        return None
    if not (math.isfinite(estimated_bpm) and math.isfinite(target_bpm)) or target_bpm <= 0:
        return None
    return (estimated_bpm - target_bpm) / target_bpm * 100.0


def beat_timing_error_ms(beat_times: Sequence[float], target_bpm: float | None) -> float | None:
    """Mean absolute offset (ms) of beats from a target-tempo grid.

    The grid phase is the circular mean of all beat phases, so the score does
    not depend on which beat happened to come first. Requires >= 2 beats.
    """
    if target_bpm is None or not math.isfinite(target_bpm) or target_bpm <= 0:
        return None
    times = np.asarray([b for b in beat_times if math.isfinite(b)], dtype=float)
    if len(times) < 2:
        return None
    period = 60.0 / target_bpm
    angles = 2 * math.pi * (times % period) / period
    anchor = math.atan2(float(np.mean(np.sin(angles))), float(np.mean(np.cos(angles))))
    offsets = (angles - anchor + math.pi) % (2 * math.pi) - math.pi
    return float(np.mean(np.abs(offsets)) / (2 * math.pi) * period * 1000.0)
