import math

import numpy as np
import pytest

from archestral.analysis.beats import detect_beats
from archestral.analysis.config import AnalysisConfig
from archestral.analysis.dtw import dtw
from archestral.analysis.patterns import (BUILTIN_SPECS, beat_times, builtin_pattern, ideal_trajectory,
                                          load_patterns, pattern_from_dict)
from archestral.analysis.preprocessing import compute_normalization
from archestral.analysis.similarity import gesture_similarity
from archestral.analysis.tempo import beat_timing_error_ms, estimate_tempo, tempo_deviation_percent

P44 = builtin_pattern("4-4")


def _normalized(bpm, bars=4, pattern=P44, rate=60.0):
    t, xy = ideal_trajectory(pattern, bpm, bars, rate)
    return t, compute_normalization(xy, 0.01).apply(xy)


# ----------------------------------------------------------------- beats
@pytest.mark.parametrize("bpm", [60, 90, 120, 160])
def test_beats_found_at_every_ictus(bpm):
    t, xy = _normalized(bpm)
    beats = detect_beats(t, xy, AnalysisConfig())
    expected = beat_times(bpm, 4, 4)[1:]          # first ictus has no approach stroke
    got = [b.t for b in beats]
    assert len(got) == len(expected) - 0 or len(got) == len(expected) - 1
    for g in got:
        assert min(abs(g - e) for e in expected) < 0.03


def test_apex_of_rebound_is_not_a_beat():
    t, xy = _normalized(90)
    beats = detect_beats(t, xy, AnalysisConfig())
    assert len(beats) <= 4 * 4   # never more than one per ictus
    for b in beats:
        assert b.y < 0  # all ictus points are in the lower half of the normalized pattern


def test_noise_does_not_create_unbounded_beats():
    rng = np.random.default_rng(3)
    t = np.arange(0, 10, 1 / 60)
    xy = rng.normal(0, 0.6, (len(t), 2))           # violent random movement
    cfg = AnalysisConfig()
    beats = detect_beats(t, xy, cfg)
    assert len(beats) <= 10 / cfg.min_beat_interval_s + 1
    gaps = np.diff([b.t for b in beats])
    assert np.all(gaps >= cfg.min_beat_interval_s - 1e-9)


def test_idle_hand_produces_no_beats():
    t = np.arange(0, 5, 1 / 60)
    xy = np.column_stack([0.02 * np.sin(t * 3), 0.02 * np.cos(t * 5)])
    assert detect_beats(t, xy, AnalysisConfig()) == []


def test_beat_detection_handles_short_input():
    assert detect_beats(np.array([0.0, 0.1]), np.zeros((2, 2)), AnalysisConfig()) == []


# ----------------------------------------------------------------- tempo
def test_tempo_from_controlled_beats():
    est = estimate_tempo([i * 0.5 for i in range(10)], 30, 200)
    assert est.status == "ok" and est.bpm == pytest.approx(120.0)


def test_tempo_rejects_implausible_intervals():
    times = [0, 0.5, 1.0, 1.05, 1.5, 2.0, 5.0, 5.5]   # 0.05 s (1200 BPM) and 3 s (20 BPM) gaps
    est = estimate_tempo(times, 30, 200)
    assert est.bpm == pytest.approx(120.0)
    assert est.intervals_rejected == 2


def test_tempo_unavailable_without_enough_beats():
    assert estimate_tempo([0.0, 0.6], 30, 200).bpm is None
    assert estimate_tempo([], 30, 200).status == "insufficient_beats"


def test_tempo_deviation_formula_and_invalid_target():
    assert tempo_deviation_percent(99, 90) == pytest.approx(10.0)
    assert tempo_deviation_percent(81, 90) == pytest.approx(-10.0)
    assert tempo_deviation_percent(90, 0) is None
    assert tempo_deviation_percent(None, 90) is None
    assert tempo_deviation_percent(90, float("nan")) is None


def test_beat_timing_error():
    period = 60 / 90
    on_grid = [1.234 + i * period for i in range(8)]
    assert beat_timing_error_ms(on_grid, 90) == pytest.approx(0.0, abs=1e-6)
    jittered = [b + (0.02 if i % 2 else -0.02) for i, b in enumerate(on_grid)]
    assert beat_timing_error_ms(jittered, 90) == pytest.approx(20.0, abs=0.5)
    assert beat_timing_error_ms([1.0], 90) is None
    assert beat_timing_error_ms(on_grid, 0) is None


# ----------------------------------------------------------------- DTW
def test_dtw_identical_sequences_zero():
    a = np.random.default_rng(4).normal(size=(40, 2))
    r = dtw(a, a)
    assert r.status == "ok" and r.distance == pytest.approx(0.0) and r.path_length == 40


def test_dtw_different_lengths():
    s = np.linspace(0, 2 * np.pi, 50)
    a = np.column_stack([np.sin(s), np.cos(s)])
    s2 = np.linspace(0, 2 * np.pi, 80)
    b = np.column_stack([np.sin(s2), np.cos(s2)])
    r = dtw(a, b, band=10)
    assert r.status == "ok"
    assert r.normalized < 0.1
    assert r.path_length >= 80


def test_dtw_time_shift_beats_euclidean_and_noise_increases_distance():
    s = np.linspace(0, 4 * np.pi, 100)
    a = np.column_stack([np.sin(s), np.zeros_like(s)])
    shifted = np.column_stack([np.sin(s - 0.4), np.zeros_like(s)])
    noisy = a + np.random.default_rng(5).normal(0, 0.3, a.shape)
    r_shift = dtw(a, shifted)
    euclid = float(np.mean(np.linalg.norm(a - shifted, axis=1)))
    assert r_shift.normalized < euclid
    assert dtw(a, noisy).normalized > dtw(a, a + 0.01).normalized


def test_dtw_length_normalization():
    a = np.zeros((20, 1))
    b = np.ones((20, 1))
    a2 = np.zeros((200, 1))
    b2 = np.ones((200, 1))
    assert dtw(a, b).normalized == pytest.approx(dtw(a2, b2).normalized)


def test_dtw_empty_and_invalid():
    assert dtw([], [[1, 2]]).status == "empty"
    assert dtw([[1, 2]], [[1, 2, 3]]).status == "invalid"
    assert dtw([[np.nan, 1]], [[1, 1]]).status == "invalid"
    assert dtw("abc", [[1]]).status == "invalid"
    assert dtw(np.zeros((2, 2, 2)), np.zeros((2, 2))).status == "invalid"


# ----------------------------------------------------------------- patterns + similarity
def test_pattern_format_round_trip_and_beat_order():
    for pid in BUILTIN_SPECS:
        p = builtin_pattern(pid)
        q = pattern_from_dict(p.to_dict())
        assert q.beats_per_bar == p.beats_per_bar
        assert np.allclose(q.ictus, p.ictus, atol=1e-4)
        # beat k sits at phase (k-1)/beats and at the ictus position
        for k in range(p.beats_per_bar):
            row = p.points[np.argmin(np.abs(p.points[:, 0] - k / p.beats_per_bar))]
            assert np.allclose(row[1:], p.ictus[k], atol=1e-6)


def test_pattern_validation_rejects_bad_input():
    good = P44.to_dict()
    for mutate in (lambda d: d.update(id="../x"), lambda d: d.update(beats_per_bar=0),
                   lambda d: d["ictus"].pop(), lambda d: d["ictus"][0].update(x=float("inf"))):
        d = P44.to_dict()
        mutate(d)
        with pytest.raises((ValueError, KeyError)):
            pattern_from_dict(d)
    assert pattern_from_dict(good).id == "4-4"


def test_patterns_load_from_directory():
    pats = load_patterns()
    assert {"4-4", "3-4", "2-4"} <= set(pats)


def test_similarity_prefers_correct_pattern_and_finds_start_beat():
    cfg = AnalysisConfig()
    period = 60 / 90
    t, xy = ideal_trajectory(P44, 90, 2, 60)
    # one bar starting on beat 2
    m = (t >= period) & (t <= period * 5)
    good = gesture_similarity(xy[m], P44, cfg.dtw_points, cfg.dtw_band, cfg.similarity_d_perfect, cfg.similarity_d_random)
    assert good.status == "ok" and good.start_beat == 2
    assert good.estimate > 0.8
    t3, xy3 = ideal_trajectory(builtin_pattern("3-4"), 90, 2, 60)
    wrong = gesture_similarity(xy3[t3 <= period * 4], P44, cfg.dtw_points, cfg.dtw_band, cfg.similarity_d_perfect,
                               cfg.similarity_d_random)
    assert wrong.estimate < good.estimate - 0.3


def test_similarity_insufficient_or_invalid():
    assert gesture_similarity(np.zeros((3, 2)), P44, 64, 0.25).status == "insufficient_data"
    bad = np.full((20, 2), np.nan)
    assert gesture_similarity(bad, P44, 64, 0.25).status == "invalid"
    assert math.isfinite(gesture_similarity(np.random.default_rng(1).normal(size=(30, 2)), P44, 64, 0.25).normalized_distance)


def test_similarity_anchors_random_motion_near_zero():
    """Smooth random hand motion must not earn partial credit."""
    rng = np.random.default_rng(7)
    ests = []
    for _ in range(40):
        w = rng.normal(size=(100, 2))
        xy = np.column_stack([np.convolve(w[:, i], np.ones(8) / 8, "same") for i in range(2)])[20:80]
        ests.append(gesture_similarity(xy, P44, 64, 0.25).estimate)
    assert np.median(ests) < 0.15
    t, xy = ideal_trajectory(P44, 90, 1, 60)
    assert gesture_similarity(xy, P44, 64, 0.25).estimate > 0.9
