"""Beat (ictus) detection on a uniformly resampled, normalized trajectory segment.

A conducting beat is the *ictus*: the hand falls into a point, slows sharply
and rebounds upward. A candidate at index i is accepted only when ALL hold:

  1. speed[i] is a local minimum of the speed curve;
  2. the peak speed in the preceding approach window is >= min_approach_speed
     (a real stroke, not idle drift);
  3. speed[i] <= dip_ratio * that approach peak (a clear deceleration);
  4. mean vertical velocity before i is downward and after i is upward
     (direction reversal; this rejects the apex of the rebound, which is also
     a speed minimum but reverses from up to down);
  5. it is at least 60/max_bpm seconds after the previously accepted beat
     (stronger candidate wins inside the refractory window).

Not every extremum becomes a beat, and the refractory window bounds the
number of beats per second even for very noisy input.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import AnalysisConfig


@dataclass(frozen=True)
class BeatCandidate:
    t: float
    index: int
    x: float
    y: float
    strength: float      # approach peak speed minus ictus speed (normalized units / s)
    amplitude: float     # vertical drop from the highest point since the previous beat


def _velocity(t: np.ndarray, xy: np.ndarray) -> np.ndarray:
    return np.gradient(xy, t, axis=0)


def detect_beats(t: np.ndarray, xy: np.ndarray, cfg: AnalysisConfig, t_min: float = -np.inf,
                 t_max: float = np.inf) -> list[BeatCandidate]:
    """Detect beats in one uniform segment. Only beats with t_min < t <= t_max are returned."""
    t = np.asarray(t, dtype=float)
    xy = np.asarray(xy, dtype=float)
    n = len(t)
    if n < 5:
        return []
    dt = float(np.median(np.diff(t)))
    if dt <= 0:
        return []
    v = _velocity(t, xy)
    speed = np.linalg.norm(v, axis=1)
    w = max(2, int(round(cfg.window_s / dt)))
    wa = max(w, int(round(cfg.approach_window_s / dt)))

    raw: list[BeatCandidate] = []
    last_beat_idx = 0
    for i in range(w, n - w):
        if not (speed[i] <= speed[i - 1] and speed[i] <= speed[i + 1]):
            continue
        approach = float(np.max(speed[max(0, i - wa):i]))
        if approach < cfg.min_approach_speed:
            continue
        if speed[i] > cfg.dip_ratio * approach:
            continue
        vy_before = float(np.mean(v[i - w:i, 1]))
        vy_after = float(np.mean(v[i + 1:i + 1 + w, 1]))
        if not (vy_before < 0.0 < vy_after):
            continue
        top = float(np.max(xy[last_beat_idx:i + 1, 1]))
        raw.append(BeatCandidate(float(t[i]), i, float(xy[i, 0]), float(xy[i, 1]),
                                 approach - float(speed[i]), max(0.0, top - float(xy[i, 1]))))
        last_beat_idx = i

    # Refractory window: keep the strongest candidate among close neighbours.
    accepted: list[BeatCandidate] = []
    for c in raw:
        if accepted and c.t - accepted[-1].t < cfg.min_beat_interval_s:
            if c.strength > accepted[-1].strength:
                accepted[-1] = c
            continue
        accepted.append(c)
    return [c for c in accepted if t_min < c.t <= t_max]
