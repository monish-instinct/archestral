// Mixer and spatial math shared by the composer UI and diagnostics. Pure module.

/**
 * Effective linear gain for one instrument.
 * Rules: muted -> 0 always; if any instrument is soloed, non-soloed ones -> 0.
 */
export function effectiveGain(inst, anySolo) {
  if (inst.muted) return 0;
  if (anySolo && !inst.solo) return 0;
  return clamp(inst.gain, 0, 2);
}

export function anySolo(instruments) {
  return instruments.some((i) => i.solo);
}

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
export const gainToDb = (g) => (g <= 0 ? -Infinity : 20 * Math.log10(g));
export const dbToGain = (db) => Math.pow(10, db / 20);

/** Web Audio "inverse" distance model (same formula the PannerNode uses). */
export function inverseDistanceGain(distance, refDistance, maxDistance, rolloff) {
  const d = clamp(distance, refDistance, maxDistance);
  return refDistance / (refDistance + rolloff * (d - refDistance));
}

/** Horizontal angle of a source relative to a listener facing `forward` (radians, + = right). */
export function azimuth(listenerPos, forward, sourcePos) {
  const dx = sourcePos[0] - listenerPos[0];
  const dz = sourcePos[2] - listenerPos[2];
  const fx = forward[0];
  const fz = forward[2];
  // right vector of a y-up listener facing (fx, fz) is (-fz, fx)
  const along = dx * fx + dz * fz;
  const right = dx * -fz + dz * fx;
  return Math.atan2(right, along);
}

export function distance3(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/** RMS of a Float32Array in dBFS (-Infinity for silence). */
export function rmsDb(buf) {
  let s = 0;
  for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
  const rms = Math.sqrt(s / Math.max(1, buf.length));
  return rms > 0 ? 20 * Math.log10(rms) : -Infinity;
}
