"""Reference conducting patterns.

A pattern file (patterns/*.json) contains:
  * ``ictus``: ordered beat points (beat number, x, y) in a unit box, y up;
  * ``rebound``: how far the hand rises after each beat before travelling on;
  * ``points``: the derived reference trajectory for one bar, as
    [phase, x, y] rows with phase in [0, 1) and beat k at phase (k-1)/beats.

The trajectory is generated from the ictus/rebound description with cubic
Bezier strokes (each stroke leaves an ictus upward and falls into the next one
from above) and cosine easing, which gives the speed dip at every ictus that
the beat detector looks for. These are schematic textbook shapes, not motion
capture of a real conductor.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

PATTERN_DIR = Path(__file__).resolve().parents[2] / "patterns"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class ConductingPattern:
    id: str
    name: str
    beats_per_bar: int
    ictus: np.ndarray        # [beats, 2]
    rebound: np.ndarray      # [beats]
    approach: np.ndarray     # [beats] height the hand falls from into each ictus
    points: np.ndarray       # [n, 3] phase, x, y

    @property
    def xy(self) -> np.ndarray:
        return self.points[:, 1:3]

    def rotated(self, start_beat_index: int) -> np.ndarray:
        """Trajectory xy starting at beat ``start_beat_index`` (0-based) and wrapping around."""
        phase0 = start_beat_index / self.beats_per_bar
        ph = (self.points[:, 0] - phase0) % 1.0
        order = np.argsort(ph, kind="stable")
        return self.xy[order]

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "id": self.id,
            "name": self.name,
            "beats_per_bar": self.beats_per_bar,
            "coordinate_space": "unit box, x right, y up",
            "ictus": [{"beat": i + 1, "x": round(float(p[0]), 4), "y": round(float(p[1]), 4),
                       "rebound": round(float(self.rebound[i]), 4), "approach": round(float(self.approach[i]), 4)}
                      for i, p in enumerate(self.ictus)],
            "points": [[round(float(a), 5), round(float(b), 5), round(float(c), 5)] for a, b, c in self.points],
        }


def _ease(s: np.ndarray) -> np.ndarray:
    return (1.0 - np.cos(np.pi * s)) / 2.0


def stroke(p0, p1, rebound: float, approach: float, s: np.ndarray) -> np.ndarray:
    """Cubic Bezier from ictus p0 to ictus p1 with eased parameter s in [0, 1]."""
    p0 = np.asarray(p0, float)
    p1 = np.asarray(p1, float)
    c1 = p0 + np.array([0.0, rebound])
    c2 = p1 + np.array([0.0, approach])
    u = _ease(s)[:, None]
    return ((1 - u) ** 3) * p0 + 3 * ((1 - u) ** 2) * u * c1 + 3 * (1 - u) * u * u * c2 + (u ** 3) * p1


def build_points(ictus: np.ndarray, rebound: np.ndarray, approach: np.ndarray, per_beat: int = 32) -> np.ndarray:
    beats = len(ictus)
    rows = []
    s = np.arange(per_beat) / per_beat
    for k in range(beats):
        nxt = (k + 1) % beats
        seg = stroke(ictus[k], ictus[nxt], rebound[k], approach[nxt], s)
        phase = (k + s) / beats
        rows.append(np.column_stack([phase, seg]))
    return np.vstack(rows)


def make_pattern(pid: str, name: str, ictus, rebound, approach, per_beat: int = 32) -> ConductingPattern:
    ictus = np.asarray(ictus, float)
    rebound = np.asarray(rebound, float)
    approach = np.asarray(approach, float)
    return ConductingPattern(pid, name, len(ictus), ictus, rebound, approach,
                             build_points(ictus, rebound, approach, per_beat))


# Built-in schematic patterns. 4/4 is the primary supported exercise.
BUILTIN_SPECS = {
    "4-4": ("4/4 (common time)", [(0.0, -0.75), (-0.65, -0.55), (0.7, -0.55), (0.15, -0.35)],
            [0.45, 0.35, 0.40, 1.25], [1.6, 0.35, 0.30, 0.30]),
    "3-4": ("3/4 (waltz)", [(0.0, -0.75), (0.65, -0.55), (0.15, -0.35)],
            [0.45, 0.40, 1.25], [1.6, 0.35, 0.30]),
    "2-4": ("2/4 (march)", [(0.0, -0.75), (0.2, -0.45)],
            [0.55, 1.25], [1.6, 0.35]),
}


def builtin_pattern(pid: str) -> ConductingPattern:
    name, ictus, rebound, approach = BUILTIN_SPECS[pid]
    return make_pattern(pid, name, ictus, rebound, approach)


def pattern_from_dict(d: dict) -> ConductingPattern:
    """Validate and load a pattern definition (untrusted JSON)."""
    if not isinstance(d, dict):
        raise ValueError("pattern must be an object")
    pid = d.get("id")
    if not isinstance(pid, str) or not _ID_RE.match(pid):
        raise ValueError("pattern id must match [a-z0-9_-]")
    beats = d.get("beats_per_bar")
    if not isinstance(beats, int) or not (1 <= beats <= 12):
        raise ValueError("beats_per_bar must be an integer 1..12")
    ictus = d.get("ictus")
    if not isinstance(ictus, list) or len(ictus) != beats:
        raise ValueError("ictus must list one entry per beat")
    ordered = sorted(ictus, key=lambda e: e.get("beat", 0) if isinstance(e, dict) else 0)
    if [e.get("beat") for e in ordered] != list(range(1, beats + 1)):
        raise ValueError("ictus beats must be numbered 1..beats_per_bar")
    vals = [[e["x"], e["y"], e["rebound"], e["approach"]] for e in ordered]
    arr = np.asarray(vals, float)
    if not np.all(np.isfinite(arr)) or np.any(np.abs(arr) > 3):
        raise ValueError("ictus values must be finite and within [-3, 3]")
    return make_pattern(pid, str(d.get("name", pid))[:64], arr[:, :2], arr[:, 2], arr[:, 3])


def load_patterns(directory: Path = PATTERN_DIR) -> dict[str, ConductingPattern]:
    """Load pattern files; fall back to built-ins for anything missing or invalid."""
    out = {pid: builtin_pattern(pid) for pid in BUILTIN_SPECS}
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                p = pattern_from_dict(json.loads(path.read_text(encoding="utf-8")))
                out[p.id] = p
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
    return out


def ideal_trajectory(pattern: ConductingPattern, bpm: float, bars: int, rate_hz: float,
                     center=(0.5, 0.5), size: float = 0.25, t0: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Time-stamped trajectory of the pattern at a given tempo (used for synthetic fixtures)."""
    period = 60.0 / bpm
    duration = bars * pattern.beats_per_bar * period
    t = t0 + np.arange(0.0, duration, 1.0 / rate_hz)
    rel = (t - t0) / period
    beat_idx = np.floor(rel).astype(int) % pattern.beats_per_bar
    s = rel - np.floor(rel)
    xy = np.empty((len(t), 2))
    for k in range(pattern.beats_per_bar):
        m = beat_idx == k
        if not np.any(m):
            continue
        nxt = (k + 1) % pattern.beats_per_bar
        xy[m] = stroke(pattern.ictus[k], pattern.ictus[nxt], pattern.rebound[k], pattern.approach[nxt], s[m])
    return t, np.asarray(center, float) + xy * size


def beat_times(bpm: float, bars: int, beats_per_bar: int, t0: float = 0.0) -> list[float]:
    period = 60.0 / bpm
    return [t0 + i * period for i in range(bars * beats_per_bar)]


def is_valid_id(pid: str) -> bool:
    return isinstance(pid, str) and bool(_ID_RE.match(pid))
