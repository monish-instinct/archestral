// Conductor mode: input selection, session control, live visualisation,
// feedback metrics and beat-reactive audio.
import { DASH, duration, fmt, signed } from "../core/format.js";
import { $, $$, logEvent, setupCanvas, toast } from "../ui.js";
import { click, playNote } from "../audio/voices.js";
import { PARTS, chordAt, LOOP_BEATS } from "../audio/score.js";
import { XRConductingInput } from "./xr.js";

const TRAIL_SECONDS = 2.5;
const BEAT_FADE_S = 2.0;
const TEMPO_WINDOW_S = 60;

export class ConductorMode {
  constructor({ link, engine, settings, patterns, fixtures, onSummary }) {
    this.link = link;
    this.engine = engine;
    this.settings = settings;
    this.patterns = new Map(patterns.map((p) => [p.id, p]));
    this.fixtures = fixtures;
    this.onSummary = onSummary;
    this.input = settings.input_mode;
    this.status = null;
    this.feedback = null;
    this.sessionState = "idle";
    this.sessionMessage = "";
    this.calibration = null;
    this.trail = [];             // [wallTime, x, y] raw coordinates
    this.beats = [];             // {wall, x, y, n}
    this.tempoHistory = [];      // [wallTime, bpm|null, target]
    this.loopBeat = -1;
    this.visible = false;
    this.mouse = { down: false, buf: [] };
    this.xr = new XRConductingInput(link);
    this._bind();
  }

  // ------------------------------------------------------------------ setup
  _bind() {
    const link = this.link;
    link.addEventListener("status", (e) => this._onStatus(e.detail));
    link.addEventListener("samples", (e) => this._onSamples(e.detail));
    link.addEventListener("beat", (e) => this._onBeat(e.detail));
    link.addEventListener("feedback", (e) => this._onFeedback(e.detail));
    link.addEventListener("session_state", (e) => {
      this.sessionState = e.detail.state;
      this.sessionMessage = e.detail.message;
      logEvent(`Session: ${e.detail.message}`);
      this._renderControls();
    });
    link.addEventListener("calibration", (e) => { this.calibration = e.detail.normalization; });
    link.addEventListener("summary", (e) => this.onSummary(e.detail, this.tempoHistory.slice()));
    link.addEventListener("preview", (e) => {
      const img = $("#preview");
      img.src = `data:image/jpeg;base64,${e.detail.jpeg}`;
      img.hidden = !$("#show-preview").checked || this.input !== "webcam";
    });
    link.addEventListener("error", (e) => toast(e.detail.message, "bad"));
    link.addEventListener("connection", (e) => {
      if (e.detail === "open" && this.visible && !this._active()) this._selectSource();
      this._renderBanners();
    });

    $$("#input-seg button").forEach((b) => b.addEventListener("click", () => this.setInput(b.dataset.input)));
    $("#camera-index").value = String(this.settings.camera_index);
    const guarded = () => {
      if (this._active()) {
        toast("Stop the current session before changing the input.", "warn");
        return;
      }
      this._selectSource();
    };
    $("#camera-index").addEventListener("change", guarded);
    const fx = $("#fixture-select");
    fx.replaceChildren(...this.fixtures.map((f) => new Option(`${f.name}`, f.id)));
    if (this.fixtures.some((f) => f.id === "reference_90bpm")) fx.value = "reference_90bpm";
    fx.addEventListener("change", guarded);
    $("#show-preview").checked = this.settings.ui.show_preview;
    $("#show-preview").addEventListener("change", (e) => {
      link.command("set_preview", { enabled: e.target.checked });
      if (!e.target.checked) $("#preview").hidden = true;
    });

    const ps = $("#pattern-select");
    ps.replaceChildren(...[...this.patterns.values()].map((p) => new Option(p.name, p.id)));
    ps.value = this.patterns.has(this.settings.pattern) ? this.settings.pattern : "4-4";
    ps.addEventListener("change", () => {
      link.command("set_pattern", { pattern: ps.value });
      this._renderBeatDots();
    });

    const bpm = $("#target-bpm");
    bpm.value = this.settings.target_bpm;
    const setBpm = (v) => {
      const n = Math.round(Number(v));
      // Empty or out-of-range input is rejected (not clamped) so a half-typed value
      // never silently becomes 20 or 300 BPM.
      if (String(v).trim() === "" || !Number.isFinite(n) || n < 40 || n > 200) {
        bpm.value = this.settings.target_bpm;
        toast("Target tempo must be between 40 and 200 BPM.", "warn");
        return;
      }
      bpm.value = n;
      if (n === this.settings.target_bpm) return;
      link.command("set_target_bpm", { bpm: n });
      this.settings.target_bpm = n;
    };
    bpm.addEventListener("change", () => setBpm(bpm.value));
    $$(".stepper button").forEach((b) => b.addEventListener("click", () => setBpm(Number(bpm.value) + Number(b.dataset.step))));

    $("#btn-start").addEventListener("click", () => this.start());
    $("#btn-pause").addEventListener("click", () => link.command(this.sessionState === "paused" ? "resume" : "pause"));
    $("#btn-stop").addEventListener("click", () => link.command("stop"));
    $("#btn-calibrate").addEventListener("click", () => link.command("calibrate"));
    $("#opt-reference").checked = this.settings.audio.reference_metronome;

    this._bindPad();
    this._bindXR();
    this._renderBeatDots();
    this._renderControls();
  }

  _bindPad() {
    const pad = $("#pad");
    const toNorm = (ev) => {
      const r = pad.getBoundingClientRect();
      const s = Math.min(r.width, r.height);
      return [0.5 + (ev.clientX - r.left - r.width / 2) / s, 0.5 - (ev.clientY - r.top - r.height / 2) / s];
    };
    pad.addEventListener("pointerdown", (ev) => {
      if (this.input !== "mouse") return;
      this.mouse.down = true;
      pad.setPointerCapture(ev.pointerId);
    });
    pad.addEventListener("pointermove", (ev) => {
      if (this.input !== "mouse" || !this.mouse.down) return;
      // Coalesced events give the full browser input rate, not just the frame rate.
      const events = ev.getCoalescedEvents ? ev.getCoalescedEvents() : [ev];
      for (const e of events.length ? events : [ev]) {
        const [x, y] = toNorm(e);
        this.mouse.buf.push([e.timeStamp / 1000, x, y, 1]);   // ms since page load -> s
      }
    });
    const up = () => { this.mouse.down = false; };
    pad.addEventListener("pointerup", up);
    pad.addEventListener("pointercancel", up);
    setInterval(() => this._flushMouse(), 33);
  }

  _flushMouse() {
    if (!this.mouse.buf.length) return;
    const pts = this.mouse.buf.splice(0);
    const clean = [];
    let last = this._lastMouseT ?? -Infinity;
    for (const p of pts) {
      if (p[0] > last + 1e-4) { clean.push(p); last = p[0]; }
    }
    this._lastMouseT = last;
    for (let i = 0; i < clean.length; i += 200) this.link.samples("mouse", clean.slice(i, i + 200));
  }

  async _bindXR() {
    const hint = $("#xr-hint");
    const btn = $("#xr-enter");
    const support = await this.xr.checkSupport();
    hint.textContent = support.message;
    btn.disabled = !support.supported;
    btn.addEventListener("click", async () => {
      try {
        await this.engine.ensure();
        await this.xr.enter();
      } catch (e) {
        toast(`Could not start VR: ${e.message}`, "bad");
      }
    });
  }

  // ------------------------------------------------------------------ input & session
  setInput(kind) {
    if (this._active()) {
      toast("Stop the current session before switching input.", "warn");
      return;
    }
    this.input = kind;
    this._selectSource();
    fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input_mode: kind }) }).catch(() => {});
  }

  _selectSource() {
    $$("#input-seg button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.input === this.input)));
    $$(".input-extra").forEach((d) => { d.hidden = d.dataset.for !== this.input; });
    $("#pad").style.cursor = this.input === "mouse" ? "crosshair" : "default";
    $("#preview").hidden = true;
    this.trail = [];
    this.beats = [];
    this.calibration = null;
    const args = { source: this.input };
    if (this.input === "webcam") args.camera = Number($("#camera-index").value);
    if (this.input === "recorded") args.fixture = $("#fixture-select").value;
    this.link.command("set_source", args);
    if (this.input === "webcam") this.link.command("set_preview", { enabled: $("#show-preview").checked });
    this._renderBanners();
  }

  async start() {
    if (this.input === "webxr" && !this.xr.session) {
      toast("VR input needs a headset: press \u201cEnter VR conducting\u201d first. On a laptop use Webcam or Mouse.", "warn", 6000);
      return;
    }
    await this.engine.ensure();
    if (this.engine.state !== "running") toast("Audio is not available; visual feedback still works.", "warn");
    this.trail = [];
    this.beats = [];
    this.tempoHistory = [];
    this.loopBeat = -1;
    this.feedback = null;
    this.calibration = null;
    this._clearMetrics();
    this.link.command("start");
    this._startReference();
  }

  show() {
    this.visible = true;
    if (this.link.state === "open" && !this._active()) this._selectSource();
    this._loop();
  }

  hide() {
    this.visible = false;
    cancelAnimationFrame(this._raf);
    clearInterval(this._refTimer);
    // Leaving the mode ends the session and releases the camera.
    if (this._active()) this.link.command("stop");
    this.link.command("set_source", { source: "none" });
  }

  _active() {
    return ["running", "calibrating", "paused"].includes(this.sessionState);
  }

  _clearMetrics() {
    for (const id of ["#m-bpm", "#m-dev", "#m-timing", "#m-sim", "#m-conf"]) $(id).textContent = DASH;
    $("#m-beats").textContent = "0";
    $("#m-duration").textContent = "0:00";
    $("#m-gaps").textContent = "0";
    $("#m-sim-bar").style.width = "0";
    $("#m-conf-bar").style.width = "0";
  }

  // ------------------------------------------------------------------ messages
  _onStatus(s) {
    this.status = s;
    if (s.session_state && s.session_state !== this.sessionState) {
      this.sessionState = s.session_state;
      this._renderControls();
    }
    this._renderBanners();
  }

  _onSamples(m) {
    const now = performance.now() / 1000;
    const n = m.points.length;
    // spread the batch over the last ~33 ms so the trail animates smoothly
    m.points.forEach((p, i) => this.trail.push([now - (n - 1 - i) / 60, p[1], p[2]]));
    while (this.trail.length && now - this.trail[0][0] > TRAIL_SECONDS) this.trail.shift();
  }

  _onBeat(b) {
    const now = performance.now() / 1000;
    const raw = this._fromNormalized(b.x, b.y);
    this.beats.push({ wall: now, x: raw[0], y: raw[1], n: b.beat_in_bar });
    while (this.beats.length > 16) this.beats.shift();
    this._flashDot(b.beat_in_bar);
    this.xr.onBeat();
    this._dynamics = b.amplitude;
    $("#dyn-label") && ($("#dyn-label").textContent = dynamicMark(b.amplitude));
    this._playBeat(b);
  }

  _onFeedback(f) {
    this.feedback = f;
    const now = performance.now() / 1000;
    this.tempoHistory.push([now, f.estimated_bpm, f.target_bpm]);
    while (this.tempoHistory.length && now - this.tempoHistory[0][0] > TEMPO_WINDOW_S) this.tempoHistory.shift();
    if (f.state !== this.sessionState) {
      this.sessionState = f.state;
      this._renderControls();
    }
    this._renderMetrics();
    this._renderBanners();
  }

  _fromNormalized(nx, ny) {
    const c = this.calibration;
    if (!c) return [0.5 + nx * 0.25, 0.5 + ny * 0.25];
    return [c.center[0] + nx * c.scale, c.center[1] + ny * c.scale];
  }

  // ------------------------------------------------------------------ audio
  _period() {
    const est = this.feedback && this.feedback.estimated_bpm;
    return 60 / (est || Number($("#target-bpm").value) || 90);
  }

  _playBeat(b) {
    const eng = this.engine;
    if (eng.state !== "running") return;
    const ctx = eng.ctx;
    const t = ctx.currentTime + 0.005;
    const a = this.settings.audio;
    if ($("#opt-click").checked) click(ctx, eng.directBus, t, b.beat_in_bar === 1, 0.35 * a.metronome_gain);
    if (!$("#opt-orchestra").checked) return;
    // Advance through the 16-beat chorale, re-aligning on recognised downbeats.
    if (b.beat_in_bar === 1) this.loopBeat = (Math.floor((this.loopBeat + 1) / 4) * 4) % LOOP_BEATS;
    else this.loopBeat = (this.loopBeat + 1) % LOOP_BEATS;
    const vel = Math.max(0.25, Math.min(1, 0.3 + 0.4 * b.amplitude));
    const dur = this._period() * 0.95;
    const out = this._orchestraBus || (this._orchestraBus = (() => {
      const g = ctx.createGain();
      g.connect(eng.directBus);
      return g;
    })());
    out.gain.value = a.orchestra_gain;
    for (const n of chordAt(this.loopBeat)) {
      const voice = n.part === "descant" ? "flute" : n.part === "tenor" ? "brass" : "bowed_string";
      const midi = n.midi + (n.part === "bass" ? -12 : n.part === "descant" ? 12 : 0);
      playNote(ctx, out, voice, "staccato", midi, t, dur, vel * n.vel * 0.8);
    }
    const mel = PARTS.melody.find((x) => x[0] === this.loopBeat);
    if (mel) playNote(ctx, out, "bowed_string", "arco", mel[2], t, dur * mel[1], vel * mel[3]);
  }

  _startReference() {
    clearInterval(this._refTimer);
    const eng = this.engine;
    if (eng.state !== "running") return;
    let next = eng.ctx.currentTime + 0.1;
    let count = 0;
    this._refTimer = setInterval(() => {
      const active = this.sessionState === "running" || this.sessionState === "calibrating";
      if (!["running", "calibrating", "paused"].includes(this.sessionState) && count > 0) {
        clearInterval(this._refTimer);
        return;
      }
      const period = 60 / (Number($("#target-bpm").value) || 90);
      const beats = (this.patterns.get($("#pattern-select").value) || { beats_per_bar: 4 }).beats_per_bar;
      while (next < eng.ctx.currentTime + 0.12) {
        // Scheduled on the audio clock: sample-accurate relative to itself.
        if (active && $("#opt-reference").checked) click(eng.ctx, eng.directBus, next, count % beats === 0, 0.22 * this.settings.audio.metronome_gain);
        next += period;
        count++;
      }
    }, 25);
  }

  // ------------------------------------------------------------------ rendering
  _renderBeatDots() {
    const p = this.patterns.get($("#pattern-select").value) || { beats_per_bar: 4 };
    const dots = $("#beat-dots");
    dots.replaceChildren();
    for (let i = 1; i <= p.beats_per_bar; i++) {
      const s = document.createElement("span");
      s.textContent = i;
      if (i === 1) s.className = "down";
      dots.append(s);
    }
    const dyn = document.createElement("span");
    dyn.id = "dyn-label";
    dyn.title = "Gesture size mapped to loudness";
    dyn.style.cssText = "width:auto;padding:0 10px;border-radius:15px;font-style:italic;font-family:Georgia,serif";
    dyn.textContent = DASH;
    dots.append(dyn);
  }

  _flashDot(n) {
    const spans = $$("#beat-dots span:not(#dyn-label)");
    const target = n ? spans[n - 1] : null;
    spans.forEach((s) => s.classList.remove("on"));
    if (target) {
      target.classList.add("on");
      clearTimeout(this._dotTimer);
      this._dotTimer = setTimeout(() => target.classList.remove("on"), 180);
    }
  }

  _renderControls() {
    const s = this.sessionState;
    const active = s === "running" || s === "calibrating";
    $("#btn-start").disabled = active || s === "paused";
    $("#btn-pause").disabled = !(active || s === "paused");
    $("#btn-pause").textContent = s === "paused" ? "Resume" : "Pause";
    $("#btn-stop").disabled = !(active || s === "paused");
    $("#btn-calibrate").disabled = !active;
  }

  _renderMetrics() {
    const f = this.feedback;
    if (!f) return;
    $("#m-bpm").textContent = fmt(f.estimated_bpm, 1);
    $("#m-target").textContent = fmt(f.target_bpm, 0);
    $("#m-dev").textContent = signed(f.tempo_deviation_pct, 1);
    $("#m-timing").textContent = fmt(f.beat_timing_error_ms, 0);
    $("#m-beats").textContent = String(f.beat_count);
    $("#m-duration").textContent = duration(f.session_duration_s);
    $("#m-gaps").textContent = String(f.invalid_intervals);
    const sim = f.similarity;
    $("#m-sim-bar").style.width = sim.estimate === null ? "0" : `${Math.round(sim.estimate * 100)}%`;
    $("#m-sim").textContent = sim.estimate === null
      ? (sim.status === "insufficient_data" ? "Needs one full bar of beats" : sim.status)
      : `${sim.estimate.toFixed(2)}  (DTW d = ${sim.normalized_distance.toFixed(3)})`;
    $("#m-conf-bar").style.width = `${Math.round(f.tracking_confidence * 100)}%`;
    $("#m-conf").textContent = `${(f.tracking_confidence * 100).toFixed(0)}% · ${f.tracking}`;
  }

  _renderBanners() {
    const out = [];
    const add = (kind, text) => out.push(`<div class="banner ${kind}">${text}</div>`);
    if (this.link.state !== "open") add("bad", "Analysis service disconnected. Reconnecting… (is <code>python -m archestral</code> running?)");
    const inp = this.status && this.status.input;
    if (inp && inp.test_input) add("warn", `<strong>Test input:</strong> ${escape(inp.label)}`);
    if (inp && inp.source === "webcam") {
      if (inp.state === "unavailable" || inp.state === "error") add("bad", `Camera unavailable: ${escape(inp.message)}`);
      else if (inp.state === "starting") add("info", "Opening camera…");
    }
    const f = this.feedback;
    const active = ["running", "calibrating"].includes(this.sessionState);
    if (active && inp && inp.state === "lost") add("warn", inp.source === "mouse" ? "No movement: press and drag in the pad." : "Tracking lost: keep your hand inside the camera view.");
    if (active && f && f.insufficient_movement) add("warn", "Movement too small. Use larger, clearer beat gestures.");
    else if (active && f && f.small_movement && inp && inp.source === "webcam") add("warn", "Your gestures fill only a small part of the camera view, so detection is less reliable. Move closer (about an arm\u2019s length) or conduct bigger, then press Recalibrate.");
    if (this.sessionState === "calibrating") add("info", "Calibration required: conduct steadily for a couple of seconds.");
    if (this.sessionState === "running" && f && f.estimated_bpm === null) add("info", "No reliable tempo yet: at least four evenly spaced beats are needed.");
    if (this.engine.state === "unavailable") add("bad", `Audio unavailable: ${escape(this.engine.error || "")}`);
    $("#cond-banners").innerHTML = out.join("");
  }

  _overlay() {
    const s = this.sessionState;
    const f = this.feedback;
    if (s === "idle" || s === "stopped") {
      const how = { webcam: "Raise one hand in front of the camera.", mouse: "Press and drag in this pad.",
        recorded: "Replays a synthetic test trajectory.", webxr: "Use the VR controller." }[this.input];
      return `<div class="big">Press Start to conduct</div><div class="sub">${how} Conduct 4/4: down, left, right, up, with a small bounce on every beat.</div>`;
    }
    if (s === "paused") return `<div class="big">Paused</div>`;
    if (s === "calibrating") {
      const p = f ? f.calibration_progress : 0;
      return `<div class="big">Calibrating…</div><div class="sub">Conduct a few beats so your movement range can be measured.</div><div class="progress"><div style="width:${Math.round(p * 100)}%"></div></div>`;
    }
    return "";
  }

  _loop() {
    if (!this.visible) return;
    this._raf = requestAnimationFrame(() => this._loop());
    this._drawPad();
    this._drawTempo();
    const html = this._overlay();
    if (html !== this._lastOverlay) {
      $("#pad-overlay").innerHTML = html;
      this._lastOverlay = html;
    }
  }

  _drawPad() {
    const { ctx, w, h } = setupCanvas($("#pad"));
    const S = Math.min(w, h);
    const X = (x) => w / 2 + (x - 0.5) * S;
    const Y = (y) => h / 2 - (y - 0.5) * S;
    ctx.clearRect(0, 0, w, h);
    // grid
    ctx.strokeStyle = "#1f242d";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 10; i++) {
      const v = i / 10;
      ctx.beginPath(); ctx.moveTo(X(v), Y(0)); ctx.lineTo(X(v), Y(1)); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(X(0), Y(v)); ctx.lineTo(X(1), Y(v)); ctx.stroke();
    }
    // reference pattern ghost
    const pat = this.patterns.get($("#pattern-select").value);
    if (pat) {
      const c = this.calibration;
      const cx = c ? c.center[0] : 0.5;
      const cy = c ? c.center[1] : 0.5;
      const sc = c ? c.scale : 0.22;
      ctx.strokeStyle = "rgba(216,162,74,0.35)";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 6]);
      ctx.beginPath();
      pat.points.forEach((p, i) => {
        const x = X(cx + p[1] * sc);
        const y = Y(cy + p[2] * sc);
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      });
      ctx.closePath();
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(216,162,74,0.7)";
      ctx.font = "600 12px ui-sans-serif, system-ui";
      for (const ic of pat.ictus) {
        const x = X(cx + ic.x * sc);
        const y = Y(cy + ic.y * sc);
        ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill();
        ctx.fillText(String(ic.beat), x + 6, y + 14);
      }
    }
    // live trail
    const now = performance.now() / 1000;
    const tr = this.trail;
    for (let i = 1; i < tr.length; i++) {
      const age = now - tr[i][0];
      const a = Math.max(0, 1 - age / TRAIL_SECONDS);
      ctx.strokeStyle = `rgba(92,200,194,${a})`;
      ctx.lineWidth = 1 + 3 * a;
      ctx.beginPath();
      ctx.moveTo(X(tr[i - 1][1]), Y(tr[i - 1][2]));
      ctx.lineTo(X(tr[i][1]), Y(tr[i][2]));
      ctx.stroke();
    }
    if (tr.length && now - tr[tr.length - 1][0] < 0.5) {
      const p = tr[tr.length - 1];
      ctx.fillStyle = "#e7e9ee";
      ctx.beginPath(); ctx.arc(X(p[1]), Y(p[2]), 6, 0, Math.PI * 2); ctx.fill();
    }
    // beats
    for (const b of this.beats) {
      const age = now - b.wall;
      if (age > BEAT_FADE_S) continue;
      const a = 1 - age / BEAT_FADE_S;
      const r = 10 + 18 * (1 - a);
      ctx.strokeStyle = b.n === 1 ? `rgba(216,162,74,${a})` : `rgba(92,200,194,${a})`;
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(X(b.x), Y(b.y), r, 0, Math.PI * 2); ctx.stroke();
      if (b.n) {
        ctx.fillStyle = `rgba(231,233,238,${a})`;
        ctx.font = "700 13px ui-sans-serif, system-ui";
        ctx.textAlign = "center";
        ctx.fillText(String(b.n), X(b.x), Y(b.y) + 4);
        ctx.textAlign = "start";
      }
    }
  }

  _drawTempo() {
    const { ctx, w, h } = setupCanvas($("#tempo-chart"));
    ctx.clearRect(0, 0, w, h);
    const hist = this.tempoHistory;
    const now = performance.now() / 1000;
    const target = Number($("#target-bpm").value) || 90;
    const vals = hist.map((p) => p[1]).filter((v) => v !== null);
    const lo = Math.floor((Math.min(target, ...vals) - 15) / 10) * 10;
    const hi = Math.ceil((Math.max(target, ...vals) + 15) / 10) * 10;
    const padL = 34;
    const X = (t) => padL + (1 - (now - t) / TEMPO_WINDOW_S) * (w - padL - 6);
    const Y = (v) => 6 + (1 - (v - lo) / (hi - lo)) * (h - 22);
    ctx.font = "11px ui-sans-serif, system-ui";
    ctx.fillStyle = "#7c8496";
    ctx.strokeStyle = "#1f242d";
    for (let v = lo; v <= hi; v += (hi - lo) > 80 ? 20 : 10) {
      ctx.beginPath(); ctx.moveTo(padL, Y(v)); ctx.lineTo(w, Y(v)); ctx.stroke();
      ctx.fillText(String(v), 4, Y(v) + 4);
    }
    ctx.fillText(`last ${TEMPO_WINDOW_S}s`, w - 60, h - 2);
    ctx.strokeStyle = "#d8a24a";
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(padL, Y(target)); ctx.lineTo(w, Y(target)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = "#5cc8c2";
    ctx.lineWidth = 2;
    ctx.beginPath();
    let pen = false;
    for (const [t, v] of hist) {
      if (v === null) { pen = false; continue; }      // gaps stay gaps; nothing is interpolated
      if (pen) ctx.lineTo(X(t), Y(v)); else ctx.moveTo(X(t), Y(v));
      pen = true;
    }
    ctx.stroke();
    ctx.lineWidth = 1;
    if (!vals.length) {
      ctx.fillStyle = "#7c8496";
      ctx.fillText("Tempo unavailable until enough beats are detected", padL + 10, h / 2);
    }
  }
}

function dynamicMark(amp) {
  if (!Number.isFinite(amp)) return DASH;
  if (amp < 0.5) return "p";
  if (amp < 0.9) return "mp";
  if (amp < 1.3) return "mf";
  return "f";
}

const escape = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
