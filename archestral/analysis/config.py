"""Analysis configuration with validated, documented defaults.

All distances are in *normalized* units: after calibration the user's movement
is centered and divided by half of its larger extent, so a typical conducting
pattern spans roughly [-1, 1] on each axis. Speeds are normalized units / s.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass
class AnalysisConfig:
    # --- sample validation ---
    min_confidence: float = 0.5          # samples below this are treated as tracking loss
    gap_threshold_s: float = 0.25        # larger gaps split the trajectory into segments
    lost_timeout_s: float = 0.6          # no valid samples for this long -> "tracking lost"

    # --- smoothing (One Euro filter, Casiez et al. 2012) ---
    smoothing_min_cutoff_hz: float = 2.5
    smoothing_beta: float = 0.4
    smoothing_d_cutoff_hz: float = 1.0

    # --- calibration ---
    calibration_s: float = 2.0           # movement collected before analysis starts
    min_movement_range: float = 0.04     # in raw input units (0..1 image space)
    small_movement_scale: float = 0.07   # calibrated half-extent below this -> "move closer" hint

    # --- resampling ---
    resample_hz: float = 60.0

    # --- beat detection ---
    min_approach_speed: float = 1.2      # normalized units / s
    dip_ratio: float = 0.55              # speed at ictus must be <= ratio * approach peak
    window_s: float = 0.12               # pre/post window to measure direction reversal
    approach_window_s: float = 0.35      # how far back to look for the stroke's peak speed
    speed_smoothing_s: float = 0.05      # moving-average window on the speed curve
    adaptive_ratio: float = 0.2         # approach peak must reach this x the user's p90 stroke speed
    vertical_ratio: float = 0.2          # required upward change in vertical velocity, x approach peak
    detection_lookahead_s: float = 0.15  # latency before a beat candidate is finalized
    min_bpm: float = 30.0
    max_bpm: float = 200.0

    # --- tempo ---
    tempo_window: int = 8                # rolling number of intervals
    min_intervals_for_tempo: int = 3
    tempo_refractory_ratio: float = 0.6  # once tempo is known, ignore beats sooner than this x period

    # --- similarity ---
    dtw_points: int = 64
    dtw_band: float = 0.25               # Sakoe-Chiba band as fraction of length
    similarity_scale: float = 0.35       # d at which estimate = exp(-1) ~ 0.37 (uncalibrated)

    # --- feedback ---
    target_bpm: float = 90.0
    feedback_interval_s: float = 0.2
    buffer_s: float = 10.0

    @property
    def min_beat_interval_s(self) -> float:
        return 60.0 / self.max_bpm

    @property
    def max_beat_interval_s(self) -> float:
        return 60.0 / self.min_bpm

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# (min, max) bounds for every numeric field; values outside are rejected.
_BOUNDS: dict[str, tuple[float, float]] = {
    "min_confidence": (0.0, 1.0),
    "gap_threshold_s": (0.02, 2.0),
    "lost_timeout_s": (0.1, 5.0),
    "smoothing_min_cutoff_hz": (0.1, 30.0),
    "smoothing_beta": (0.0, 10.0),
    "smoothing_d_cutoff_hz": (0.1, 30.0),
    "calibration_s": (0.5, 10.0),
    "min_movement_range": (0.001, 0.5),
    "small_movement_scale": (0.0, 0.5),
    "resample_hz": (20.0, 240.0),
    "min_approach_speed": (0.05, 20.0),
    "dip_ratio": (0.05, 0.95),
    "window_s": (0.03, 0.5),
    "approach_window_s": (0.05, 1.5),
    "speed_smoothing_s": (0.0, 0.3),
    "adaptive_ratio": (0.0, 0.9),
    "vertical_ratio": (0.0, 2.0),
    "detection_lookahead_s": (0.05, 0.6),
    "min_bpm": (20.0, 120.0),
    "max_bpm": (60.0, 300.0),
    "tempo_window": (2, 64),
    "min_intervals_for_tempo": (1, 32),
    "tempo_refractory_ratio": (0.0, 0.9),
    "dtw_points": (8, 512),
    "dtw_band": (0.0, 1.0),
    "similarity_scale": (0.01, 10.0),
    "target_bpm": (20.0, 300.0),
    "feedback_interval_s": (0.05, 2.0),
    "buffer_s": (3.0, 60.0),
}


def config_from_dict(data: dict[str, Any] | None, base: AnalysisConfig | None = None) -> tuple[AnalysisConfig, list[str]]:
    """Build a config from untrusted data. Invalid entries are ignored and reported."""
    cfg = AnalysisConfig(**asdict(base)) if base else AnalysisConfig()
    problems: list[str] = []
    if not data:
        return cfg, problems
    if not isinstance(data, dict):
        return cfg, ["analysis config must be an object"]
    known = {f.name: f for f in fields(AnalysisConfig)}
    for key, value in data.items():
        if key not in known:
            problems.append(f"unknown analysis setting '{key}'")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"'{key}' must be a number")
            continue
        lo, hi = _BOUNDS[key]
        if not (lo <= float(value) <= hi):
            problems.append(f"'{key}'={value} outside [{lo}, {hi}]")
            continue
        setattr(cfg, key, int(value) if known[key].type in ("int", int) else float(value))
    if cfg.min_bpm >= cfg.max_bpm:
        problems.append("min_bpm must be below max_bpm; restored defaults")
        cfg.min_bpm, cfg.max_bpm = AnalysisConfig.min_bpm, AnalysisConfig.max_bpm
    return cfg, problems
