"""End-to-end service tests over real HTTP + WebSocket (in-process aiohttp server)."""

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from archestral.server import create_app


async def _client(tmp_path):
    client = TestClient(TestServer(create_app(tmp_path)))
    await client.start_server()
    return client


async def _recv_until(ws, predicate, timeout=20.0):
    seen = []
    async def loop():
        while True:
            msg = json.loads((await ws.receive()).data)
            seen.append(msg)
            if predicate(msg):
                return msg
    return await asyncio.wait_for(loop(), timeout), seen


def test_rest_endpoints(tmp_path):
    async def run():
        c = await _client(tmp_path)
        try:
            caps = await (await c.get("/api/capabilities")).json()
            assert caps["protocol_version"] == 1
            lib = await (await c.get("/api/library")).json()
            assert lib["instruments"][0]["id"] == "violin"
            pats = await (await c.get("/api/patterns")).json()
            assert {p["id"] for p in pats["patterns"]} >= {"4-4"}
            fx = await (await c.get("/api/fixtures")).json()
            assert all(f["synthetic"] for f in fx["fixtures"])
            doc = {"schema_version": 1, "name": "A", "instruments": [
                {"uid": "u1", "instrument_id": "violin", "position": [0, 0, 0], "articulation": "arco"}]}
            r = await c.put("/api/arrangements/my-arr", json=doc)
            assert r.status == 200
            r = await c.put("/api/arrangements/..%2Fx", json=doc)
            assert r.status in (400, 404)
            r = await c.put("/api/arrangements/bad", data="{oops", headers={"Content-Type": "application/json"})
            assert r.status == 400
            assert (await c.get("/api/arrangements/nope")).status == 404
            listing = await (await c.get("/api/arrangements")).json()
            assert [a["id"] for a in listing["arrangements"]] == ["my-arr"]
            r = await c.put("/api/settings", json={"target_bpm": 100})
            assert (await r.json())["settings"]["target_bpm"] == 100
            assert (await c.delete("/api/arrangements/my-arr")).status == 200
            assert (await c.get("/")).status == 200
        finally:
            await c.close()
    asyncio.run(run())


def test_websocket_recorded_session_produces_beats_and_feedback(tmp_path):
    async def run():
        c = await _client(tmp_path)
        try:
            ws = await c.ws_connect("/ws")
            hello = json.loads((await ws.receive()).data)
            assert hello["type"] == "hello" and hello["protocol_version"] == 1
            await ws.send_str(json.dumps({"v": 1, "type": "command", "name": "set_source",
                                          "args": {"source": "recorded", "fixture": "faster_120bpm"}}))
            await ws.send_str(json.dumps({"v": 1, "type": "command", "name": "start"}))
            beat, seen = await _recv_until(ws, lambda m: m["type"] == "beat")
            assert beat["confidence"] > 0.5
            fb, _ = await _recv_until(ws, lambda m: m["type"] == "feedback" and m["estimated_bpm"] is not None)
            assert fb["estimated_bpm"] == pytest.approx(120, rel=0.05)
            assert any(m["type"] == "status" and m["input"]["test_input"] for m in seen)
            await ws.send_str(json.dumps({"v": 1, "type": "command", "name": "stop"}))
            summary, _ = await _recv_until(ws, lambda m: m["type"] == "summary")
            assert summary["beat_count"] >= 3
            assert not (tmp_path / "recordings").exists()     # test input is never recorded
            await ws.send_str("garbage")
            err, _ = await _recv_until(ws, lambda m: m["type"] == "error")
            assert err["code"] == "bad_json"
            await ws.close()
        finally:
            await c.close()
    asyncio.run(run())


def test_websocket_mouse_samples_feed_same_analyzer(tmp_path):
    from archestral.analysis.patterns import builtin_pattern, ideal_trajectory

    async def run():
        c = await _client(tmp_path)
        try:
            ws = await c.ws_connect("/ws")
            await ws.send_str(json.dumps({"v": 1, "type": "command", "name": "set_source",
                                          "args": {"source": "mouse"}}))
            await ws.send_str(json.dumps({"v": 1, "type": "command", "name": "start"}))
            t, xy = ideal_trajectory(builtin_pattern("4-4"), 100, 4, 60)
            rows = [[float(a), float(b), float(d)] for a, (b, d) in zip(t, xy)]
            for i in range(0, len(rows), 30):
                await ws.send_str(json.dumps({"v": 1, "type": "samples", "source": "mouse",
                                              "points": rows[i:i + 30]}))
            await asyncio.sleep(0.3)
            await ws.send_str(json.dumps({"v": 1, "type": "command", "name": "stop"}))
            summary, _ = await _recv_until(ws, lambda m: m["type"] == "summary")
            assert summary["beat_count"] >= 8
            assert summary["estimated_bpm"] == pytest.approx(100, rel=0.05)
            await ws.close()
            # live (non-test) sessions are recorded in the fixture format for offline tuning
            recs = list((tmp_path / "recordings").glob("*-mouse.json"))
            assert len(recs) == 1
            doc = json.loads(recs[0].read_text())
            assert doc["synthetic"] is False and doc["recorded_live"] is True
            assert len(doc["samples"]) == len(rows)
            assert doc["summary"]["beat_count"] == summary["beat_count"]
        finally:
            await c.close()
    asyncio.run(run())
