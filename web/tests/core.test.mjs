// Unit tests for the pure client modules. Run: node --test web/tests
import assert from "node:assert/strict";
import { test } from "node:test";
import { compareArrangements } from "../js/core/compare.js";
import { fmt, signed } from "../js/core/format.js";
import { anySolo, azimuth, effectiveGain, inverseDistanceGain, rmsDb } from "../js/core/mixer.js";
import { command, parseServerMessage, samplesMessage } from "../js/core/protocol.js";
import { checkPlacement, findFreeSpot, newId, slugify, snap } from "../js/core/stage.js";

const env = (o) => JSON.stringify({ v: 1, seq: 1, ts: 1.5, ...o });

test("protocol parses valid server messages", () => {
  const r = parseServerMessage(env({ type: "beat", index: 3, t: 2.1, beat_in_bar: 2, confidence: 0.9, amplitude: 1.1 }));
  assert.equal(r.ok, true);
  assert.equal(r.msg.beat_in_bar, 2);
  const f = parseServerMessage(env({ type: "feedback", state: "running", estimated_bpm: null, target_bpm: 90,
    tempo_deviation_pct: null, similarity: { estimate: null }, beat_count: 0 }));
  assert.equal(f.ok, true);
});

test("protocol rejects malformed or unexpected messages", () => {
  for (const bad of [
    "nope", "[1]", env({ type: "eval" }), JSON.stringify({ v: 2, type: "pong", seq: 1, ts: 1 }),
    env({ type: "beat", index: "x", t: 1, beat_in_bar: 1, confidence: 1, amplitude: 1 }),
    env({ type: "samples", points: [[1, 2]] }),
    env({ type: "feedback", state: "running", estimated_bpm: "fast", target_bpm: 90, tempo_deviation_pct: null, similarity: {}, beat_count: 0 }),
    JSON.stringify({ v: 1, type: "pong" }),
  ]) assert.equal(parseServerMessage(bad).ok, false, bad);
  assert.equal(parseServerMessage("x".repeat(600 * 1024)).ok, false);
});

test("protocol encodes commands and samples with versioned envelope", () => {
  const c = JSON.parse(command("set_target_bpm", { bpm: 100 }));
  assert.deepEqual([c.v, c.type, c.name, c.args.bpm], [1, "command", "set_target_bpm", 100]);
  const s = JSON.parse(samplesMessage("mouse", [[1, 0.5, 0.5, 1]]));
  assert.equal(s.source, "mouse");
  assert.ok(s.seq > c.seq);
});

test("mute and solo rules", () => {
  const a = { gain: 0.8, muted: false, solo: false };
  const b = { gain: 0.5, muted: false, solo: true };
  const m = { gain: 0.5, muted: true, solo: true };
  assert.equal(effectiveGain(a, anySolo([a])), 0.8);
  assert.equal(effectiveGain(a, anySolo([a, b])), 0);
  assert.equal(effectiveGain(b, anySolo([a, b])), 0.5);
  assert.equal(effectiveGain(m, true), 0, "mute wins over solo");
  assert.equal(effectiveGain({ gain: 9, muted: false, solo: false }, false), 2, "gain is clamped");
});

test("inverse distance gain matches the Web Audio formula", () => {
  assert.equal(inverseDistanceGain(1, 1.5, 40, 1), 1);
  assert.ok(Math.abs(inverseDistanceGain(3, 1.5, 40, 1) - 0.5) < 1e-12);
  assert.ok(inverseDistanceGain(10, 1.5, 40, 1) < inverseDistanceGain(5, 1.5, 40, 1), "farther is quieter");
});

test("azimuth sign: listener facing -z sees +x on the right", () => {
  const right = azimuth([0, 0, 0], [0, 0, -1], [3, 0, -3]);
  const left = azimuth([0, 0, 0], [0, 0, -1], [-3, 0, -3]);
  assert.ok(right > 0 && left < 0);
  assert.ok(Math.abs(azimuth([0, 0, 0], [0, 0, -1], [0, 0, -5])) < 1e-12);
});

test("rms in dBFS", () => {
  assert.equal(rmsDb(new Float32Array(16)), -Infinity);
  assert.ok(Math.abs(rmsDb(new Float32Array(16).fill(1))) < 1e-9);
});

const STAGE = { half_width: 7, depth_front: 3, depth_back: 6.5, min_spacing: 0.9, grid: 0.5 };

test("placement bounds and spacing", () => {
  const insts = [{ uid: "a", instrument_id: "violin", position: [0, 0, 0] }];
  assert.equal(checkPlacement(STAGE, insts, "b", 2, 0).ok, true);
  assert.match(checkPlacement(STAGE, insts, "b", 8, 0).reason, /stage/);
  assert.match(checkPlacement(STAGE, insts, "b", 0, 3.5).reason, /forward/);
  assert.match(checkPlacement(STAGE, insts, "b", 0, -7).reason, /back/);
  assert.match(checkPlacement(STAGE, insts, "b", 0.5, 0).reason, /Too close/);
  assert.equal(checkPlacement(STAGE, insts, "a", 0.1, 0).ok, true, "an instrument does not collide with itself");
  assert.equal(checkPlacement(STAGE, insts, "b", NaN, 0).ok, false);
});

test("snapping and free-spot search", () => {
  assert.equal(snap(1.26, 0.5), 1.5);
  assert.equal(snap(1.26, 0), 1.26);
  const insts = [{ uid: "a", position: [0, 0, 0] }];
  const spot = findFreeSpot(STAGE, insts, 0, 0);
  assert.ok(spot && Math.hypot(spot[0], spot[1]) >= 0.9);
});

test("ids are safe slugs", () => {
  assert.equal(slugify("My  Arrangement!/../x"), "my-arrangement-x");
  assert.equal(slugify("???"), "arrangement");
  assert.match(newId("Test", 1000), /^test-[a-z0-9]+$/);
  assert.ok(newId("x".repeat(200)).length <= 64);
});

test("arrangement comparison reports measurable differences", () => {
  const base = {
    audio: { tempo_bpm: 72, reverb_mix: 0.25 }, listener: { preset: "podium" },
    instruments: [
      { uid: "v", instrument_id: "violin", position: [-3, 0, 0], rotation_y_deg: 0, gain: 0.8, muted: false, solo: false, articulation: "arco" },
      { uid: "c", instrument_id: "cello", position: [3, 0, 0], rotation_y_deg: 0, gain: 0.8, muted: false, solo: false, articulation: "arco" },
    ],
  };
  const b = JSON.parse(JSON.stringify(base));
  b.instruments[0].position = [0, 0, -4];
  b.instruments[1].gain = 0.4;
  b.instruments[1].articulation = "pizzicato";
  b.instruments[1].uid = "different-uid";    // still paired by instrument type
  b.instruments.push({ uid: "f", instrument_id: "flute", position: [0, 0, -2], rotation_y_deg: 0, gain: 0.7, muted: false, solo: false, articulation: "legato" });
  b.listener.preset = "audience";
  const c = compareArrangements(base, b);
  assert.equal(c.countA, 2);
  assert.equal(c.countB, 3);
  assert.deepEqual(c.onlyB, ["flute"]);
  const v = c.rows.find((r) => r.instrument === "violin");
  assert.equal(v.movedMeters, 5);
  const cello = c.rows.find((r) => r.instrument === "cello");
  assert.equal(cello.gainDeltaDb, -6);
  assert.equal(cello.articulationChanged, true);
  assert.equal(c.changedCount, 3);
  assert.deepEqual(c.audio.listener, ["podium", "audience"]);
  assert.equal(compareArrangements(base, base).changedCount, 0);
});

test("formatting never invents numbers", () => {
  assert.equal(fmt(null), "—");
  assert.equal(fmt(NaN), "—");
  assert.equal(fmt(90.04, 1), "90.0");
  assert.equal(signed(3.21, 1, "%"), "+3.2%");
  assert.equal(signed(undefined), "—");
});
