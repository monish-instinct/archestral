"""Versioned JSON message protocol between the service and the client (see docs/PROTOCOL.md).

Envelope: {"v": 1, "type": str, "seq": int, "ts": float, ...payload}
Transport: WebSocket text frames on 127.0.0.1 (one JSON object per frame).

Incoming messages are validated against an explicit whitelist; nothing in a
message is ever evaluated or used as a file path.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any

from . import PROTOCOL_VERSION
from .analysis.config import TARGET_BPM_RANGE

MAX_MESSAGE_BYTES = 64 * 1024
MAX_POINTS_PER_MESSAGE = 256

SERVER_TYPES = frozenset({"hello", "status", "samples", "beat", "feedback", "session_state", "calibration",
                          "summary", "preview", "error", "pong"})
COMMANDS = frozenset({"start", "pause", "resume", "stop", "calibrate", "set_source", "set_target_bpm",
                      "set_pattern", "set_preview"})
SOURCES = frozenset({"webcam", "mouse", "webxr", "recorded", "none"})
CLIENT_SAMPLE_SOURCES = frozenset({"mouse", "webxr"})


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ClientMessage:
    type: str
    seq: int
    data: dict[str, Any]


class Encoder:
    def __init__(self) -> None:
        self._seq = 0

    def encode(self, msg_type: str, payload: dict[str, Any] | None = None) -> str:
        if msg_type not in SERVER_TYPES:
            raise ValueError(f"unknown server message type {msg_type}")
        self._seq += 1
        body = {"v": PROTOCOL_VERSION, "type": msg_type, "seq": self._seq, "ts": round(time.monotonic(), 4)}
        if payload:
            for k in ("v", "type", "seq", "ts"):
                payload.pop(k, None)
            body.update(payload)
        return json.dumps(body, separators=(",", ":"), allow_nan=False)


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _points(raw: Any) -> list[list[float]]:
    if not isinstance(raw, list) or not raw:
        raise ProtocolError("bad_points", "points must be a non-empty list")
    if len(raw) > MAX_POINTS_PER_MESSAGE:
        raise ProtocolError("too_many_points", f"at most {MAX_POINTS_PER_MESSAGE} points per message")
    out = []
    for p in raw:
        if not isinstance(p, list) or not (3 <= len(p) <= 4) or not all(_finite(v) for v in p):
            raise ProtocolError("bad_points", "each point must be [t, x, y, confidence?] of finite numbers")
        conf = float(p[3]) if len(p) == 4 else 1.0
        if not (0.0 <= conf <= 1.0):
            raise ProtocolError("bad_points", "confidence must be in [0, 1]")
        out.append([float(p[0]), float(p[1]), float(p[2]), conf])
    return out


def decode_client(raw: str | bytes) -> ClientMessage:
    """Parse and validate one client message. Raises ProtocolError."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_MESSAGE_BYTES:
            raise ProtocolError("too_large", "message exceeds size limit")
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ProtocolError("bad_encoding", "message must be UTF-8") from e
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ProtocolError("too_large", "message exceeds size limit")
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ProtocolError("bad_json", "message is not valid JSON") from e
    if not isinstance(msg, dict):
        raise ProtocolError("bad_envelope", "message must be a JSON object")
    if msg.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("bad_version", f"unsupported protocol version {msg.get('v')!r}")
    mtype = msg.get("type")
    seq = msg.get("seq", 0)
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        raise ProtocolError("bad_envelope", "seq must be a non-negative integer")

    if mtype == "ping":
        return ClientMessage("ping", seq, {})
    if mtype == "samples":
        source = msg.get("source")
        if source not in CLIENT_SAMPLE_SOURCES:
            raise ProtocolError("bad_source", "samples source must be 'mouse' or 'webxr'")
        return ClientMessage("samples", seq, {"source": source, "points": _points(msg.get("points"))})
    if mtype == "command":
        return ClientMessage("command", seq, _command(msg))
    raise ProtocolError("unknown_type", f"unknown message type {mtype!r}")


def _command(msg: dict[str, Any]) -> dict[str, Any]:
    name = msg.get("name")
    if name not in COMMANDS:
        raise ProtocolError("unknown_command", f"unknown command {name!r}")
    args = msg.get("args", {})
    if not isinstance(args, dict):
        raise ProtocolError("bad_args", "args must be an object")
    out: dict[str, Any] = {"name": name}
    if name == "set_source":
        src = args.get("source")
        if src not in SOURCES:
            raise ProtocolError("bad_args", "unknown source")
        out["source"] = src
        if src == "webcam":
            cam = args.get("camera", 0)
            if not isinstance(cam, int) or isinstance(cam, bool) or not (0 <= cam <= 9):
                raise ProtocolError("bad_args", "camera must be an integer 0..9")
            out["camera"] = cam
        if src == "recorded":
            fx = args.get("fixture")
            if not isinstance(fx, str) or not fx.replace("_", "").isalnum() or len(fx) > 64:
                raise ProtocolError("bad_args", "fixture must be a fixture name")
            out["fixture"] = fx
    elif name == "set_target_bpm":
        bpm = args.get("bpm")
        lo, hi = TARGET_BPM_RANGE
        if not _finite(bpm) or not (lo <= bpm <= hi):
            raise ProtocolError("bad_args", f"bpm must be within {lo:g}..{hi:g}")
        out["bpm"] = float(bpm)
    elif name == "set_pattern":
        pid = args.get("pattern")
        if not isinstance(pid, str) or len(pid) > 32:
            raise ProtocolError("bad_args", "pattern must be a pattern id")
        out["pattern"] = pid
    elif name == "set_preview":
        out["enabled"] = bool(args.get("enabled", False))
    return out
