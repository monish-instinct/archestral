"""Regression tests for beat/tempo robustness on webcam-like SYNTHETIC input.

The generator mimics webcam conditions that the clean fixtures do not:
30 fps, landmark jitter, dropped frames (no hand), per-beat size variation,
slight tempo drift, flatter sideways beats and a hand that keeps moving
through the ictus. It is still synthetic; real recordings are the next step
(see docs/KNOWN_LIMITATIONS.md).
"""

import numpy as np
import pytest

from archestral.analysis.config import AnalysisConfig
from archestral.analysis.patterns import builtin_pattern, make_pattern, stroke
from archestral.analysis.session import analyze_samples
from archestral.analysis.tempo import estimate_tempo
from archestral.analysis.trajectory import Sample

P44 = builtin_pattern("4-4")


def webcam_like(bpm, seed, fps=30, bars=8, size=0.12, jitter=0.003, drop=0.03, lateral=0.5, sharp=0.5):
    rng = np.random.default_rng(seed)
    p = make_pattern("x", "x", P44.ictus, P44.rebound * [1, lateral, lateral, 1], P44.approach * [1, lateral, lateral, 1])
    out, t = [], 0.0
    for k in range(bars * 4):
        period = 60 / bpm * (1 + 0.03 * np.sin(k / 5))
        amp = 1 + rng.normal(0, 0.15)
        b, n = k % 4, (k + 1) % 4
        nf = max(2, int(round(period * fps)))
        for i in range(nf):
            s = i / nf
            s = (1 - sharp) * s + sharp * np.arccos(1 - 2 * s) / np.pi
            xy = stroke(p.ictus[b], p.ictus[n], p.rebound[b], p.approach[n], np.array([s]))[0] * amp
            tt = t + i / fps + rng.normal(0, 0.003)
            if rng.random() < drop:
                out.append(Sample(tt, float("nan"), float("nan"), 0.0))
            else:
                out.append(Sample(tt, 0.5 + xy[0] * size + rng.normal(0, jitter),
                                  0.5 + xy[1] * size + rng.normal(0, jitter), 0.93))
        t += period
    out.sort(key=lambda s: s.t)
    return out


@pytest.mark.parametrize("bpm", [60, 90, 120])
@pytest.mark.parametrize("seed", [0, 1])
def test_typical_webcam_conditions(bpm, seed):
    r = analyze_samples(webcam_like(bpm, seed), AnalysisConfig(target_bpm=bpm), P44)
    assert r["estimated_bpm"] == pytest.approx(bpm, rel=0.06)
    expected = 8 * 4 - 2.3 * bpm / 60          # beats after calibration
    assert 0.85 * expected <= r["beat_count"] <= 1.1 * expected


@pytest.mark.parametrize("bpm", [90, 120])
def test_far_jittery_hand_does_not_double_tempo(bpm):
    """Small hand in frame + strong jitter used to produce ~2x tempo (extra beats).

    At 60 BPM this condition is still unreliable (documented limitation); the
    service flags it with ``small_movement`` so the UI asks the user to move closer.
    """
    ratios = []
    for seed in range(3):
        samples = webcam_like(bpm, seed, size=0.08, jitter=0.006, sharp=0.8, lateral=1.0)
        r = analyze_samples(samples, AnalysisConfig(target_bpm=bpm), P44)
        ratios.append((r["estimated_bpm"] or 0) / bpm)
    assert max(ratios) < 1.15
    assert min(ratios) > 0.85


def test_bar_span_tempo_cancels_per_beat_offsets():
    # beats of a 4/4 bar with systematic per-position offsets (up to 40 ms) at 100 BPM
    offsets = [0.04, 0.0, -0.01, -0.01]
    times = [i * 0.6 + offsets[i % 4] for i in range(16)]
    single = estimate_tempo(times, 30, 200, beats_per_bar=1).bpm
    spans = estimate_tempo(times, 30, 200, beats_per_bar=4).bpm
    assert spans == pytest.approx(100.0, abs=0.01)
    assert abs(single - 100.0) > abs(spans - 100.0)


def test_bar_span_skips_bars_with_missed_beat():
    times = [i * 0.6 for i in range(12)]
    del times[6]                                   # one missed beat
    assert estimate_tempo(times, 30, 200, beats_per_bar=4).bpm == pytest.approx(100.0, rel=0.01)


def test_far_hand_is_flagged():
    samples = webcam_like(90, 0, size=0.06, jitter=0.002)
    from archestral.analysis.session import SessionAnalyzer
    a = SessionAnalyzer(AnalysisConfig(), P44)
    a.start()
    for x in samples:
        a.push(x)
    assert a.metrics()["small_movement"] is True
    b = SessionAnalyzer(AnalysisConfig(), P44)
    b.start()
    for x in webcam_like(90, 0, size=0.15):
        b.push(x)
    assert b.metrics()["small_movement"] is False
