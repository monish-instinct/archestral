"""Recorded-trajectory replay. Explicitly a TEST input - never presented as live tracking."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..analysis.trajectory import Sample
from ..fixtures import FIXTURE_DIR, fixture_samples, load_fixture
from . import TrackingSource


def list_fixtures(directory: Path = FIXTURE_DIR) -> list[dict[str, Any]]:
    out = []
    for path in sorted(directory.glob("*.json")):
        try:
            doc = load_fixture(path)
            out.append({"id": path.stem, "name": doc.get("name", path.stem), "description": doc.get("description", ""),
                        "generated_bpm": doc.get("generated_bpm"), "synthetic": bool(doc.get("synthetic"))})
        except (ValueError, OSError):
            continue
    return out


class RecordedSource(TrackingSource):
    kind = "recorded"
    is_test_input = True

    def __init__(self, fixture_id: str, directory: Path = FIXTURE_DIR, loop: bool = True, clock=time.monotonic) -> None:
        path = (directory / f"{fixture_id}.json").resolve()
        if path.parent != directory.resolve() or not path.exists():
            raise FileNotFoundError(f"unknown fixture {fixture_id!r}")
        doc = load_fixture(path)
        self.fixture_id = fixture_id
        self.label = f"Recorded test trajectory: {doc.get('name', fixture_id)} (synthetic)"
        self.samples = fixture_samples(doc)
        if not self.samples:
            raise ValueError("fixture has no samples")
        finite_t = [s.t for s in self.samples if s.t == s.t]
        self._t_first = min(finite_t)
        self._span = max(finite_t) - self._t_first + 1.0 / float(doc.get("rate_hz", 60))
        self.loop = loop
        self._clock = clock
        self._start: float | None = None
        self._i = 0
        self._lap = 0

    def start(self) -> None:
        self._start = self._clock()
        self._i = 0
        self._lap = 0

    def stop(self) -> None:
        self._start = None

    def poll(self) -> list[Sample]:
        if self._start is None:
            return []
        elapsed = self._clock() - self._start
        out = []
        while True:
            if self._i >= len(self.samples):
                if not self.loop:
                    break
                self._i = 0
                self._lap += 1
            s = self.samples[self._i]
            rel = (s.t - self._t_first) + self._lap * self._span
            if rel != rel:          # NaN timestamp: pass through so validation rejects it
                rel = -1.0
            if rel > elapsed:
                break
            # Re-base onto the service clock; invalid timestamps keep their relative error.
            out.append(Sample(self._start + rel if s.t == s.t else s.t, s.x, s.y, s.confidence))
            self._i += 1
            if len(out) > 1000:
                break
        return out

    def status(self) -> dict[str, Any]:
        running = self._start is not None
        return {"source": "recorded", "label": self.label, "test_input": True,
                "state": "tracking" if running else "idle",
                "message": "Replaying a synthetic test trajectory (not live tracking)." if running else "Stopped."}
