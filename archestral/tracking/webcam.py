"""Webcam hand tracking with OpenCV + MediaPipe Hands, fully local.

A background thread captures frames, runs MediaPipe, and emits one Sample per
frame for the tracked landmark (wrist by default). Frames where no hand is
found emit a confidence-0 sample so the analyzer can measure tracking loss.
Only the processed point leaves this module; a small JPEG preview is kept for
the local UI when requested and is never written to disk or sent elsewhere.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from ..analysis.trajectory import Sample
from . import BoundedSampleQueue, TrackingSource

log = logging.getLogger("archestral.webcam")

LANDMARKS = {"wrist": 0, "index_tip": 8}


def vision_available() -> tuple[bool, str]:
    try:
        import cv2  # noqa: F401
    except Exception as e:  # pragma: no cover - environment dependent
        return False, f"OpenCV unavailable: {e}"
    try:
        import mediapipe as mp
        if not hasattr(mp, "solutions"):
            return False, "Installed MediaPipe has no 'solutions' API; install mediapipe==0.10.21"
    except Exception as e:  # pragma: no cover
        return False, f"MediaPipe unavailable: {e}"
    return True, "OpenCV and MediaPipe available"


class WebcamSource(TrackingSource):
    kind = "webcam"
    is_test_input = False

    def __init__(self, camera_index: int = 0, mirror: bool = True, landmark: str = "wrist",
                 width: int = 640, height: int = 480) -> None:
        self.camera_index = camera_index
        self.mirror = mirror
        self.landmark = LANDMARKS.get(landmark, 0)
        self.size = (width, height)
        self.label = f"Webcam {camera_index} (MediaPipe Hands, {landmark})"
        self._q = BoundedSampleQueue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._state = "idle"
        self._message = "Not started."
        self._hand = False
        self._fps = 0.0
        self._preview: bytes | None = None
        self.preview_enabled = False
        self._trail: deque[tuple[int, int]] = deque(maxlen=40)

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        ok, msg = vision_available()
        if not ok:
            self._set_state("unavailable", msg)
            return
        self._stop.clear()
        self._set_state("starting", "Opening camera...")
        # macOS only shows the camera-permission prompt when the device is opened
        # from the main thread, so open here (the service calls start() on its
        # main event-loop thread) and only read frames in the background.
        import cv2
        cap = self._open(cv2)
        if cap is None:
            self._set_state("unavailable",
                            f"Camera {self.camera_index} could not be opened. On macOS allow camera access for "
                            "the app that runs Archestral (e.g. Terminal) in System Settings > Privacy & Security "
                            "> Camera, then press Start again.")
            return
        self._thread = threading.Thread(target=self._run, args=(cap,), name="webcam", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None
        if self._state not in ("unavailable",):
            self._set_state("stopped", "Camera released.")

    def poll(self) -> list[Sample]:
        return self._q.drain()

    def latest_preview(self) -> bytes | None:
        with self._lock:
            p, self._preview = self._preview, None
        return p

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self._state
            if state == "running":
                state = "tracking" if self._hand else "lost"
            return {"source": "webcam", "label": self.label, "test_input": False, "state": state,
                    "camera_state": self._state, "message": self._message, "fps": round(self._fps, 1),
                    "dropped_samples": self._q.dropped}

    def _set_state(self, state: str, message: str) -> None:
        with self._lock:
            changed = state != self._state
            self._state, self._message = state, message
        if changed:
            log.info("webcam state=%s %s", state, message)

    # -- capture thread ------------------------------------------------------
    def _open(self, cv2):
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_AVFOUNDATION) if hasattr(cv2, "CAP_AVFOUNDATION") \
            else cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
        return cap

    def _run(self, cap) -> None:  # pragma: no cover - needs camera hardware
        import cv2
        import mediapipe as mp

        hands = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=1, model_complexity=0,
                                         min_detection_confidence=0.6, min_tracking_confidence=0.5)
        drawer = mp.solutions.drawing_utils
        conn = mp.solutions.hands.HAND_CONNECTIONS
        self._set_state("running", "Camera running. Raise one hand into view.")
        failures = 0
        last_preview = 0.0
        frame_times: deque[float] = deque(maxlen=30)
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                t = time.monotonic()
                if not ok or frame is None:
                    failures += 1
                    if failures in (15, 60):
                        log.warning("webcam read failures=%d; trying to reopen", failures)
                        cap.release()
                        time.sleep(0.5)
                        cap = self._open(cv2) or cap
                    if failures > 150:
                        self._set_state("error", "Camera stopped delivering frames.")
                        break
                    time.sleep(0.02)
                    continue
                if failures:
                    failures = 0
                    self._set_state("running", "Camera reacquired.")
                frame_times.append(t)
                if len(frame_times) > 1:
                    self._fps = (len(frame_times) - 1) / max(1e-6, frame_times[-1] - frame_times[0])
                if self.mirror:
                    frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                res = hands.process(rgb)
                h, w = frame.shape[:2]
                if res.multi_hand_landmarks:
                    lm = res.multi_hand_landmarks[0].landmark[self.landmark]
                    score = 1.0
                    if res.multi_handedness:
                        score = float(res.multi_handedness[0].classification[0].score)
                    self._hand = True
                    self._q.put(Sample(t, float(lm.x), 1.0 - float(lm.y), score))
                    self._trail.append((int(lm.x * w), int(lm.y * h)))
                else:
                    self._hand = False
                    self._q.put(Sample(t, float("nan"), float("nan"), 0.0))
                if self.preview_enabled and t - last_preview > 1 / 12:
                    last_preview = t
                    if res.multi_hand_landmarks:
                        drawer.draw_landmarks(frame, res.multi_hand_landmarks[0], conn)
                    for a, b in zip(list(self._trail)[:-1], list(self._trail)[1:]):
                        cv2.line(frame, a, b, (84, 179, 224), 2)
                    small = cv2.resize(frame, (int(w * 320 / h), 320)) if h > 320 else frame
                    ok_jpg, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 60])
                    if ok_jpg:
                        with self._lock:
                            self._preview = buf.tobytes()
        finally:
            hands.close()
            cap.release()
            log.info("webcam released")
