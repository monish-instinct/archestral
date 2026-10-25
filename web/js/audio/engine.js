// Web Audio engine: master bus, generated-impulse reverb, spatial channels and
// output metering. Created lazily on a user gesture (browser autoplay policy).
import { rmsDb } from "../core/mixer.js";

export class AudioEngine extends EventTarget {
  constructor() {
    super();
    this.ctx = null;
    this.state = "not-started";   // not-started | running | suspended | unavailable
    this.error = null;
  }

  /** Create/resume the AudioContext. Must be called from a user gesture the first time. */
  async ensure() {
    if (this.state === "unavailable") return null;
    if (!this.ctx) {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) {
        this._set("unavailable", "Web Audio is not supported by this browser.");
        return null;
      }
      try {
        this.ctx = new Ctor({ latencyHint: "interactive" });
      } catch (e) {
        this._set("unavailable", `Could not start audio: ${e.message}`);
        return null;
      }
      this._build();
      this.ctx.onstatechange = () => this._set(this.ctx.state === "running" ? "running" : "suspended");
    }
    if (this.ctx.state !== "running") {
      try { await this.ctx.resume(); } catch { /* reported via state */ }
    }
    this._set(this.ctx.state === "running" ? "running" : "suspended");
    return this.ctx;
  }

  _set(state, error = null) {
    this.state = state;
    if (error) this.error = error;
    this.dispatchEvent(new CustomEvent("state", { detail: state }));
  }

  _build() {
    const ctx = this.ctx;
    this.master = ctx.createGain();
    this.master.gain.value = 0.8;
    this.limiter = ctx.createDynamicsCompressor();     // protects ears/speakers from summed peaks
    this.limiter.threshold.value = -6;
    this.limiter.ratio.value = 12;
    this.master.connect(this.limiter).connect(ctx.destination);

    this.reverbSend = ctx.createGain();
    this.convolver = ctx.createConvolver();
    this.convolver.buffer = makeImpulse(ctx, 2.4, 2.8);
    this.reverbReturn = ctx.createGain();
    this.reverbReturn.gain.value = 0.25;
    this.reverbSend.connect(this.convolver).connect(this.reverbReturn).connect(this.master);

    // Metering taps the post-limiter stereo signal.
    const split = ctx.createChannelSplitter(2);
    this.limiter.connect(split);
    this.analysers = [0, 1].map((ch) => {
      const a = ctx.createAnalyser();
      a.fftSize = 2048;
      split.connect(a, ch);
      return a;
    });
    this._meterBuf = new Float32Array(2048);

    // Non-spatial bus (conductor mode, metronome)
    this.directBus = ctx.createGain();
    this.directBus.connect(this.master);
    this.directBus.connect(this.reverbSend);
  }

  setMaster(g) { if (this.ctx) this.master.gain.setTargetAtTime(g, this.ctx.currentTime, 0.02); }
  setReverb(mix) { if (this.ctx) this.reverbReturn.gain.setTargetAtTime(mix, this.ctx.currentTime, 0.05); }

  /** Output levels in dBFS for the left and right channel. */
  levels() {
    if (!this.ctx) return [-Infinity, -Infinity];
    return this.analysers.map((a) => {
      a.getFloatTimeDomainData(this._meterBuf);
      return rmsDb(this._meterBuf);
    });
  }

  /** A gain -> PannerNode chain for one positioned instrument. */
  createSpatialChannel(spatial, panningModel = "HRTF") {
    const ctx = this.ctx;
    const input = ctx.createGain();       // voices connect here
    const volume = ctx.createGain();      // user volume x mute/solo
    const panner = ctx.createPanner();
    panner.panningModel = panningModel;
    panner.distanceModel = "inverse";
    panner.refDistance = spatial.ref_distance;
    panner.maxDistance = spatial.max_distance;
    panner.rolloffFactor = spatial.rolloff;
    panner.coneInnerAngle = spatial.cone_inner_deg;
    panner.coneOuterAngle = spatial.cone_outer_deg;
    panner.coneOuterGain = spatial.cone_outer_gain;
    input.connect(volume).connect(panner);
    panner.connect(this.master);
    panner.connect(this.reverbSend);
    return {
      input, volume, panner,
      dispose() { try { input.disconnect(); volume.disconnect(); panner.disconnect(); } catch { /* already gone */ } },
    };
  }

  setListener(pos, forward, up = [0, 1, 0]) {
    if (!this.ctx) return;
    const l = this.ctx.listener;
    const t = this.ctx.currentTime;
    if (l.positionX) {
      l.positionX.setTargetAtTime(pos[0], t, 0.03);
      l.positionY.setTargetAtTime(pos[1], t, 0.03);
      l.positionZ.setTargetAtTime(pos[2], t, 0.03);
      l.forwardX.setTargetAtTime(forward[0], t, 0.03);
      l.forwardY.setTargetAtTime(forward[1], t, 0.03);
      l.forwardZ.setTargetAtTime(forward[2], t, 0.03);
      l.upX.value = up[0]; l.upY.value = up[1]; l.upZ.value = up[2];
    } else {
      l.setPosition(...pos);
      l.setOrientation(...forward, ...up);
    }
    this.listener = { pos, forward };
  }
}

function makeImpulse(ctx, seconds, decay) {
  const rate = ctx.sampleRate;
  const len = Math.floor(rate * seconds);
  const buf = ctx.createBuffer(2, len, rate);
  let seed = 1234567;
  const rand = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff) * 2 - 1;
  for (let ch = 0; ch < 2; ch++) {
    const d = buf.getChannelData(ch);
    for (let i = 0; i < len; i++) {
      const pre = i < rate * 0.012 ? 0 : 1;   // short pre-delay
      d[i] = rand() * Math.pow(1 - i / len, decay) * pre;
    }
  }
  return buf;
}
