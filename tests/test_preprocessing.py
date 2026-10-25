import math

import numpy as np
import pytest

from archestral.analysis.config import AnalysisConfig, config_from_dict
from archestral.analysis.preprocessing import (OneEuroFilter, compute_normalization, find_gaps, normalize_shape,
                                               preprocess, resample_n, resample_uniform, split_segments,
                                               validate_samples)
from archestral.analysis.trajectory import Sample, samples_from_rows


def test_normalization_centers_and_scales():
    rng = np.random.default_rng(0)
    xy = np.column_stack([rng.uniform(0.3, 0.7, 500), rng.uniform(0.4, 0.6, 500)])
    n = compute_normalization(xy, 0.01)
    assert n is not None
    out = n.apply(xy)
    box_mid = (np.percentile(out, 5, axis=0) + np.percentile(out, 95, axis=0)) / 2
    assert np.allclose(box_mid, 0.0, atol=1e-9)
    # larger axis spans roughly [-1, 1] between its 5th and 95th percentile
    assert np.percentile(out[:, 0], 95) == pytest.approx(1.0, abs=0.02)
    assert np.percentile(out[:, 0], 5) == pytest.approx(-1.0, abs=0.02)


def test_normalization_rejects_insufficient_movement():
    xy = np.full((100, 2), 0.5) + np.random.default_rng(1).normal(0, 0.001, (100, 2))
    assert compute_normalization(xy, 0.04) is None
    assert compute_normalization(np.zeros((3, 2)), 0.04) is None


def test_one_euro_reduces_jitter_but_follows_fast_motion():
    rng = np.random.default_rng(2)
    t = np.arange(0, 2, 1 / 60)
    still = 0.5 + rng.normal(0, 0.01, (len(t), 2))
    f = OneEuroFilter(2.5, 0.4, 1.0)
    smoothed = np.array([f(ti, p) for ti, p in zip(t, still)])
    assert smoothed[30:].std() < still[30:].std() * 0.6

    f.reset()
    ramp = np.column_stack([t * 3.0, np.zeros_like(t)])  # fast linear motion
    out = np.array([f(ti, p) for ti, p in zip(t, ramp)])
    lag = ramp[-1, 0] - out[-1, 0]
    assert 0 <= lag < 0.15   # small lag: beat boundaries are not smeared


def test_invalid_timestamps_rejected():
    rows = [[0.0, 0.5, 0.5], [0.1, 0.5, 0.5], [0.1, 0.5, 0.5], [0.05, 0.5, 0.5], [float("nan"), 0.5, 0.5],
            [0.2, 0.5, 0.5]]
    good, rep = validate_samples(samples_from_rows(rows), 0.5)
    assert [s.t for s in good] == [0.0, 0.1, 0.2]
    assert rep.rejected_timestamp == 3


def test_nonfinite_range_and_confidence_rejected():
    s = [Sample(0.0, 0.5, 0.5), Sample(0.1, math.nan, 0.5), Sample(0.2, 99.0, 0.5), Sample(0.3, 0.5, 0.5, 0.1),
         Sample(0.4, 0.5, 0.5, 0.9)]
    good, rep = validate_samples(s, 0.5)
    assert [x.t for x in good] == [0.0, 0.4]
    assert (rep.rejected_nonfinite, rep.rejected_range, rep.rejected_confidence) == (1, 1, 1)


def test_missing_samples_split_into_segments_without_interpolating_across_gap():
    t = np.concatenate([np.arange(0, 1, 0.02), np.arange(1.5, 2.5, 0.02)])
    segs = split_segments(t, 0.25)
    assert segs == [(0, 50), (50, 100)]
    assert find_gaps(t, 0.25) == [(pytest.approx(0.98), pytest.approx(1.5))]
    samples = [Sample(float(a), 0.5 + 0.1 * math.sin(a), 0.5) for a in t]
    res = preprocess(samples, AnalysisConfig())
    assert len(res.segments) == 2
    for ts, _ in res.segments:
        assert np.allclose(np.diff(ts), 1 / 60, atol=1e-9)


def test_resampling():
    t = np.array([0.0, 0.1, 0.3])
    xy = np.array([[0.0, 0.0], [1.0, 1.0], [3.0, 3.0]])
    tu, xu = resample_uniform(t, xy, 20)
    assert np.allclose(tu, np.arange(0, 0.3001, 0.05))
    assert np.allclose(xu[:, 0], tu * 10)
    assert resample_n(xy, 5).shape == (5, 2)
    with pytest.raises(ValueError):
        resample_n(np.zeros((0, 2)), 4)


def test_shape_normalization_is_translation_and_scale_invariant():
    a = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
    b = a * 7 + np.array([3, -2])
    assert np.allclose(normalize_shape(a), normalize_shape(b))


def test_config_validation():
    cfg, problems = config_from_dict({"target_bpm": 120, "dip_ratio": 5, "nope": 1, "min_bpm": "x"})
    assert cfg.target_bpm == 120
    assert cfg.dip_ratio == AnalysisConfig().dip_ratio
    assert len(problems) == 3
    cfg, problems = config_from_dict({"min_bpm": 100, "max_bpm": 90})
    assert cfg.min_bpm < cfg.max_bpm and problems
    cfg, _ = config_from_dict({"tempo_window": 5})
    assert isinstance(cfg.tempo_window, int)
