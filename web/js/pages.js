// Settings, Diagnostics, Results and Main-menu status pages.
import { api } from "./api.js";
import { duration, escapeHtml, fmt, signed } from "./core/format.js";
import { $, el, eventLog, kv, setupCanvas, toast } from "./ui.js";

// ---------------------------------------------------------------- settings
const ANALYSIS_FIELDS = [
  ["min_confidence", "Min. tracking confidence", 0, 1, 0.05],
  ["smoothing_min_cutoff_hz", "Smoothing min cutoff (Hz)", 0.1, 30, 0.1],
  ["smoothing_beta", "Smoothing speed coefficient (beta)", 0, 10, 0.05],
  ["calibration_s", "Calibration duration (s)", 0.5, 10, 0.5],
  ["min_approach_speed", "Beat: min stroke speed", 0.05, 20, 0.05],
  ["dip_ratio", "Beat: deceleration ratio", 0.05, 0.95, 0.05],
  ["min_bpm", "Min plausible BPM", 20, 120, 1],
  ["max_bpm", "Max plausible BPM", 60, 300, 1],
  ["tempo_window", "Tempo rolling window (beats)", 2, 64, 1],
  ["similarity_scale", "Similarity scale (DTW d)", 0.01, 10, 0.01],
];

export function renderSettings(settings, defaults, onSaved) {
  const grid = $("#settings-grid");
  const a = settings.analysis || {};
  const num = (id, label, value, min, max, step) => [
    el("label", { class: "field-label", for: id }, label),
    el("input", { type: "number", id, value: String(value), min: String(min), max: String(max), step: String(step) }),
  ];
  const sel = (id, label, value, opts) => [
    el("label", { class: "field-label", for: id }, label),
    (() => { const s = el("select", { id }, ...opts.map(([v, t]) => new Option(t, v))); s.value = String(value); return s; })(),
  ];
  const chk = (id, label, value) => el("label", { class: "check" }, el("input", { type: "checkbox", id, checked: value }), label);
  grid.replaceChildren(
    el("div", { class: "panel" }, el("h3", {}, "Input"),
      ...sel("s-input", "Default conducting input", settings.input_mode, [["webcam", "Webcam"], ["mouse", "Mouse / trackpad"], ["recorded", "Recorded test data"], ["webxr", "WebXR controller"]]),
      ...sel("s-camera", "Camera", settings.camera_index, [0, 1, 2, 3].map((i) => [String(i), `Camera ${i}`])),
      ...sel("s-landmark", "Tracked hand point", settings.tracked_landmark, [["wrist", "Wrist"], ["index_tip", "Index fingertip"]]),
      chk("s-mirror", "Mirror camera image (selfie view)", settings.mirror_camera),
      chk("s-preview", "Show camera preview by default", settings.ui.show_preview),
      ...num("s-bpm", "Default target tempo (BPM)", settings.target_bpm, 20, 300, 1)),
    el("div", { class: "panel" }, el("h3", {}, "Analysis"),
      ...ANALYSIS_FIELDS.flatMap(([k, label, min, max, step]) => num(`a-${k}`, label, a[k] ?? defaults[k], min, max, step)),
      el("p", { class: "hint" }, "Changes apply to the next session.")),
    el("div", { class: "panel" }, el("h3", {}, "Audio"),
      ...num("s-master", "Master gain", settings.audio.master_gain, 0, 2, 0.05),
      ...num("s-metro", "Metronome gain", settings.audio.metronome_gain, 0, 2, 0.05),
      ...num("s-orch", "Orchestra response gain", settings.audio.orchestra_gain, 0, 2, 0.05),
      chk("s-ref", "Reference metronome on by default", settings.audio.reference_metronome),
      el("p", { class: "hint" }, `Data folder: ${settings.__dataDir || "data/"}`)),
  );

  $("#settings-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const analysis = {};
    for (const [k] of ANALYSIS_FIELDS) {
      const v = Number($(`#a-${k}`).value);
      if (Number.isFinite(v) && v !== defaults[k]) analysis[k] = Number.isInteger(defaults[k]) ? Math.round(v) : v;
    }
    const patch = {
      input_mode: $("#s-input").value,
      camera_index: Number($("#s-camera").value),
      tracked_landmark: $("#s-landmark").value,
      mirror_camera: $("#s-mirror").checked,
      target_bpm: Number($("#s-bpm").value),
      analysis,
      audio: { master_gain: Number($("#s-master").value), metronome_gain: Number($("#s-metro").value),
        orchestra_gain: Number($("#s-orch").value), reference_metronome: $("#s-ref").checked },
      ui: { show_preview: $("#s-preview").checked },
    };
    try {
      const res = await api.saveSettings(patch);
      showProblems(res.problems);
      toast(res.problems.length ? "Saved; some values were invalid and kept their defaults." : "Settings saved.", res.problems.length ? "warn" : "ok");
      onSaved(res.settings);
    } catch (e) {
      toast(e.message, "bad");
    }
  };
  $("#set-defaults").onclick = async () => {
    const res = await api.saveSettings({ analysis: {}, target_bpm: 90, camera_index: 0, mirror_camera: true,
      tracked_landmark: "wrist", audio: { master_gain: 0.8, metronome_gain: 0.6, orchestra_gain: 0.7, reference_metronome: false } });
    // analysis overrides are replaced, not merged, when an empty object is sent
    onSaved(res.settings);
    renderSettings(res.settings, defaults, onSaved);
    toast("Defaults restored.", "ok");
  };
}

export function showProblems(problems) {
  $("#settings-problems").innerHTML = (problems || []).map((p) => `<div class="banner warn">${escapeHtml(p)}</div>`).join("");
}

// ---------------------------------------------------------------- diagnostics
export function renderDiagnostics({ link, engine, caps, conductor, xrSupport }) {
  const age = link.lastMessageAt ? ((performance.now() - link.lastMessageAt) / 1000).toFixed(1) : null;
  kv($("#dg-service"), [
    ["WebSocket", link.state],
    ["Service version", link.serverInfo ? link.serverInfo.version : "—"],
    ["Protocol", link.serverInfo ? `v${link.serverInfo.protocol_version}` : "—"],
    ["Last message", age ? `${age} s ago` : "—"],
    ["Invalid messages", String(link.invalidCount)],
    ["Vision (MediaPipe)", caps ? `${caps.vision.available ? "available" : "unavailable"} – ${caps.vision.message}` : "—"],
  ]);
  const st = conductor.status;
  const f = conductor.feedback;
  kv($("#dg-input"), [
    ["Input source", st ? st.input.label : "—"],
    ["Tracking", st ? `${st.input.state}${st.input.message ? ` – ${st.input.message}` : ""}` : "—"],
    ["Test input", st ? (st.input.test_input ? "yes (synthetic)" : "no") : "—"],
    ["Camera FPS", st && st.input.fps !== undefined ? String(st.input.fps) : "—"],
    ["Last sample", st && st.last_sample_age_s !== null ? `${st.last_sample_age_s} s ago` : "—"],
    ["Analysis state", conductor.sessionState],
    ["Rejected samples", f ? String(f.rejected_samples) : "—"],
    ["Service error", st && st.last_error ? st.last_error : "none"],
  ]);
  kv($("#dg-audio"), [
    ["Audio engine", engine.state + (engine.error ? ` – ${engine.error}` : "")],
    ["Sample rate", engine.ctx ? `${engine.ctx.sampleRate} Hz` : "—"],
    ["Base latency", engine.ctx && engine.ctx.baseLatency ? `${(engine.ctx.baseLatency * 1000).toFixed(1)} ms` : "—"],
    ["WebXR", xrSupport ? xrSupport.message : "checking…"],
    ["Secure context", String(window.isSecureContext)],
  ]);
  $("#dg-log").innerHTML = eventLog.slice(-80).reverse()
    .map((e) => `<li class="${e.level}">${e.time.toLocaleTimeString()} — ${escapeHtml(e.message)}</li>`).join("");
}

// ---------------------------------------------------------------- results
export function renderResults(s, tempoHistory) {
  const body = $("#results-body");
  const card = (label, value, note = "") => el("div", { class: "panel" },
    el("div", { class: "l" }, label), el("div", { class: "v" }, value), note ? el("div", { class: "hint" }, note) : null);
  const sim = s.similarity_mean;
  const positions = Object.entries(s.beats_per_position || {}).map(([k, v]) => `${k}: ${v}`).join("  ·  ");
  const canvas = el("canvas", { id: "results-chart" });
  body.replaceChildren(
    el("div", { class: "results-cards" },
      card("Estimated tempo", `${fmt(s.estimated_bpm, 1)} BPM`, `target ${fmt(s.target_bpm, 0)} BPM`),
      card("Tempo deviation", `${signed(s.tempo_deviation_pct, 1)} %`, "(estimated − target) / target"),
      card("Beat timing error", `${fmt(s.beat_timing_error_ms, 0)} ms`, "mean |offset| from target grid"),
      card("Gesture similarity", sim === null ? "—" : sim.toFixed(2), `prototype estimate over ${s.similarity_bars} bar(s); not a grade`),
      card("Beats detected", String(s.beat_count), positions ? `per position: ${positions}` : ""),
      card("Session time", duration(s.session_duration_s)),
      card("Tracking gaps", String(s.invalid_intervals), `${fmt(s.invalid_time_s, 1)} s without valid tracking`),
      card("Mean tracking confidence", s.mean_tracking_confidence === null ? "—" : `${Math.round(s.mean_tracking_confidence * 100)} %`,
        `rejected samples: ${s.rejected_samples}`)),
    el("div", { class: "panel" }, el("h3", {}, "Tempo during session"), canvas),
    el("div", { class: "panel" }, el("h3", {}, "How to read this"),
      el("p", { class: "hint" }, "Tempo is the median of recent beat intervals (BPM = 60 / T). Timing error compares each beat with an even grid at the target tempo. Gesture similarity is a length-normalized DTW distance between your last bar and the schematic reference pattern, mapped to 0–1 with an uncalibrated constant. None of these alone measures conducting quality.")),
  );
  requestAnimationFrame(() => drawHistory(canvas, s.tempo_history || [], s.target_bpm));
}

function drawHistory(canvas, hist, target) {
  const { ctx, w, h } = setupCanvas(canvas);
  if (!hist.length) {
    ctx.fillStyle = "#7c8496";
    ctx.font = "13px ui-sans-serif, system-ui";
    ctx.fillText("No reliable tempo estimate was produced in this session.", 12, h / 2);
    return;
  }
  const t0 = hist[0][0];
  const t1 = hist[hist.length - 1][0] || t0 + 1;
  const vals = hist.map((p) => p[1]);
  const lo = Math.floor((Math.min(target, ...vals) - 10) / 10) * 10;
  const hi = Math.ceil((Math.max(target, ...vals) + 10) / 10) * 10;
  const X = (t) => 40 + ((t - t0) / Math.max(1e-6, t1 - t0)) * (w - 50);
  const Y = (v) => 8 + (1 - (v - lo) / (hi - lo)) * (h - 28);
  ctx.font = "11px ui-sans-serif, system-ui";
  ctx.fillStyle = "#7c8496";
  ctx.strokeStyle = "#1f242d";
  for (let v = lo; v <= hi; v += 10) {
    ctx.beginPath(); ctx.moveTo(40, Y(v)); ctx.lineTo(w, Y(v)); ctx.stroke();
    ctx.fillText(String(v), 6, Y(v) + 4);
  }
  ctx.fillText("time (s)", w - 50, h - 4);
  ctx.strokeStyle = "#d8a24a";
  ctx.setLineDash([5, 4]);
  ctx.beginPath(); ctx.moveTo(40, Y(target)); ctx.lineTo(w, Y(target)); ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle = "#5cc8c2";
  ctx.lineWidth = 2;
  ctx.beginPath();
  hist.forEach(([t, v], i) => (i ? ctx.lineTo(X(t), Y(v)) : ctx.moveTo(X(t), Y(v))));
  ctx.stroke();
}

// ---------------------------------------------------------------- menu status
export function renderMenuStatus({ link, engine, caps, xrSupport }) {
  kv($("#menu-status"), [
    ["Analysis service", link.state === "open" ? "connected" : "not connected"],
    ["Webcam tracking", caps ? (caps.vision.available ? "MediaPipe + OpenCV ready (camera permission is checked when you start)" : caps.vision.message) : "—"],
    ["Mouse conducting", "always available"],
    ["Audio", engine.state === "not-started" ? "starts on your first click (browser policy)" : engine.state],
    ["VR / WebXR", xrSupport ? xrSupport.message : "checking…"],
  ]);
}
