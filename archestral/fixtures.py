"""Deterministic SYNTHETIC trajectory fixtures for tests and the recorded-test input.

Every file is marked ``"synthetic": true`` and the UI labels this input as
"Recorded test trajectory". They are generated from the schematic reference
pattern - they are not recordings of a real person.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .analysis.patterns import builtin_pattern, ideal_trajectory

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic"
RATE_HZ = 60.0


def _rows(t, xy, conf=None):
    conf = np.ones(len(t)) if conf is None else conf
    return [[round(float(a), 5), round(float(b), 5), round(float(c), 5), round(float(d), 3)]
            for a, (b, c), d in zip(t, xy, conf)]


def _doc(name, description, bpm, rows, expect):
    return {"schema_version": 1, "synthetic": True, "name": name, "description": description,
            "pattern": "4-4", "generated_bpm": bpm, "rate_hz": RATE_HZ,
            "coordinate_space": "normalized, x right, y up", "expected": expect, "samples": rows}


def build_fixtures() -> dict[str, dict]:
    p = builtin_pattern("4-4")
    rng = np.random.default_rng(20261025)
    out: dict[str, dict] = {}

    t, xy = ideal_trajectory(p, 90, 8, RATE_HZ)
    out["reference_90bpm"] = _doc("Reference 4/4 at 90 BPM", "Clean schematic pattern.", 90, _rows(t, xy),
                                  {"bpm": 90, "beats_min": 24})

    t, xy = ideal_trajectory(p, 120, 8, RATE_HZ)
    out["faster_120bpm"] = _doc("Faster 4/4 at 120 BPM", "Clean pattern, faster tempo.", 120, _rows(t, xy),
                                {"bpm": 120, "beats_min": 24})

    t, xy = ideal_trajectory(p, 60, 6, RATE_HZ)
    out["slower_60bpm"] = _doc("Slower 4/4 at 60 BPM", "Clean pattern, slower tempo.", 60, _rows(t, xy),
                               {"bpm": 60, "beats_min": 18})

    t, xy = ideal_trajectory(p, 90, 8, RATE_HZ)
    noisy_xy = xy + rng.normal(0.0, 0.004, xy.shape)
    noisy_t = t + rng.uniform(-0.002, 0.002, len(t))
    noisy_t = np.maximum.accumulate(noisy_t + np.arange(len(t)) * 1e-7)
    conf = np.clip(rng.normal(0.9, 0.05, len(t)), 0.0, 1.0)
    out["noisy_90bpm"] = _doc("Noisy 4/4 at 90 BPM", "Positional noise (sigma 0.004), timing jitter (+-2 ms).",
                              90, _rows(noisy_t, noisy_xy, conf), {"bpm": 90, "beats_min": 20})

    t, xy = ideal_trajectory(p, 90, 1, RATE_HZ)
    keep = t < 2.6
    out["incomplete"] = _doc("Incomplete pattern", "Under one bar: too short for a reliable tempo.", 90,
                             _rows(t[keep], xy[keep]), {"bpm": None, "beats_min": 0})

    t, xy = ideal_trajectory(p, 90, 6, RATE_HZ)
    rows = _rows(t, xy)
    for i in range(50, len(rows), 97):
        rows[i][0] = rows[i - 1][0]                 # duplicate timestamp
    for i in range(80, len(rows), 131):
        rows[i][0] = rows[i][0] - 0.5               # backwards timestamp
    for i in range(120, len(rows), 173):
        rows[i][1] = None                           # non-finite coordinate (null in JSON)
    out["invalid_timestamps"] = _doc("Invalid timestamps", "Duplicates, backwards jumps and null coordinates.",
                                     90, rows, {"bpm": 90, "beats_min": 12})

    t, xy = ideal_trajectory(p, 90, 8, RATE_HZ)
    keep = rng.random(len(t)) > 0.1
    keep &= ~((t > 9.0) & (t < 9.6))               # one 0.6 s tracking gap
    out["missing_samples"] = _doc("Missing samples", "10% random drops and one 0.6 s gap.", 90,
                                  _rows(t[keep], xy[keep]), {"bpm": 90, "beats_min": 18, "gaps_min": 1})
    return out


def load_fixture(path: Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("samples"), list):
        raise ValueError("fixture must contain a samples list")
    return doc


def fixture_samples(doc: dict):
    """Convert fixture rows to Samples; null coordinates become NaN (rejected by validation)."""
    from .analysis.trajectory import Sample
    out = []
    for row in doc["samples"]:
        vals = [float("nan") if v is None else float(v) for v in row]
        out.append(Sample(vals[0], vals[1], vals[2], vals[3] if len(vals) > 3 else 1.0))
    return out


def write_fixtures(directory: Path = FIXTURE_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, doc in build_fixtures().items():
        path = directory / f"{name}.json"
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        paths.append(path)
    return paths
