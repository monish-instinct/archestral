"""Local service: serves the web client, a WebSocket for live conducting data,
and a small REST API for settings, patterns, the instrument library and arrangements.

Binds to 127.0.0.1 by default. Exposing it on another interface requires the
explicit --host option.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from . import PROTOCOL_VERSION, __version__
from .analysis.config import AnalysisConfig, config_from_dict
from .analysis.patterns import load_patterns
from .analysis.session import SessionAnalyzer
from .analysis.trajectory import Sample
from .protocol import Encoder, ProtocolError, decode_client
from .storage import ArrangementStore, SettingsStore, ValidationError, default_data_dir, load_library
from .tracking import ExternalSource, TrackingSource
from .tracking.recorded import RecordedSource, list_fixtures
from .tracking.webcam import WebcamSource, vision_available

log = logging.getLogger("archestral.server")
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
SERVICE_KEY: web.AppKey["ConductorService"] = web.AppKey("service")
TICK_S = 1 / 60
SAMPLE_BROADCAST_S = 1 / 30
STATUS_INTERVAL_S = 1.0


class RateLimitedLog:
    """Log a repeated warning at most once per interval, with a suppressed count."""

    def __init__(self, interval_s: float = 5.0) -> None:
        self.interval = interval_s
        self._last: dict[str, float] = {}
        self._suppressed: dict[str, int] = {}

    def warning(self, key: str, msg: str, *args) -> None:
        now = time.monotonic()
        if now - self._last.get(key, -1e9) >= self.interval:
            n = self._suppressed.pop(key, 0)
            log.warning(msg + (f" (+{n} similar suppressed)" if n else ""), *args)
            self._last[key] = now
        else:
            self._suppressed[key] = self._suppressed.get(key, 0) + 1


class ConductorService:
    """Owns the active input source and the single analysis pipeline."""

    def __init__(self, settings: SettingsStore) -> None:
        self.settings = settings
        self.patterns = load_patterns()
        self.clients: set[web.WebSocketResponse] = set()
        self.encoder = Encoder()
        self.source: TrackingSource | None = None
        self.preview_clients: set[web.WebSocketResponse] = set()
        self.analyzer = self._new_analyzer()
        self._pending_points: list[list[float]] = []
        self._last_samples_sent = 0.0
        self._last_status = 0.0
        self._task: asyncio.Task | None = None
        self.rlog = RateLimitedLog()
        self.last_error: str | None = None
        self.last_sample_wall: float | None = None

    def _new_analyzer(self) -> SessionAnalyzer:
        s = self.settings.data
        cfg, problems = config_from_dict(s.get("analysis"))
        for p in problems:
            log.warning("analysis config: %s", p)
        cfg.target_bpm = float(s.get("target_bpm", 90))
        pattern = self.patterns.get(s.get("pattern", "4-4")) or self.patterns["4-4"]
        return SessionAnalyzer(cfg, pattern)

    # ------------------------------------------------------------------ lifecycle
    def start_loop(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def shutdown(self) -> None:
        if self._task:
            self._task.cancel()
        self._set_source(None)
        for ws in list(self.clients):
            await ws.close()

    def _set_source(self, src: TrackingSource | None) -> None:
        if self.source is not None:
            try:
                self.source.stop()
            except Exception:  # pragma: no cover - defensive cleanup
                log.exception("error stopping source")
        self.source = src
        if src is not None:
            if isinstance(src, WebcamSource):
                src.preview_enabled = bool(self.preview_clients)
            src.start()
            log.info("input source -> %s", src.label)

    # ------------------------------------------------------------------ messaging
    async def broadcast(self, msg_type: str, payload: dict[str, Any] | None = None,
                        only: set[web.WebSocketResponse] | None = None) -> None:
        targets = only if only is not None else self.clients
        if not targets:
            return
        text = self.encoder.encode(msg_type, dict(payload or {}))
        for ws in list(targets):
            if ws.closed:
                self.clients.discard(ws)
                continue
            try:
                await ws.send_str(text)
            except (ConnectionError, RuntimeError):
                self.clients.discard(ws)

    async def emit_events(self, events: list[dict]) -> None:
        for ev in events:
            ev = dict(ev)
            await self.broadcast(ev.pop("type"), ev)

    def status_payload(self) -> dict[str, Any]:
        src = self.source.status() if self.source else {"source": None, "label": "No input selected",
                                                         "test_input": False, "state": "idle", "message": ""}
        return {"input": src, "session_state": self.analyzer.state, "pattern": self.analyzer.pattern.id,
                "target_bpm": self.analyzer.cfg.target_bpm, "last_error": self.last_error,
                "last_sample_age_s": None if self.last_sample_wall is None else
                round(time.monotonic() - self.last_sample_wall, 2)}

    # ------------------------------------------------------------------ main loop
    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # keep the service alive; report the failure
                self.last_error = f"{type(e).__name__}: {e}"
                log.exception("service tick failed")
            await asyncio.sleep(TICK_S)

    async def _tick(self) -> None:
        now = time.monotonic()
        if self.source is not None:
            samples = self.source.poll()
            if samples:
                await self._ingest(samples)
            if isinstance(self.source, WebcamSource) and self.preview_clients:
                jpg = self.source.latest_preview()
                if jpg:
                    await self.broadcast("preview", {"jpeg": base64.b64encode(jpg).decode("ascii")},
                                         only=self.preview_clients)
        if self._pending_points and now - self._last_samples_sent >= SAMPLE_BROADCAST_S:
            pts, self._pending_points = self._pending_points[-120:], []
            self._last_samples_sent = now
            await self.broadcast("samples", {"points": pts})
        if now - self._last_status >= STATUS_INTERVAL_S:
            self._last_status = now
            await self.broadcast("status", self.status_payload())

    async def _ingest(self, samples: list[Sample]) -> None:
        self.last_sample_wall = time.monotonic()
        norm = self.analyzer.norm
        for s in samples:
            events = self.analyzer.push(s)
            if s.is_finite() and s.confidence >= self.analyzer.cfg.min_confidence:
                # Raw points for display, plus the normalized point once calibrated.
                if norm is None:
                    self._pending_points.append([round(s.t, 4), round(s.x, 4), round(s.y, 4)])
                else:
                    nx, ny = norm.apply([s.x, s.y])
                    self._pending_points.append([round(s.t, 4), round(s.x, 4), round(s.y, 4),
                                                 round(float(nx), 4), round(float(ny), 4)])
                norm = self.analyzer.norm
            if events:
                await self.emit_events(events)

    # ------------------------------------------------------------------ commands
    async def handle(self, ws: web.WebSocketResponse, raw: str) -> None:
        try:
            msg = decode_client(raw)
        except ProtocolError as e:
            self.rlog.warning(f"bad:{e.code}", "rejected client message: %s (%s)", e.code, e)
            await self.broadcast("error", {"code": e.code, "message": str(e)}, only={ws})
            return
        if msg.type == "ping":
            await self.broadcast("pong", {"echo_seq": msg.seq}, only={ws})
        elif msg.type == "samples":
            if isinstance(self.source, ExternalSource) and self.source.kind == msg.data["source"]:
                self.source.push([Sample(p[0], p[1], p[2], p[3]) for p in msg.data["points"]])
            else:
                self.rlog.warning("samples_mismatch", "samples from %s ignored; active source is %s",
                                  msg.data["source"], self.source.kind if self.source else None)
        else:
            await self._command(ws, msg.data)

    async def _command(self, ws: web.WebSocketResponse, cmd: dict[str, Any]) -> None:
        name = cmd["name"]
        a = self.analyzer
        log.info("command %s", cmd)
        if name == "set_source" and cmd["source"] == "none":
            if a.state in ("calibrating", "running", "paused"):
                await self.emit_events(a.stop())
            self._set_source(None)
        elif name == "set_source":
            try:
                src = self._make_source(cmd)
            except (FileNotFoundError, ValueError) as e:
                await self.broadcast("error", {"code": "source_unavailable", "message": str(e)}, only={ws})
                return
            if a.state in ("calibrating", "running", "paused"):
                await self.emit_events(a.stop())
            self.analyzer = self._new_analyzer()
            self._set_source(src)
        elif name == "start":
            if self.source is None:
                await self.broadcast("error", {"code": "no_source", "message": "Select an input first."}, only={ws})
                return
            if isinstance(self.source, WebcamSource) and \
                    self.source.status()["camera_state"] in ("unavailable", "error", "stopped"):
                self.source.start()          # retry, e.g. after camera permission was granted
                if self.source.status()["camera_state"] in ("unavailable", "error"):
                    await self.broadcast("error", {"code": "camera_unavailable",
                                                   "message": self.source.status()["message"]}, only={ws})
                    await self.broadcast("status", self.status_payload())
                    return
            self.source.poll()  # drop samples produced before the session started
            await self.emit_events(a.start())
        elif name == "pause":
            await self.emit_events(a.pause())
        elif name == "resume":
            await self.emit_events(a.resume())
        elif name == "stop":
            await self.emit_events(a.stop())
        elif name == "calibrate":
            await self.emit_events(a.recalibrate())
        elif name == "set_target_bpm":
            a.set_target_bpm(cmd["bpm"])
            self.settings.update({"target_bpm": cmd["bpm"]})
        elif name == "set_pattern":
            p = self.patterns.get(cmd["pattern"])
            if p is None:
                await self.broadcast("error", {"code": "bad_pattern", "message": "Unknown pattern."}, only={ws})
                return
            a.set_pattern(p)
            self.settings.update({"pattern": p.id})
        elif name == "set_preview":
            if cmd["enabled"]:
                self.preview_clients.add(ws)
            else:
                self.preview_clients.discard(ws)
            if isinstance(self.source, WebcamSource):
                self.source.preview_enabled = bool(self.preview_clients)
        await self.broadcast("status", self.status_payload())

    def _make_source(self, cmd: dict[str, Any]) -> TrackingSource:
        kind = cmd["source"]
        s = self.settings.data
        if kind == "webcam":
            return WebcamSource(cmd.get("camera", s["camera_index"]), s["mirror_camera"], s["tracked_landmark"])
        if kind == "recorded":
            return RecordedSource(cmd["fixture"])
        return ExternalSource(kind)


# ---------------------------------------------------------------------- HTTP
def _json_error(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status)


async def _read_json(request: web.Request) -> Any:
    if request.content_length is not None and request.content_length > 256 * 1024:
        raise web.HTTPRequestEntityTooLarge(max_size=256 * 1024, actual_size=request.content_length)
    try:
        return await request.json()
    except json.JSONDecodeError as e:
        raise ValidationError("request body is not valid JSON") from e


def create_app(data_dir: Path | None = None) -> web.Application:
    data_dir = Path(data_dir or default_data_dir())
    settings = SettingsStore(data_dir / "settings.json")
    library = load_library()
    store = ArrangementStore(data_dir / "arrangements", library)
    service = ConductorService(settings)
    app = web.Application(client_max_size=512 * 1024)
    app[SERVICE_KEY] = service

    async def on_startup(app):
        service.start_loop()

    async def on_cleanup(app):
        await service.shutdown()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    async def index(_):
        return web.FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    async def capabilities(_):
        ok, msg = vision_available()
        return web.json_response({
            "service": "archestral", "version": __version__, "protocol_version": PROTOCOL_VERSION,
            "vision": {"available": ok, "message": msg},
            "inputs": ["webcam", "mouse", "webxr", "recorded"],
            "settings_problems": settings.problems,
            "analysis_defaults": AnalysisConfig().to_dict(),
            "data_dir": str(data_dir),
        })

    async def get_settings(_):
        return web.json_response({"settings": settings.data, "problems": settings.problems})

    async def put_settings(request):
        try:
            data, problems = settings.update(await _read_json(request))
        except ValidationError as e:
            return _json_error(400, str(e))
        service.analyzer.cfg.target_bpm = float(data["target_bpm"])
        return web.json_response({"settings": data, "problems": problems})

    async def patterns(_):
        return web.json_response({"patterns": [p.to_dict() for p in service.patterns.values()]})

    async def fixtures(_):
        return web.json_response({"fixtures": list_fixtures()})

    async def get_library(_):
        return web.json_response(library)

    async def list_arrangements(_):
        return web.json_response({"arrangements": store.list()})

    async def get_arrangement(request):
        try:
            return web.json_response(store.get(request.match_info["aid"]))
        except FileNotFoundError:
            return _json_error(404, "arrangement not found")
        except ValidationError as e:
            return _json_error(422, f"arrangement file is invalid: {e}")

    async def put_arrangement(request):
        try:
            doc = store.put(request.match_info["aid"], await _read_json(request))
        except ValidationError as e:
            return _json_error(400, str(e))
        return web.json_response(doc)

    async def delete_arrangement(request):
        try:
            store.delete(request.match_info["aid"])
        except FileNotFoundError:
            return _json_error(404, "arrangement not found")
        except ValidationError as e:
            return _json_error(400, str(e))
        return web.json_response({"deleted": request.match_info["aid"]})

    async def websocket(request):
        ws = web.WebSocketResponse(heartbeat=10.0, max_msg_size=64 * 1024)
        await ws.prepare(request)
        service.clients.add(ws)
        log.info("client connected (%d total)", len(service.clients))
        await service.broadcast("hello", {"service": "archestral", "version": __version__,
                                          "protocol_version": PROTOCOL_VERSION}, only={ws})
        await service.broadcast("status", service.status_payload(), only={ws})
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await service.handle(ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    log.warning("websocket error: %s", ws.exception())
        finally:
            service.clients.discard(ws)
            service.preview_clients.discard(ws)
            if isinstance(service.source, WebcamSource):
                service.source.preview_enabled = bool(service.preview_clients)
            log.info("client disconnected (%d total)", len(service.clients))
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/api/capabilities", capabilities)
    app.router.add_get("/api/settings", get_settings)
    app.router.add_put("/api/settings", put_settings)
    app.router.add_get("/api/patterns", patterns)
    app.router.add_get("/api/fixtures", fixtures)
    app.router.add_get("/api/library", get_library)
    app.router.add_get("/api/arrangements", list_arrangements)
    app.router.add_get("/api/arrangements/{aid}", get_arrangement)
    app.router.add_put("/api/arrangements/{aid}", put_arrangement)
    app.router.add_delete("/api/arrangements/{aid}", delete_arrangement)
    app.router.add_static("/static/", WEB_DIR, show_index=False)
    return app
