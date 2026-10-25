// A/B arrangement comparison. Reports measurable differences only; it does not
// judge which arrangement is musically better. Pure module.

import { gainToDb } from "./mixer.js";

function countBy(list, key) {
  const m = new Map();
  for (const it of list) m.set(it[key], (m.get(it[key]) || 0) + 1);
  return m;
}

/**
 * Pair instruments of A and B: first by uid, then remaining ones by instrument type
 * (in list order). Returns differences for paired instruments plus unmatched ones.
 */
export function compareArrangements(a, b, nameOf = (id) => id) {
  const pairs = [];
  const restA = [];
  const usedB = new Set();
  const byUidB = new Map(b.instruments.map((i) => [i.uid, i]));
  for (const ia of a.instruments) {
    const ib = byUidB.get(ia.uid);
    if (ib && ib.instrument_id === ia.instrument_id) {
      pairs.push([ia, ib]);
      usedB.add(ib.uid);
    } else restA.push(ia);
  }
  const onlyA = [];
  for (const ia of restA) {
    const ib = b.instruments.find((x) => !usedB.has(x.uid) && x.instrument_id === ia.instrument_id);
    if (ib) {
      pairs.push([ia, ib]);
      usedB.add(ib.uid);
    } else onlyA.push(ia);
  }
  const onlyB = b.instruments.filter((x) => !usedB.has(x.uid));

  const rows = pairs.map(([ia, ib]) => {
    const moved = Math.hypot(ib.position[0] - ia.position[0], ib.position[2] - ia.position[2]);
    const dDb = gainToDb(ib.gain) - gainToDb(ia.gain);
    return {
      instrument: nameOf(ia.instrument_id),
      positionA: ia.position, positionB: ib.position,
      movedMeters: round(moved, 2),
      rotationDeltaDeg: round(ib.rotation_y_deg - ia.rotation_y_deg, 1),
      gainDeltaDb: Number.isFinite(dDb) ? round(dDb, 1) : null,
      gainA: ia.gain, gainB: ib.gain,
      mutedChanged: ia.muted !== ib.muted,
      soloChanged: ia.solo !== ib.solo,
      articulationA: ia.articulation, articulationB: ib.articulation,
      articulationChanged: ia.articulation !== ib.articulation,
      changed: moved > 0.01 || Math.abs(ib.rotation_y_deg - ia.rotation_y_deg) > 0.5
        || Math.abs(ib.gain - ia.gain) > 1e-3 || ia.articulation !== ib.articulation
        || ia.muted !== ib.muted || ia.solo !== ib.solo,
    };
  });

  const countsA = countBy(a.instruments, "instrument_id");
  const countsB = countBy(b.instruments, "instrument_id");
  const types = [...new Set([...countsA.keys(), ...countsB.keys()])];
  return {
    countA: a.instruments.length,
    countB: b.instruments.length,
    perType: types.map((t) => ({ instrument: nameOf(t), a: countsA.get(t) || 0, b: countsB.get(t) || 0 })),
    rows,
    onlyA: onlyA.map((i) => nameOf(i.instrument_id)),
    onlyB: onlyB.map((i) => nameOf(i.instrument_id)),
    audio: {
      tempo: [a.audio.tempo_bpm, b.audio.tempo_bpm],
      reverb: [a.audio.reverb_mix, b.audio.reverb_mix],
      listener: [a.listener.preset, b.listener.preset],
    },
    changedCount: rows.filter((r) => r.changed).length + onlyA.length + onlyB.length,
  };
}

const round = (v, nd) => Math.round(v * 10 ** nd) / 10 ** nd + 0;
