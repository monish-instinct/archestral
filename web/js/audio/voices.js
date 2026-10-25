// Synthesized TEST voices. They make routing, articulation and spatial effects
// audible without licensed samples; they are not realistic instrument models.

export const midiToHz = (m) => 440 * Math.pow(2, (m - 69) / 12);

const pluckCache = new Map();

/** Karplus-Strong plucked string rendered into a buffer (pizzicato). */
function pluckBuffer(ctx, freq) {
  const key = `${ctx.sampleRate}:${freq.toFixed(2)}`;
  if (pluckCache.has(key)) return pluckCache.get(key);
  const sr = ctx.sampleRate;
  const len = Math.floor(sr * 1.4);
  const buf = ctx.createBuffer(1, len, sr);
  const out = buf.getChannelData(0);
  const n = Math.max(2, Math.round(sr / freq));
  const ring = new Float32Array(n);
  let seed = 99991;
  for (let i = 0; i < n; i++) {
    seed = (seed * 16807) % 2147483647;
    ring[i] = (seed / 2147483647) * 2 - 1;
  }
  let idx = 0;
  for (let i = 0; i < len; i++) {
    const next = (idx + 1) % n;
    const v = 0.5 * (ring[idx] + ring[next]) * 0.994;
    out[i] = ring[idx];
    ring[idx] = v;
    idx = next;
  }
  pluckCache.set(key, buf);
  return buf;
}

function envelope(ctx, gainParam, t, dur, peak, attack, release) {
  gainParam.setValueAtTime(0, t);
  gainParam.linearRampToValueAtTime(peak, t + attack);
  gainParam.setValueAtTime(peak, t + Math.max(attack, dur - release));
  gainParam.linearRampToValueAtTime(0, t + dur);
}

function vibrato(ctx, t, end, freq, depth, delay = 0.18) {
  const lfo = ctx.createOscillator();
  lfo.frequency.value = 5.4;
  const g = ctx.createGain();
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(freq * depth, t + delay + 0.2);
  lfo.connect(g);
  lfo.start(t);
  lfo.stop(end);
  return g;
}

function bowed(ctx, out, f, t, dur, vel, art) {
  const staccato = art === "staccato";
  const d = staccato ? Math.min(dur, 0.22) : dur;
  const amp = ctx.createGain();
  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.value = Math.min(9000, f * 7);
  filter.Q.value = 0.8;
  const end = t + d + 0.05;
  const vib = staccato ? null : vibrato(ctx, t, end, f, 0.006);
  for (const det of [-6, 5]) {
    const o = ctx.createOscillator();
    o.type = "sawtooth";
    o.frequency.value = f;
    o.detune.value = det;
    if (vib) vib.connect(o.frequency);
    o.connect(filter);
    o.start(t);
    o.stop(end);
  }
  filter.connect(amp);
  if (art === "tremolo") {
    const trem = ctx.createGain();
    const lfo = ctx.createOscillator();
    lfo.type = "triangle";
    lfo.frequency.value = 13;
    const depth = ctx.createGain();
    depth.gain.value = 0.45;
    trem.gain.value = 0.55;
    lfo.connect(depth).connect(trem.gain);
    lfo.start(t);
    lfo.stop(end);
    amp.connect(trem).connect(out);
  } else {
    amp.connect(out);
  }
  envelope(ctx, amp.gain, t, d, 0.16 * vel, staccato ? 0.012 : 0.09, staccato ? 0.06 : 0.18);
}

function pizz(ctx, out, f, t, vel) {
  const src = ctx.createBufferSource();
  src.buffer = pluckBuffer(ctx, f);
  const g = ctx.createGain();
  g.gain.value = 0.55 * vel;
  const lp = ctx.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = Math.min(8000, f * 8);
  src.connect(lp).connect(g).connect(out);
  src.start(t);
}

function flute(ctx, out, f, t, dur, vel, art) {
  const staccato = art === "staccato";
  const d = staccato ? Math.min(dur, 0.2) : dur;
  const end = t + d + 0.05;
  const amp = ctx.createGain();
  const vib = staccato ? null : vibrato(ctx, t, end, f, 0.005, 0.25);
  for (const [mult, lvl, type] of [[1, 1, "sine"], [2, 0.18, "sine"], [3, 0.05, "triangle"]]) {
    const o = ctx.createOscillator();
    o.type = type;
    o.frequency.value = f * mult;
    if (vib && mult === 1) vib.connect(o.frequency);
    const g = ctx.createGain();
    g.gain.value = lvl;
    o.connect(g).connect(amp);
    o.start(t);
    o.stop(end);
  }
  // breath noise
  const noise = ctx.createBufferSource();
  noise.buffer = noiseBuffer(ctx);
  const bp = ctx.createBiquadFilter();
  bp.type = "bandpass";
  bp.frequency.value = f * 2;
  bp.Q.value = 1.2;
  const ng = ctx.createGain();
  ng.gain.value = 0.05;
  noise.connect(bp).connect(ng).connect(amp);
  noise.start(t);
  noise.stop(end);
  amp.connect(out);
  envelope(ctx, amp.gain, t, d, 0.2 * vel, staccato ? 0.02 : 0.07, 0.1);
}

function brass(ctx, out, f, t, dur, vel, art) {
  const staccato = art === "staccato";
  const d = staccato ? Math.min(dur, 0.25) : dur;
  const end = t + d + 0.05;
  const o = ctx.createOscillator();
  o.type = "sawtooth";
  o.frequency.value = f;
  const lp = ctx.createBiquadFilter();
  lp.type = "lowpass";
  lp.Q.value = 1.5;
  lp.frequency.setValueAtTime(f * 1.2, t);
  lp.frequency.linearRampToValueAtTime(f * (2.5 + 2.5 * vel), t + 0.07);
  lp.frequency.setTargetAtTime(f * 3, t + 0.1, 0.2);
  const amp = ctx.createGain();
  o.connect(lp).connect(amp).connect(out);
  o.start(t);
  o.stop(end);
  envelope(ctx, amp.gain, t, d, 0.15 * vel, 0.05, 0.12);
}

function timpaniHit(ctx, out, f, t, vel) {
  const o = ctx.createOscillator();
  o.frequency.setValueAtTime(f * 1.03, t);
  o.frequency.exponentialRampToValueAtTime(f, t + 0.15);
  const o2 = ctx.createOscillator();
  o2.frequency.value = f * 1.5;
  const g = ctx.createGain();
  const g2 = ctx.createGain();
  g.gain.setValueAtTime(0.45 * vel, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 1.6);
  g2.gain.setValueAtTime(0.12 * vel, t);
  g2.gain.exponentialRampToValueAtTime(0.001, t + 0.7);
  o.connect(g).connect(out);
  o2.connect(g2).connect(out);
  const n = ctx.createBufferSource();
  n.buffer = noiseBuffer(ctx);
  const lp = ctx.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 900;
  const ng = ctx.createGain();
  ng.gain.setValueAtTime(0.25 * vel, t);
  ng.gain.exponentialRampToValueAtTime(0.001, t + 0.08);
  n.connect(lp).connect(ng).connect(out);
  for (const node of [o, o2]) { node.start(t); node.stop(t + 1.7); }
  n.start(t);
  n.stop(t + 0.1);
}

let _noise = null;
function noiseBuffer(ctx) {
  if (_noise && _noise.sampleRate === ctx.sampleRate) return _noise;
  const len = ctx.sampleRate * 2;
  _noise = ctx.createBuffer(1, len, ctx.sampleRate);
  const d = _noise.getChannelData(0);
  let seed = 4242;
  for (let i = 0; i < len; i++) {
    seed = (seed * 16807) % 2147483647;
    d[i] = (seed / 2147483647) * 2 - 1;
  }
  return _noise;
}

/** Schedule one note. `voice` and `articulation` come from the instrument library. */
export function playNote(ctx, out, voice, articulation, midi, t, dur, vel = 0.8) {
  const f = midiToHz(midi);
  switch (voice) {
    case "bowed_string":
      if (articulation === "pizzicato") pizz(ctx, out, f, t, vel);
      else bowed(ctx, out, f, t, dur, vel, articulation);
      break;
    case "flute":
      flute(ctx, out, f, t, dur, vel, articulation);
      break;
    case "brass":
      brass(ctx, out, f, t, dur, vel, articulation);
      break;
    case "timpani":
      if (articulation === "roll") {
        const step = 1 / 14;
        for (let k = 0; k * step < dur; k++) timpaniHit(ctx, out, f, t + k * step, vel * (0.45 + 0.1 * (k % 2)));
      } else timpaniHit(ctx, out, f, t, vel);
      break;
    default:
      throw new Error(`unknown voice ${voice}`);
  }
}

/** Metronome click. Accented clicks are higher. */
export function click(ctx, out, t, accent = false, gain = 0.5) {
  const o = ctx.createOscillator();
  o.frequency.value = accent ? 2000 : 1400;
  const g = ctx.createGain();
  g.gain.setValueAtTime(gain, t);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.04);
  o.connect(g).connect(out);
  o.start(t);
  o.stop(t + 0.05);
}
