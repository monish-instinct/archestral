"""Input sources that produce conducting trajectories.

Every source yields ``analysis.trajectory.Sample`` objects in the shared
coordinate space (normalized, x right, y up) and reports its status.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Any

from ..analysis.trajectory import Sample


class TrackingSource(ABC):
    kind: str = "abstract"
    label: str = "abstract"
    is_test_input: bool = False

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def poll(self) -> list[Sample]:
        """Return all samples produced since the last call (non-blocking)."""

    @abstractmethod
    def status(self) -> dict[str, Any]: ...

    def latest_preview(self) -> bytes | None:
        return None


class BoundedSampleQueue:
    """Thread-safe FIFO that drops the oldest samples when full (stale data is useless)."""

    def __init__(self, maxlen: int = 512) -> None:
        self._q: deque[Sample] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.dropped = 0

    def put(self, s: Sample) -> None:
        with self._lock:
            if len(self._q) == self._q.maxlen:
                self.dropped += 1
            self._q.append(s)

    def drain(self) -> list[Sample]:
        with self._lock:
            out = list(self._q)
            self._q.clear()
        return out


class ExternalSource(TrackingSource):
    """Samples pushed by the client: mouse/trackpad conducting or a WebXR controller."""

    def __init__(self, kind: str) -> None:
        if kind not in ("mouse", "webxr"):
            raise ValueError(kind)
        self.kind = kind
        self.label = "Mouse / trackpad (manual input)" if kind == "mouse" else "WebXR controller"
        self._q = BoundedSampleQueue(4096)   # client batches can arrive in bursts
        self._last_wall: float | None = None
        self._running = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def push(self, samples: list[Sample]) -> None:
        if not self._running:
            return
        for s in samples:
            self._q.put(s)
        self._last_wall = time.monotonic()

    def poll(self) -> list[Sample]:
        return self._q.drain()

    def status(self) -> dict[str, Any]:
        if self._last_wall is None:
            state, msg = "waiting", ("Press and drag in the conducting pad to conduct." if self.kind == "mouse"
                                     else "Waiting for controller samples from the headset.")
        elif time.monotonic() - self._last_wall > 0.6:
            state, msg = "lost", "No movement received."
        else:
            state, msg = "tracking", "Receiving samples."
        return {"source": self.kind, "label": self.label, "test_input": False, "state": state, "message": msg}
