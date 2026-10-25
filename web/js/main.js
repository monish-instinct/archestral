// App bootstrap: load configuration, connect to the service, detect
// capabilities, route between screens and keep the status chips current.
import { api } from "./api.js";
import { AudioEngine } from "./audio/engine.js";
import { ComposerMode } from "./composer/composer.js";
import { ConductorMode } from "./conductor/conductor.js";
import { ServiceLink } from "./net.js";
import { renderDiagnostics, renderMenuStatus, renderResults, renderSettings, showProblems } from "./pages.js";
import { $, $$, el, logEvent, modal, setChip, toast } from "./ui.js";

const ROUTES = ["menu", "conductor", "composer", "settings", "diagnostics", "results"];

async function boot() {
  logEvent("Starting Archestral client");
  const engine = new AudioEngine();
  const link = new ServiceLink(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);

  let caps, settingsRes, patterns, fixtures, library;
  try {
    [caps, settingsRes, patterns, fixtures, library] = await Promise.all([
      api.capabilities(), api.settings(), api.patterns(), api.fixtures(), api.library(),
    ]);
  } catch (e) {
    document.querySelector("main").replaceChildren(el("div", { class: "menu" },
      el("div", { class: "banner bad" }, `Startup failed: ${e.message}`),
      el("p", { class: "hint" }, "Start the service with `python -m archestral` and reload this page.")));
    return;
  }
  const settings = settingsRes.settings;
  settings.__dataDir = caps.data_dir;
  if (settingsRes.problems.length) {
    toast("Some saved settings were invalid and were reset. See Settings.", "warn", 6000);
    showProblems(settingsRes.problems);
  }
  if (!caps.vision.available) logEvent(`Vision unavailable: ${caps.vision.message}`, "warn");

  const app = { link, engine, caps, settings, xrSupport: null };
  app.conductor = new ConductorMode({
    link, engine, settings, patterns: patterns.patterns, fixtures: fixtures.fixtures,
    onSummary: (summary, hist) => {
      renderResults(summary, hist);
      if (location.hash.startsWith("#/conductor")) location.hash = "#/results";
      else toast("Conducting session ended. Results are on the Results page.", "info");
    },
  });
  app.composer = new ComposerMode({ engine, library, settings });
  app.conductor.xr.checkSupport().then((s) => { app.xrSupport = s; });

  renderSettings(settings, caps.analysis_defaults, (s) => {
    Object.assign(settings, s);
    app.conductor.settings = settings;
  });

  // ---- status chips
  const refreshChips = () => {
    setChip("chip-service", link.state === "open" ? "ok" : link.state === "connecting" ? "warn" : "bad",
      `Analysis service: ${link.state}`);
    const st = app.conductor.status;
    const inState = st && st.input.state;
    setChip("chip-input", !st || !st.input.source ? null
      : inState === "tracking" ? "ok" : inState === "unavailable" || inState === "error" ? "bad" : "warn",
    st ? `${st.input.label}: ${inState}` : "No input selected");
    setChip("chip-audio", engine.state === "running" ? "ok" : engine.state === "unavailable" ? "bad" : "warn",
      `Audio: ${engine.state}`);
  };
  link.addEventListener("connection", refreshChips);
  link.addEventListener("status", refreshChips);
  engine.addEventListener("state", refreshChips);
  refreshChips();

  // Browsers only allow audio after a user gesture: start it on the first click anywhere.
  window.addEventListener("pointerdown", () => engine.ensure(), { once: true });

  // ---- router
  let current = null;
  const go = async () => {
    const name = (location.hash.replace(/^#\//, "") || "menu").split("?")[0];
    const route = ROUTES.includes(name) ? name : "menu";
    if (route === current) return;
    if (current === "conductor") app.conductor.hide();
    if (current === "composer") app.composer.hide();
    current = route;
    $$(".screen").forEach((s) => { s.hidden = s.dataset.screen !== route; });
    $$(".tabs a").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
    if (route === "conductor") app.conductor.show();
    if (route === "composer") {
      try {
        await app.composer.show();
      } catch (e) {
        toast(`3D stage failed to start: ${e.message}`, "bad", 8000);
        logEvent(`Composer init error: ${e.stack || e}`, "bad");
      }
    }
  };
  window.addEventListener("hashchange", go);
  await go();

  setInterval(() => {
    if (current === "diagnostics") renderDiagnostics(app);
    if (current === "menu") renderMenuStatus(app);
    refreshChips();
  }, 500);
  renderMenuStatus(app);

  window.addEventListener("error", (e) => logEvent(`Error: ${e.message}`, "bad"));
  window.addEventListener("unhandledrejection", (e) => logEvent(`Error: ${e.reason && e.reason.message}`, "bad"));

  if (!settings.ui.first_run_done) firstRun(app);
}

async function firstRun(app) {
  const visionLine = app.caps.vision.available
    ? "Webcam tracking is ready. macOS will ask for camera permission the first time you start a webcam session."
    : `Webcam tracking is unavailable on this machine (${app.caps.vision.message}). Mouse input works everywhere.`;
  const body = el("div", {},
    el("p", {}, "Archestral runs entirely on this computer. Camera frames are processed locally and never uploaded."),
    el("ul", { class: "hint" },
      el("li", {}, visionLine),
      el("li", {}, "No camera? Use Mouse input and draw the conducting pattern in the pad."),
      el("li", {}, "Test data replays synthetic trajectories and is always labelled as test input."),
      el("li", {}, "Use headphones in Composer mode to hear the spatial (HRTF) audio.")));
  await modal({ title: "Welcome to Archestral", body, okLabel: "Get started", cancelLabel: null });
  try {
    await api.saveSettings({ ui: { first_run_done: true } });
  } catch { /* non-fatal */ }
}

boot();
