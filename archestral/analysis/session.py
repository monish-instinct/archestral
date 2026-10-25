"""Streaming conducting-session analyzer.

Every input source (webcam, mouse, WebXR controller, recorded test fixture)
feeds ``SessionAnalyzer.push`` with the same ``Sample`` type, so the analysis
algorithm exists exactly once.

States: idle -> calibrating -> running <-> paused -> stopped
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .beats import detect_beats
from .config import AnalysisConfig
from .patterns import ConductingPattern
from .preprocessing import Normalization, OneEuroFilter, SampleValidator, compute_normalization, resample_uniform
from .similarity import gesture_similarity
from .tempo import beat_timing_error_ms, estimate_tempo, tempo_deviation_percent
from .trajectory import Sample

SIMILARITY_LABEL = "prototype gesture-similarity estimate (uncalibrated)"
STATES = ("idle", "calibrating", "running", "paused", "stopped")
_DETECT_EVERY_S = 1.0 / 30.0
_MOVEMENT_WINDOW_S = 2.0
_MIN_RUNNING_EXTENT = 0.25   # normalized units over the movement window


@dataclass
class BeatEvent:
    index: int
    t: float
    beat_in_bar: int | None
    confidence: float
    amplitude: float
    x: float
    y: float

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "t": round(self.t, 4), "beat_in_bar": self.beat_in_bar,
                "confidence": round(self.confidence, 3), "amplitude": round(self.amplitude, 3),
                "x": round(self.x, 4), "y": round(self.y, 4)}


@dataclass
class _Stats:
    duration_s: float = 0.0
    invalid_intervals: list[tuple[float, float]] = field(default_factory=list)
    similarity_values: list[float] = field(default_factory=list)
    tempo_history: list[tuple[float, float]] = field(default_factory=list)
    confidence_sum: float = 0.0
    confidence_n: int = 0


class SessionAnalyzer:
    def __init__(self, cfg: AnalysisConfig, pattern: ConductingPattern) -> None:
        self.cfg = cfg
        self.pattern = pattern
        self.state = "idle"
        self._reset_all()

    # ------------------------------------------------------------------ control
    def _reset_all(self) -> None:
        self.validator = SampleValidator(self.cfg.min_confidence)
        self.filter = OneEuroFilter(self.cfg.smoothing_min_cutoff_hz, self.cfg.smoothing_beta,
                                    self.cfg.smoothing_d_cutoff_hz)
        self.norm: Normalization | None = None
        self._calib: list[tuple[float, float, float]] = []
        self._calib_start: float | None = None
        self._buf: deque[tuple[float, float, float]] = deque()   # t, nx, ny (normalized, smoothed)
        self._recent_conf: deque[tuple[float, float]] = deque()
        self.beats: list[BeatEvent] = []
        self._segment_beats: list[BeatEvent] = []
        self._last_valid_t: float | None = None
        self._prev_t: float | None = None
        self._last_detect_t = -math.inf
        self._last_feedback_t = -math.inf
        self._insufficient = False
        self._similarity = None
        self.stats = _Stats()

    def start(self) -> list[dict]:
        self._reset_all()
        self.state = "calibrating"
        return [self._state_event("Calibrating: conduct a few bars so the range of your movement can be measured.")]

    def recalibrate(self) -> list[dict]:
        if self.state not in ("running", "calibrating"):
            return []
        self.norm = None
        self._calib.clear()
        self._calib_start = None
        self._buf.clear()
        self._segment_beats.clear()
        self.filter.reset()
        self.state = "calibrating"
        return [self._state_event("Recalibrating.")]

    def pause(self) -> list[dict]:
        if self.state not in ("running", "calibrating"):
            return []
        self._paused_from = self.state
        self.state = "paused"
        return [self._state_event("Paused.")]

    def resume(self) -> list[dict]:
        if self.state != "paused":
            return []
        self.state = getattr(self, "_paused_from", "running")
        self._break_segment()
        self._prev_t = None
        self._last_valid_t = None
        return [self._state_event("Resumed.")]

    def stop(self) -> list[dict]:
        if self.state in ("idle", "stopped"):
            return []
        self.state = "stopped"
        return [self._state_event("Session stopped."), {"type": "summary", **self.summary()}]

    def set_target_bpm(self, bpm: float) -> None:
        if math.isfinite(bpm) and 20 <= bpm <= 300:
            self.cfg.target_bpm = float(bpm)

    def set_pattern(self, pattern: ConductingPattern) -> None:
        self.pattern = pattern
        self._segment_beats.clear()
        self._similarity = None

    # ------------------------------------------------------------------ input
    def push(self, s: Sample) -> list[dict]:
        events: list[dict] = []
        if self.state not in ("calibrating", "running"):
            if self.state == "paused":
                self.validator.check(s)   # keep the clock monotonic while paused
            return events

        reason = self.validator.check(s)
        if reason == "timestamp":
            return events
        if self._prev_t is not None:
            self.stats.duration_s += max(0.0, s.t - self._prev_t)
        self._prev_t = s.t
        conf = s.confidence if reason is None and math.isfinite(s.confidence) else 0.0
        self._recent_conf.append((s.t, conf))
        while self._recent_conf and s.t - self._recent_conf[0][0] > 1.0:
            self._recent_conf.popleft()
        self.stats.confidence_sum += conf
        self.stats.confidence_n += 1
        if reason is not None:
            events += self._maybe_feedback(s.t)
            return events

        if self._last_valid_t is not None and s.t - self._last_valid_t > self.cfg.gap_threshold_s:
            self.stats.invalid_intervals.append((self._last_valid_t, s.t))
            self._break_segment()
        self._last_valid_t = s.t

        if self.state == "calibrating":
            events += self._calibrate(s)
        else:
            self._append_running(s)
            if s.t - self._last_detect_t >= _DETECT_EVERY_S:
                self._last_detect_t = s.t
                events += self._detect()
        events += self._maybe_feedback(s.t)
        return events

    def _break_segment(self) -> None:
        self._buf.clear()
        self._segment_beats.clear()
        self.filter.reset()

    def _calibrate(self, s: Sample) -> list[dict]:
        if self._calib_start is None:
            self._calib_start = s.t
        self._calib.append((s.t, s.x, s.y))
        if s.t - self._calib_start < self.cfg.calibration_s:
            return []
        xy = np.array([[x, y] for _, x, y in self._calib])
        norm = compute_normalization(xy, self.cfg.min_movement_range)
        if norm is None:
            self._insufficient = True
            self._calib.clear()
            self._calib_start = s.t
            return [self._state_event("Not enough movement to calibrate. Conduct larger gestures.")]
        self.norm = norm
        self._insufficient = False
        self.state = "running"
        # Seed the analysis buffer with the calibration movement so the first
        # beats after calibration have context; beats inside it are not emitted.
        self._analysis_start = s.t
        for t, x, y in self._calib[-int(self.cfg.resample_hz * 1.5):]:
            self._append_running(Sample(t, x, y))
        self._calib.clear()
        return [self._state_event("Calibrated. Analysis running."),
                {"type": "calibration", "normalization": norm.to_dict()}]

    def _append_running(self, s: Sample) -> None:
        assert self.norm is not None
        p = self.filter(s.t, self.norm.apply([s.x, s.y]))
        self._buf.append((s.t, float(p[0]), float(p[1])))
        while self._buf and s.t - self._buf[0][0] > self.cfg.buffer_s:
            self._buf.popleft()

    # ------------------------------------------------------------------ analysis
    def _buffer_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        arr = np.asarray(self._buf, dtype=float)
        return arr[:, 0], arr[:, 1:3]

    def _detect(self) -> list[dict]:
        if len(self._buf) < 10:
            return []
        t, xy = self._buffer_arrays()
        self._update_movement_flag(t, xy)
        tu, xyu = resample_uniform(t, xy, self.cfg.resample_hz)
        t_min = self._analysis_start
        if self.beats:
            t_min = max(t_min, self.beats[-1].t + self.cfg.min_beat_interval_s * 0.999)
        t_max = t[-1] - self.cfg.detection_lookahead_s
        events = []
        for c in detect_beats(tu, xyu, self.cfg, t_min=t_min, t_max=t_max):
            if self.beats and c.t - self.beats[-1].t < self.cfg.min_beat_interval_s:
                continue
            ev = BeatEvent(len(self.beats) + 1, c.t, None, self._confidence(), c.amplitude, c.x, c.y)
            self.beats.append(ev)
            self._segment_beats.append(ev)
            self._update_similarity(tu, xyu)
            ev.beat_in_bar = self._label_beat()
            tempo = self._tempo()
            if tempo.bpm is not None:
                self.stats.tempo_history.append((c.t, tempo.bpm))
            events.append({"type": "beat", **ev.to_dict()})
        return events

    def _update_movement_flag(self, t: np.ndarray, xy: np.ndarray) -> None:
        m = t >= t[-1] - _MOVEMENT_WINDOW_S
        if np.count_nonzero(m) < 5:
            return
        extent = float(np.max(np.ptp(xy[m], axis=0)))
        self._insufficient = extent < _MIN_RUNNING_EXTENT

    def _update_similarity(self, tu: np.ndarray, xyu: np.ndarray) -> None:
        bpb = self.pattern.beats_per_bar
        if len(self._segment_beats) < bpb + 1:
            return
        t0, t1 = self._segment_beats[-(bpb + 1)].t, self._segment_beats[-1].t
        m = (tu >= t0) & (tu <= t1)
        res = gesture_similarity(xyu[m], self.pattern, self.cfg.dtw_points, self.cfg.dtw_band,
                                 self.cfg.similarity_scale)
        self._similarity = res
        if res.status == "ok" and res.estimate is not None:
            self.stats.similarity_values.append(res.estimate)

    def _label_beat(self) -> int | None:
        bpb = self.pattern.beats_per_bar
        sim = self._similarity
        if sim is not None and sim.status == "ok" and len(self._segment_beats) >= bpb + 1 \
                and sim.start_beat is not None:
            return sim.start_beat   # the analysed bar ends on the same beat it starts on
        if len(self.beats) >= 2 and self.beats[-2].beat_in_bar is not None:
            return self.beats[-2].beat_in_bar % bpb + 1
        return None

    def _confidence(self) -> float:
        if not self._recent_conf:
            return 0.0
        return float(np.mean([c for _, c in self._recent_conf]))

    def _tempo(self):
        return estimate_tempo([b.t for b in self.beats], self.cfg.min_bpm, self.cfg.max_bpm,
                              self.cfg.tempo_window, self.cfg.min_intervals_for_tempo)

    def tracking_state(self, t: float | None = None) -> str:
        if self._last_valid_t is None:
            return "waiting"
        ref = t if t is not None else (self._prev_t or self._last_valid_t)
        return "lost" if ref - self._last_valid_t > self.cfg.lost_timeout_s else "tracking"

    def _maybe_feedback(self, t: float) -> list[dict]:
        if t - self._last_feedback_t < self.cfg.feedback_interval_s:
            return []
        self._last_feedback_t = t
        return [{"type": "feedback", **self.metrics(t)}]

    # ------------------------------------------------------------------ reporting
    def metrics(self, t: float | None = None) -> dict[str, Any]:
        tempo = self._tempo()
        recent = [b.t for b in self.beats[-(self.cfg.tempo_window + 1):]]
        sim = self._similarity
        calib_progress = 1.0 if self.norm is not None else (
            0.0 if self._calib_start is None or not self._calib else
            min(1.0, (self._calib[-1][0] - self._calib_start) / self.cfg.calibration_s))
        return {
            "state": self.state,
            "pattern": self.pattern.id,
            "tracking": self.tracking_state(t),
            "calibrated": self.norm is not None,
            "calibration_progress": round(calib_progress, 3),
            "insufficient_movement": self._insufficient,
            "target_bpm": self.cfg.target_bpm,
            "estimated_bpm": None if tempo.bpm is None else round(tempo.bpm, 2),
            "tempo_status": tempo.status,
            "tempo_deviation_pct": _round(tempo_deviation_percent(tempo.bpm, self.cfg.target_bpm), 2),
            "beat_timing_error_ms": _round(beat_timing_error_ms(recent, self.cfg.target_bpm), 1),
            "similarity": {
                "estimate": None if sim is None else _round(sim.estimate, 3),
                "normalized_distance": None if sim is None else _round(sim.normalized_distance, 4),
                "status": "insufficient_data" if sim is None else sim.status,
                "label": SIMILARITY_LABEL,
            },
            "tracking_confidence": round(self._confidence(), 3),
            "session_duration_s": round(self.stats.duration_s, 2),
            "beat_count": len(self.beats),
            "invalid_intervals": len(self.stats.invalid_intervals),
            "invalid_time_s": round(sum(b - a for a, b in self.stats.invalid_intervals), 2),
            "rejected_samples": self.validator.report.rejected,
        }

    def summary(self) -> dict[str, Any]:
        m = self.metrics()
        r = self.validator.report
        sims = self.stats.similarity_values
        bpb = self.pattern.beats_per_bar
        return {
            **m,
            "similarity_mean": _round(float(np.mean(sims)) if sims else None, 3),
            "similarity_bars": len(sims),
            "mean_tracking_confidence": _round(
                self.stats.confidence_sum / self.stats.confidence_n if self.stats.confidence_n else None, 3),
            "rejected": {"timestamp": r.rejected_timestamp, "nonfinite": r.rejected_nonfinite,
                         "range": r.rejected_range, "low_confidence": r.rejected_confidence},
            "beats": [b.to_dict() for b in self.beats],
            "beats_per_position": {str(k): sum(1 for b in self.beats if b.beat_in_bar == k)
                                   for k in range(1, bpb + 1)},
            "tempo_history": [[round(a, 3), round(b, 2)] for a, b in self.stats.tempo_history],
        }

    def _state_event(self, message: str) -> dict:
        return {"type": "session_state", "state": self.state, "message": message}


def _round(v: float | None, nd: int) -> float | None:
    if v is None or not math.isfinite(v):
        return None
    return round(float(v), nd) + 0.0   # normalizes -0.0


def analyze_samples(samples, cfg: AnalysisConfig, pattern: ConductingPattern) -> dict[str, Any]:
    """Offline analysis through the exact streaming code path."""
    a = SessionAnalyzer(cfg, pattern)
    a.start()
    for s in samples:
        a.push(s)
    a.stop()
    return a.summary()
