"""Integration: recorded synthetic trajectories through the full streaming pipeline."""

import json
from pathlib import Path

import pytest

from archestral.analysis.config import AnalysisConfig
from archestral.analysis.patterns import builtin_pattern
from archestral.analysis.session import SIMILARITY_LABEL, SessionAnalyzer, analyze_samples
from archestral.analysis.trajectory import Sample
from archestral.fixtures import FIXTURE_DIR, build_fixtures, fixture_samples, load_fixture

P44 = builtin_pattern("4-4")


def run(name, target=None):
    doc = load_fixture(FIXTURE_DIR / f"{name}.json")
    cfg = AnalysisConfig(target_bpm=target or doc["generated_bpm"])
    return doc, analyze_samples(fixture_samples(doc), cfg, P44)


def test_fixtures_are_marked_synthetic_and_deterministic():
    built = build_fixtures()
    for name, doc in built.items():
        on_disk = json.loads((FIXTURE_DIR / f"{name}.json").read_text())
        assert on_disk["synthetic"] is True
        assert on_disk["samples"] == json.loads(json.dumps(doc["samples"])), name


def test_analysis_is_deterministic():
    _, a = run("noisy_90bpm")
    _, b = run("noisy_90bpm")
    assert a == b


@pytest.mark.parametrize("name", ["reference_90bpm", "faster_120bpm", "slower_60bpm", "noisy_90bpm",
                                  "missing_samples", "invalid_timestamps"])
def test_tempo_recovered_from_fixture(name):
    doc, s = run(name)
    exp = doc["expected"]
    assert s["beat_count"] >= exp["beats_min"]
    assert s["estimated_bpm"] == pytest.approx(exp["bpm"], rel=0.03)
    assert abs(s["tempo_deviation_pct"]) < 3.0


def test_beats_labelled_in_order():
    _, s = run("reference_90bpm")
    labels = [b["beat_in_bar"] for b in s["beats"] if b["beat_in_bar"] is not None]
    assert len(labels) >= 20
    for a, b in zip(labels, labels[1:]):
        assert b == a % 4 + 1


def test_tempo_deviation_against_other_target():
    _, s = run("faster_120bpm", target=90)
    assert s["tempo_deviation_pct"] == pytest.approx(33.3, abs=1.5)


def test_incomplete_pattern_reports_no_tempo():
    _, s = run("incomplete")
    assert s["estimated_bpm"] is None
    assert s["tempo_status"] == "insufficient_beats"
    assert s["similarity"]["estimate"] is None


def test_invalid_timestamps_are_counted():
    _, s = run("invalid_timestamps")
    assert s["rejected"]["timestamp"] > 0
    assert s["rejected"]["nonfinite"] > 0


def test_missing_samples_reports_gap():
    _, s = run("missing_samples")
    assert s["invalid_intervals"] >= 1
    assert s["invalid_time_s"] >= 0.5


def test_similarity_is_labelled_prototype_and_noisy_not_better():
    _, ref = run("reference_90bpm")
    _, noisy = run("noisy_90bpm")
    assert ref["similarity"]["label"] == SIMILARITY_LABEL
    assert 0 < ref["similarity_mean"] <= 1
    assert noisy["similarity_mean"] <= ref["similarity_mean"] + 0.01


def test_state_machine_and_pause_resume():
    a = SessionAnalyzer(AnalysisConfig(), P44)
    assert a.state == "idle"
    assert a.push(Sample(0, 0.5, 0.5)) == []          # ignored while idle
    assert a.pause() == []
    a.start()
    assert a.state == "calibrating"
    doc = load_fixture(FIXTURE_DIR / "reference_90bpm.json")
    samples = fixture_samples(doc)
    for s in samples[:300]:
        a.push(s)
    assert a.state == "running"
    a.pause()
    beats_before = len(a.beats)
    for s in samples[300:500]:
        a.push(s)
    assert len(a.beats) == beats_before               # nothing analysed while paused
    a.resume()
    for s in samples[500:]:
        a.push(s)
    assert len(a.beats) > beats_before
    events = a.stop()
    assert events[-1]["type"] == "summary"
    assert a.stop() == []


def test_insufficient_movement_blocks_calibration():
    a = SessionAnalyzer(AnalysisConfig(), P44)
    a.start()
    events = []
    for i in range(400):
        events += a.push(Sample(i / 60, 0.5 + 0.001 * (i % 2), 0.5))
    assert a.state == "calibrating"
    assert any(e["type"] == "session_state" and "Not enough movement" in e["message"] for e in events)
    assert a.metrics()["insufficient_movement"] is True


def test_tracking_lost_detected_from_no_hand_samples():
    a = SessionAnalyzer(AnalysisConfig(), P44)
    a.start()
    for i in range(100):
        a.push(Sample(i / 60, 0.5 + 0.1 * (i % 7) / 7, 0.5))
    for i in range(100, 160):
        a.push(Sample(i / 60, float("nan"), float("nan"), 0.0))
    m = a.metrics()
    assert m["tracking"] == "lost"
    assert m["tracking_confidence"] < 0.1


def test_feedback_events_are_rate_limited():
    a = SessionAnalyzer(AnalysisConfig(feedback_interval_s=0.2), P44)
    a.start()
    n = sum(1 for i in range(600) for e in a.push(Sample(i / 60, 0.5 + 0.1 * (i % 9) / 9, 0.5))
            if e["type"] == "feedback")
    assert 45 <= n <= 51       # 10 s of samples -> ~50 feedback messages, not 600


def test_session_tempo_covers_whole_session_not_just_the_end():
    """Results must report the whole session, not the rolling value at the end."""
    from archestral.analysis.patterns import ideal_trajectory
    t1, xy1 = ideal_trajectory(P44, 90, 8, 60)
    t2, xy2 = ideal_trajectory(P44, 150, 2, 60, t0=float(t1[-1]) + 1 / 60)
    samples = [Sample(float(a), float(b), float(c)) for a, (b, c) in
               list(zip(t1, xy1)) + list(zip(t2, xy2))]
    s = analyze_samples(samples, AnalysisConfig(target_bpm=90), P44)
    assert s["estimated_bpm"] > 120                         # rolling value follows the fast ending
    assert s["session_bpm"] == pytest.approx(90, rel=0.12)  # the session as a whole was mostly 90
    assert s["session_tempo_deviation_pct"] == pytest.approx((s["session_bpm"] - 90) / 90 * 100, abs=0.01)
