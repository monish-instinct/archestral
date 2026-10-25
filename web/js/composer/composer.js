// Composer mode: 3D placement, per-instrument mixing, spatial playback,
// arrangement persistence and A/B comparison.
import * as THREE from "three";
import { api } from "../api.js";
import { compareArrangements } from "../core/compare.js";
import { escapeHtml, fmt } from "../core/format.js";
import { anySolo, azimuth, distance3, effectiveGain, gainToDb, inverseDistanceGain } from "../core/mixer.js";
import { checkPlacement, findFreeSpot, newId, snap } from "../core/stage.js";
import { LOOP_BEATS, notesAt, PARTS } from "../audio/score.js";
import { playNote } from "../audio/voices.js";
import { $, confirmAction, el, kv, logEvent, modal, promptText, toast } from "../ui.js";
import { buildInstrumentView, setRing, Stage } from "./stage.js";

const SOURCE_HEIGHT = 1.1;

export class ComposerMode {
  constructor({ engine, library, settings }) {
    this.engine = engine;
    this.lib = library;
    this.defs = new Map(library.instruments.map((d) => [d.id, d]));
    this.settings = settings;
    this.arr = null;
    this.dirty = false;
    this.views = new Map();      // uid -> THREE.Group
    this.channels = new Map();   // uid -> spatial channel
    this.selected = null;
    this.playing = false;
    this.visible = false;
    this.stage = null;
    this.ab = null;
  }

  // ------------------------------------------------------------------ lifecycle
  async show() {
    this.visible = true;
    if (!this.stage) await this._init();
    this.stage.resize();
    this._loop();
  }

  hide() {
    this.visible = false;
    cancelAnimationFrame(this._raf);
    if (this.playing) this.stop();
  }

  async _init() {
    this.stage = new Stage($("#stage-host"), this.lib.stage);
    this._bindUi();
    this._bindPointer();
    window.addEventListener("keydown", (e) => this._onKey(e));
    await this._refreshList();
    if (!this.listCache.some((a) => a.valid)) await this._seedExamples();
    const first = this.listCache.find((a) => a.id === "standard-seating" && a.valid) || this.listCache.find((a) => a.valid);
    if (first) await this.load(first.id);
    else this._apply(this._blank("Untitled arrangement"), true);
  }

  // ------------------------------------------------------------------ model helpers
  _blank(name) {
    return {
      schema_version: 1, id: newId(name), name,
      audio: { master_gain: 0.8, reverb_mix: 0.25, tempo_bpm: 72, panning_model: "HRTF" },
      listener: { preset: "podium" },
      instruments: [],
    };
  }

  _instance(def, position, extra = {}) {
    return {
      uid: `${def.id}-${Date.now().toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`,
      instrument_id: def.id,
      position: [position[0], 0, position[2]],
      rotation_y_deg: def.default_rotation_y_deg,
      scale: def.default_scale,
      gain: def.default_gain,
      muted: false, solo: false,
      articulation: def.default_articulation,
      ...extra,
    };
  }

  async _seedExamples() {
    // Two starter arrangements so the A/B workflow can be tried immediately.
    const standard = this._blank("Standard seating");
    standard.id = "standard-seating";
    for (const d of this.lib.instruments) standard.instruments.push(this._instance(d, d.default_position));
    const alt = JSON.parse(JSON.stringify(standard));
    alt.id = "antiphonal-seating";
    alt.name = "Antiphonal seating";
    alt.listener.preset = "audience";
    for (const it of alt.instruments) {
      if (it.instrument_id === "violin") it.position = [3.0, 0, 0.8];
      if (it.instrument_id === "cello") { it.position = [-2.8, 0, 0.8]; it.articulation = "pizzicato"; }
      if (it.instrument_id === "horn") it.rotation_y_deg = 180;        // bell turned away from the listener
      if (it.instrument_id === "flute") it.gain = 0.45;
    }
    try {
      await api.saveArrangement(standard.id, standard);
      await api.saveArrangement(alt.id, alt);
      logEvent("Created example arrangements");
    } catch (e) {
      toast(`Could not create example arrangements: ${e.message}`, "bad");
    }
    await this._refreshList();
  }

  _def(inst) { return this.defs.get(inst.instrument_id); }
  _inst(uid) { return this.arr.instruments.find((i) => i.uid === uid); }
  _markDirty() { this.dirty = true; $("#arr-dirty").hidden = false; }

  // ------------------------------------------------------------------ apply arrangement to scene/audio
  _apply(doc, dirty = false) {
    for (const v of this.views.values()) this.stage.scene.remove(v);
    for (const c of this.channels.values()) c.dispose();
    this.views.clear();
    this.channels.clear();
    const unknown = doc.instruments.filter((i) => !this.defs.has(i.instrument_id));
    if (unknown.length) toast(`Skipped ${unknown.length} unknown instrument(s).`, "warn");
    doc.instruments = doc.instruments.filter((i) => this.defs.has(i.instrument_id));
    this.arr = doc;
    for (const inst of doc.instruments) this._addView(inst);
    this.selected = null;
    this.dirty = dirty;
    $("#arr-dirty").hidden = !dirty;
    $("#arr-name").textContent = doc.name;
    $("#tr-tempo").value = doc.audio.tempo_bpm;
    $("#tr-reverb").value = doc.audio.reverb_mix;
    $("#tr-master").value = doc.audio.master_gain;
    $("#tr-listener").value = doc.listener.preset;
    $("#tr-hrtf").checked = doc.audio.panning_model === "HRTF";
    this._applyAudioGlobals();
    this._renderInspector();
    this._renderAB();
  }

  _addView(inst) {
    const view = buildInstrumentView(this._def(inst), inst.uid);
    this.stage.scene.add(view);
    this.views.set(inst.uid, view);
    this._syncView(inst);
    if (this.engine.ctx) this._ensureChannel(inst);
  }

  _syncView(inst) {
    const v = this.views.get(inst.uid);
    v.position.set(inst.position[0], 0, inst.position[2]);
    v.rotation.y = THREE.MathUtils.degToRad(inst.rotation_y_deg);
    v.userData.parts.model.scale.setScalar(inst.scale);
    const silent = effectiveGain(inst, anySolo(this.arr.instruments)) === 0;
    v.userData.parts.model.traverse((o) => { if (o.isMesh) { o.material.transparent = silent; o.material.opacity = silent ? 0.35 : 1; } });
    setRing(v, this.selected === inst.uid ? "selected" : "none");
    this._syncChannel(inst);
  }

  _ensureChannel(inst) {
    if (!this.engine.ctx || this.channels.has(inst.uid)) return;
    const ch = this.engine.createSpatialChannel(this._def(inst).spatial, this.arr.audio.panning_model);
    this.channels.set(inst.uid, ch);
    this._syncChannel(inst);
  }

  _syncChannel(inst) {
    const ch = this.channels.get(inst.uid);
    if (!ch) return;
    const t = this.engine.ctx.currentTime;
    const p = ch.panner;
    const y = SOURCE_HEIGHT * inst.scale;
    const th = THREE.MathUtils.degToRad(inst.rotation_y_deg);
    if (p.positionX) {
      p.positionX.setTargetAtTime(inst.position[0], t, 0.02);
      p.positionY.setTargetAtTime(y, t, 0.02);
      p.positionZ.setTargetAtTime(inst.position[2], t, 0.02);
      p.orientationX.value = Math.sin(th);
      p.orientationY.value = 0;
      p.orientationZ.value = Math.cos(th);
    } else {
      p.setPosition(inst.position[0], y, inst.position[2]);
      p.setOrientation(Math.sin(th), 0, Math.cos(th));
    }
    p.panningModel = this.arr.audio.panning_model;
    ch.volume.gain.setTargetAtTime(effectiveGain(inst, anySolo(this.arr.instruments)), t, 0.02);
  }

  _syncAll() { for (const inst of this.arr.instruments) this._syncView(inst); }

  _applyAudioGlobals() {
    if (!this.engine.ctx) return;
    this.engine.setMaster(this.arr.audio.master_gain);
    this.engine.setReverb(this.arr.audio.reverb_mix);
    this._updateListener(true);
  }

  _listenerPose() {
    const preset = this.arr.listener.preset;
    if (preset === "camera") {
      const cam = this.stage.camera;
      const f = new THREE.Vector3();
      cam.getWorldDirection(f);
      return { pos: cam.position.toArray(), forward: f.toArray() };
    }
    const base = preset === "audience" ? this.lib.stage.audience : this.lib.stage.podium;
    return { pos: [base[0], preset === "audience" ? base[1] : 1.6, base[2]], forward: [0, 0, -1] };
  }

  _updateListener(force = false) {
    const pose = this._listenerPose();
    const m = this.stage.listenerMarker;
    m.visible = this.arr.listener.preset !== "camera";
    m.position.set(pose.pos[0], pose.pos[1] - 0.1, pose.pos[2]);
    if (!this.engine.ctx) return;
    const key = pose.pos.map((v) => v.toFixed(2)).join() + pose.forward.map((v) => v.toFixed(2)).join();
    if (force || key !== this._listenerKey) {
      this._listenerKey = key;
      this.engine.setListener(pose.pos, pose.forward);
    }
  }

  // ------------------------------------------------------------------ playback
  async play() {
    const ctx = await this.engine.ensure();
    if (!ctx || this.engine.state !== "running") {
      toast("Audio could not start in this browser.", "bad");
      return;
    }
    for (const inst of this.arr.instruments) this._ensureChannel(inst);
    this._applyAudioGlobals();
    this.playing = true;
    $("#tr-play").textContent = "Stop";
    let beat = 0;
    let next = ctx.currentTime + 0.1;
    this._seqTimer = setInterval(() => {
      const spb = 60 / this.arr.audio.tempo_bpm;
      while (next < ctx.currentTime + 0.15) {
        this._scheduleBeat(beat % LOOP_BEATS, next, spb);
        next += spb;
        beat++;
      }
    }, 25);
  }

  stop() {
    clearInterval(this._seqTimer);
    this.playing = false;
    $("#tr-play").textContent = "Play";
  }

  _scheduleBeat(beat, time, spb) {
    const ctx = this.engine.ctx;
    for (const inst of this.arr.instruments) {
      const def = this._def(inst);
      const ch = this.channels.get(inst.uid);
      if (!ch) continue;
      for (const [, dur, midi, vel] of notesAt(def.audio.part, beat)) {
        playNote(ctx, ch.input, def.audio.voice, inst.articulation, midi + 12 * def.audio.octave, time, dur * spb * 0.98, vel);
      }
    }
  }

  async previewNote(inst) {
    const ctx = await this.engine.ensure();
    if (!ctx) return;
    this._ensureChannel(inst);
    this._applyAudioGlobals();
    const def = this._def(inst);
    const n = PARTS[def.audio.part][0];
    playNote(ctx, this.channels.get(inst.uid).input, def.audio.voice, inst.articulation, n[2] + 12 * def.audio.octave,
      ctx.currentTime + 0.02, 0.9, 0.85);
  }

  // ------------------------------------------------------------------ UI bindings
  _bindUi() {
    const lib = $("#lib-list");
    lib.replaceChildren(...this.lib.instruments.map((d) => el("button", {
      class: "lib-item", type: "button", title: `Add a ${d.name}`,
      onclick: () => this.addInstrument(d.id),
    }, el("span", { class: "swatch", style: `background:${d.color}` }), d.name, el("span", { class: "fam" }, d.family))));

    $("#tr-play").addEventListener("click", () => (this.playing ? this.stop() : this.play()));
    $("#tr-tempo").addEventListener("change", (e) => {
      const v = Math.max(30, Math.min(200, Number(e.target.value) || 72));
      e.target.value = v;
      this.arr.audio.tempo_bpm = v;
      this._markDirty();
    });
    $("#tr-reverb").addEventListener("input", (e) => { this.arr.audio.reverb_mix = Number(e.target.value); this._applyAudioGlobals(); this._markDirty(); });
    $("#tr-master").addEventListener("input", (e) => { this.arr.audio.master_gain = Number(e.target.value); this._applyAudioGlobals(); this._markDirty(); });
    $("#tr-listener").addEventListener("change", (e) => { this.arr.listener.preset = e.target.value; this._updateListener(true); this._markDirty(); });
    $("#tr-hrtf").addEventListener("change", (e) => { this.arr.audio.panning_model = e.target.checked ? "HRTF" : "equalpower"; this._syncAll(); this._markDirty(); });
    $("#tr-diag").addEventListener("click", (e) => {
      const show = $("#audio-diag").hidden;
      $("#audio-diag").hidden = !show;
      e.target.setAttribute("aria-pressed", String(show));
    });

    // inspector
    $("#insp-gain").addEventListener("input", (e) => this._edit((i) => { i.gain = Number(e.target.value); }));
    $("#insp-rot").addEventListener("input", (e) => this._edit((i) => { i.rotation_y_deg = Number(e.target.value); }));
    $("#insp-scale").addEventListener("input", (e) => this._edit((i) => { i.scale = Number(e.target.value); }));
    $("#insp-mute").addEventListener("click", () => this._edit((i) => { i.muted = !i.muted; }, true));
    $("#insp-solo").addEventListener("click", () => this._edit((i) => { i.solo = !i.solo; }, true));
    $("#insp-preview").addEventListener("click", () => { const i = this._inst(this.selected); if (i) this.previewNote(i); });
    $("#insp-reset").addEventListener("click", () => this.resetSelected());
    $("#insp-delete").addEventListener("click", () => this.removeSelected());

    // arrangements
    $("#arr-save").addEventListener("click", () => this.save());
    $("#arr-new").addEventListener("click", () => this.newArrangement());
    $("#arr-rename").addEventListener("click", () => this.rename());
    $("#arr-dup").addEventListener("click", () => this.duplicate());
    $("#arr-delete").addEventListener("click", () => this.deleteCurrent());
    $("#arr-load").addEventListener("click", () => this._loadSelected());
    $("#arr-list").addEventListener("dblclick", () => this._loadSelected());
    $("#arr-compare").addEventListener("click", () => this.compare());
  }

  _edit(fn, syncAll = false) {
    const inst = this._inst(this.selected);
    if (!inst) return;
    fn(inst);
    if (syncAll) this._syncAll(); else this._syncView(inst);
    this._markDirty();
    this._renderInspector();
  }

  _bindPointer() {
    const dom = this.stage.renderer.domElement;
    const objects = () => [...this.views.values()];
    let drag = null;
    dom.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      const { hitUid, point } = this.stage.pick(ev, objects());
      this._downAt = [ev.clientX, ev.clientY];
      if (!hitUid) return;
      this.select(hitUid);
      const inst = this._inst(hitUid);
      this.stage.controls.enabled = false;
      dom.setPointerCapture(ev.pointerId);
      drag = { uid: hitUid, offset: point ? [point.x - inst.position[0], point.z - inst.position[2]] : [0, 0],
        start: inst.position.slice(), lastValid: inst.position.slice(), invalid: null };
    });
    dom.addEventListener("pointermove", (ev) => {
      if (!drag) return;
      const { point } = this.stage.pick(ev, []);
      if (!point) return;
      const inst = this._inst(drag.uid);
      const step = $("#tr-snap").checked ? this.lib.stage.grid : 0;
      const x = snap(point.x - drag.offset[0], step);
      const z = snap(point.z - drag.offset[1], step);
      const res = checkPlacement(this.lib.stage, this.arr.instruments, inst.uid, x, z, (o) => this._def(o).name);
      inst.position = [x, 0, z];
      this._syncView(inst);
      if (res.ok) {
        drag.lastValid = [x, 0, z];
        drag.invalid = null;
      } else {
        drag.invalid = res.reason;
        setRing(this.views.get(inst.uid), "invalid");
      }
      this._renderInspector();
    });
    const end = () => {
      if (!drag) return;
      const inst = this._inst(drag.uid);
      if (drag.invalid) {
        toast(`Can't place there: ${drag.invalid}`, "warn");
        inst.position = drag.lastValid;
      }
      if (inst.position[0] !== drag.start[0] || inst.position[2] !== drag.start[2]) this._markDirty();
      this._syncView(inst);
      this._renderInspector();
      drag = null;
      this.stage.controls.enabled = true;
    };
    dom.addEventListener("pointerup", (ev) => {
      const wasDrag = !!drag;
      end();
      const moved = this._downAt && Math.hypot(ev.clientX - this._downAt[0], ev.clientY - this._downAt[1]) > 4;
      if (!wasDrag && !moved && ev.button === 0) this.select(null);   // click on empty stage
    });
    dom.addEventListener("pointercancel", end);
  }

  _onKey(e) {
    if (!this.visible || e.target.closest("input, select, textarea, dialog")) return;
    if (e.key === " ") { e.preventDefault(); this.playing ? this.stop() : this.play(); return; }
    const inst = this._inst(this.selected);
    if (!inst) return;
    const step = e.shiftKey ? 0.1 : this.lib.stage.grid;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[e.key]) {
      e.preventDefault();
      const x = +(inst.position[0] + moves[e.key][0]).toFixed(3);
      const z = +(inst.position[2] + moves[e.key][1]).toFixed(3);
      const res = checkPlacement(this.lib.stage, this.arr.instruments, inst.uid, x, z, (o) => this._def(o).name);
      if (!res.ok) {
        toast(`Can't move there: ${res.reason}`, "warn");
        setRing(this.views.get(inst.uid), "invalid");
        setTimeout(() => this._syncView(inst), 350);
        return;
      }
      this._edit((i) => { i.position = [x, 0, z]; });
    } else if (e.key === "q" || e.key === "Q") this._edit((i) => { i.rotation_y_deg = wrapDeg(i.rotation_y_deg + 15); });
    else if (e.key === "e" || e.key === "E") this._edit((i) => { i.rotation_y_deg = wrapDeg(i.rotation_y_deg - 15); });
    else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); this.removeSelected(); }
    else if (e.key === "Escape") this.select(null);
    else if (e.key === "r" || e.key === "R") this.resetSelected();
  }

  // ------------------------------------------------------------------ instrument operations
  select(uid) {
    const prev = this.selected;
    this.selected = uid;
    for (const id of [prev, uid]) {
      const inst = id && this._inst(id);
      if (inst) this._syncView(inst);
    }
    this._renderInspector();
  }

  addInstrument(id) {
    const def = this.defs.get(id);
    const spot = findFreeSpot(this.lib.stage, this.arr.instruments, def.default_position[0], def.default_position[2]);
    if (!spot) {
      toast("No free space left on the stage.", "warn");
      return;
    }
    if (this.arr.instruments.length >= 48) {
      toast("An arrangement can hold at most 48 instruments.", "warn");
      return;
    }
    const inst = this._instance(def, [spot[0], 0, spot[1]]);
    this.arr.instruments.push(inst);
    this._addView(inst);
    this.select(inst.uid);
    this._syncAll();
    this._markDirty();
    logEvent(`Added ${def.name}`);
  }

  async removeSelected() {
    const inst = this._inst(this.selected);
    if (!inst) return;
    const ok = await confirmAction("Remove instrument?", `Remove ${this._def(inst).name} from "${this.arr.name}"?`, "Remove");
    if (!ok) return;
    this.stage.scene.remove(this.views.get(inst.uid));
    this.views.delete(inst.uid);
    const ch = this.channels.get(inst.uid);
    if (ch) ch.dispose();
    this.channels.delete(inst.uid);
    this.arr.instruments = this.arr.instruments.filter((i) => i !== inst);
    this.selected = null;
    this._syncAll();
    this._markDirty();
    this._renderInspector();
  }

  resetSelected() {
    const inst = this._inst(this.selected);
    if (!inst) return;
    const def = this._def(inst);
    const spot = checkPlacement(this.lib.stage, this.arr.instruments, inst.uid, def.default_position[0], def.default_position[2]).ok
      ? [def.default_position[0], def.default_position[2]]
      : [inst.position[0], inst.position[2]];
    if (spot[0] !== def.default_position[0] || spot[1] !== def.default_position[2]) toast("Default position is occupied; kept current position.", "warn");
    this._edit((i) => Object.assign(i, {
      position: [spot[0], 0, spot[1]], rotation_y_deg: def.default_rotation_y_deg, scale: def.default_scale,
      gain: def.default_gain, muted: false, solo: false, articulation: def.default_articulation,
    }), true);
  }

  // ------------------------------------------------------------------ arrangements
  async _refreshList(selectId) {
    try {
      this.listCache = (await api.arrangements()).arrangements;
    } catch (e) {
      this.listCache = [];
      toast(e.message, "bad");
    }
    const list = $("#arr-list");
    list.replaceChildren(...this.listCache.map((a) => {
      const o = new Option(a.valid ? `${a.name}  · ${a.instrument_count} instr.` : `⚠ ${a.file} (invalid)`, a.id);
      if (!a.valid) o.title = a.error;
      return o;
    }));
    list.value = selectId || (this.arr && this.arr.id) || "";
  }

  async load(id) {
    try {
      const doc = await api.arrangement(id);
      this._apply(doc);
      await this._refreshList(id);
      return true;
    } catch (e) {
      toast(`Could not load arrangement: ${e.message}`, "bad");
      return false;
    }
  }

  async _loadSelected() {
    const id = $("#arr-list").value;
    if (!id) return;
    if (this.dirty && !(await confirmAction("Discard unsaved changes?", `"${this.arr.name}" has unsaved changes.`, "Discard"))) return;
    if (await this.load(id)) toast(`Loaded "${this.arr.name}"`, "ok");
  }

  async save() {
    try {
      const saved = await api.saveArrangement(this.arr.id, this.arr);
      this.arr.created_at = saved.created_at;
      this.arr.modified_at = saved.modified_at;
      this.dirty = false;
      $("#arr-dirty").hidden = true;
      await this._refreshList(this.arr.id);
      toast(`Saved "${this.arr.name}"`, "ok");
      return true;
    } catch (e) {
      toast(`Save failed: ${e.message}`, "bad");
      return false;
    }
  }

  async newArrangement() {
    if (this.dirty && !(await confirmAction("Discard unsaved changes?", `"${this.arr.name}" has unsaved changes.`, "Discard"))) return;
    const name = await promptText("New arrangement", "Name", "My arrangement");
    if (!name) return;
    const doc = this._blank(name);
    const violin = this.defs.get("violin") || this.lib.instruments[0];
    doc.instruments.push(this._instance(violin, violin.default_position));
    this._apply(doc, true);
    toast("New arrangement created. Save it to keep it.", "info");
  }

  async rename() {
    const name = await promptText("Rename arrangement", "Name", this.arr.name);
    if (!name || name === this.arr.name) return;
    this.arr.name = name;
    $("#arr-name").textContent = name;
    await this.save();
  }

  async duplicate() {
    const name = await promptText("Duplicate arrangement", "Name of the copy", `${this.arr.name} (copy)`);
    if (!name) return;
    const copy = JSON.parse(JSON.stringify(this.arr));
    copy.id = newId(name);
    copy.name = name;
    delete copy.created_at;
    this._apply(copy, true);
    await this.save();
  }

  async deleteCurrent() {
    const exists = this.listCache.some((a) => a.id === this.arr.id);
    if (!exists) {
      toast("This arrangement has not been saved yet.", "warn");
      return;
    }
    if (!(await confirmAction("Delete arrangement?", `Permanently delete "${this.arr.name}" from disk?`))) return;
    try {
      await api.deleteArrangement(this.arr.id);
      toast(`Deleted "${this.arr.name}"`, "ok");
    } catch (e) {
      toast(e.message, "bad");
      return;
    }
    await this._refreshList();
    const next = this.listCache.find((a) => a.valid);
    if (next) await this.load(next.id);
    else this._apply(this._blank("Untitled arrangement"), true);
  }

  async compare() {
    const valid = this.listCache.filter((a) => a.valid);
    if (valid.length < 2) {
      toast("Save at least two arrangements to compare them.", "warn");
      return;
    }
    const selA = el("select", {}, ...valid.map((a) => new Option(a.name, a.id)));
    const selB = el("select", {}, ...valid.map((a) => new Option(a.name, a.id)));
    selA.value = (this.ab && this.ab.a) || this.arr.id;
    if (!valid.some((a) => a.id === selA.value)) selA.value = valid[0].id;
    selB.value = (this.ab && this.ab.b) || valid.find((a) => a.id !== selA.value).id;
    const out = el("div", { class: "compare-out" });
    const render = async () => {
      try {
        const [a, b] = await Promise.all([api.arrangement(selA.value), api.arrangement(selB.value)]);
        out.innerHTML = renderComparison(compareArrangements(a, b, (id) => (this.defs.get(id) || { name: id }).name));
      } catch (e) {
        out.textContent = e.message;
      }
    };
    selA.onchange = render;
    selB.onchange = render;
    await render();
    const body = el("div", {},
      el("div", { class: "row2" }, el("label", {}, el("span", { class: "field-label" }, "Arrangement A"), selA),
        el("label", {}, el("span", { class: "field-label" }, "Arrangement B"), selB)),
      out,
      el("p", { class: "hint" }, "Differences are measured, not judged: this does not say which arrangement sounds better. Use the A/B switch to listen."));
    const ok = await modal({ title: "Compare arrangements", body, okLabel: "Listen A/B", wide: true });
    if (!ok) return;
    if (this.dirty && !(await confirmAction("Discard unsaved changes?", `"${this.arr.name}" has unsaved changes.`, "Discard"))) return;
    this.ab = { a: selA.value, b: selB.value, names: [selA.selectedOptions[0].text, selB.selectedOptions[0].text], current: "a" };
    await this.load(this.ab.a);
  }

  _renderAB() {
    let bar = $("#ab-bar");
    if (!this.ab) { if (bar) bar.remove(); return; }
    if (!bar) {
      bar = el("div", { id: "ab-bar", class: "panel float", style: "left:50%;top:14px;transform:translateX(-50%);display:flex;gap:8px;align-items:center;padding:8px 10px" });
      $("#screen-composer .composer").append(bar);
    }
    const cur = this.arr.id === this.ab.a ? "a" : this.arr.id === this.ab.b ? "b" : null;
    bar.innerHTML = "";
    bar.append(el("strong", { style: "font-size:12px;color:#a9b0bf" }, "A/B"));
    for (const k of ["a", "b"]) {
      bar.append(el("button", { class: `btn sm toggle`, "aria-pressed": String(cur === k),
        onclick: () => this._switchAB(k) }, `${k.toUpperCase()}: ${this.ab.names[k === "a" ? 0 : 1]}`));
    }
    bar.append(el("button", { class: "btn sm ghost", onclick: () => { this.ab = null; this._renderAB(); } }, "×"));
  }

  async _switchAB(k) {
    if (this.dirty && !(await confirmAction("Discard unsaved changes?", "Switching discards unsaved edits.", "Discard"))) return;
    await this.load(this.ab[k]);
  }

  // ------------------------------------------------------------------ rendering
  _renderInspector() {
    const inst = this.arr && this._inst(this.selected);
    $("#inspector-empty").hidden = !!inst;
    $("#inspector-body").hidden = !inst;
    if (!inst) return;
    const def = this._def(inst);
    $("#insp-swatch").style.background = def.color;
    $("#insp-name").textContent = def.name;
    const pose = this._listenerPose();
    const src = [inst.position[0], SOURCE_HEIGHT * inst.scale, inst.position[2]];
    kv($("#insp-pos"), [
      ["Position", `x ${inst.position[0].toFixed(2)} m, z ${inst.position[2].toFixed(2)} m`],
      ["Section", def.section],
      ["To listener", `${distance3(pose.pos, src).toFixed(2)} m, ${azimuthLabel(azimuth(pose.pos, pose.forward, src))}`],
    ]);
    $("#insp-gain").value = inst.gain;
    $("#insp-gain-val").textContent = `${fmt(gainToDb(inst.gain), 1)} dB`;
    $("#insp-rot").value = inst.rotation_y_deg;
    $("#insp-rot-val").textContent = `${inst.rotation_y_deg.toFixed(0)}°`;
    $("#insp-scale").value = inst.scale;
    $("#insp-scale-val").textContent = `${inst.scale.toFixed(2)}×`;
    $("#insp-mute").setAttribute("aria-pressed", String(inst.muted));
    $("#insp-solo").setAttribute("aria-pressed", String(inst.solo));
    const arts = $("#insp-arts");
    arts.replaceChildren(...def.articulations.map((a) => el("button", {
      class: "art", type: "button", "aria-pressed": String(inst.articulation === a.id),
      disabled: !a.supported, title: a.supported ? `Use ${a.label}` : a.reason,
      onclick: () => this._edit((i) => { i.articulation = a.id; }),
    }, a.label)));
    const unsupported = def.articulations.filter((a) => !a.supported);
    $("#insp-art-note").textContent = unsupported.length
      ? `Unavailable: ${unsupported.map((a) => `${a.label} (${a.reason})`).join(" ")}` : "";
  }

  _renderDiagnostics() {
    const eng = this.engine;
    const pose = this._listenerPose();
    const inst = this._inst(this.selected);
    const rows = [
      ["AudioContext", eng.ctx ? `${eng.state}, ${eng.ctx.sampleRate} Hz` : "not started (press Play)"],
      ["Output latency", eng.ctx ? `${((eng.ctx.baseLatency || 0) * 1000).toFixed(1)} ms base` : "—"],
      ["Listener", `${this.arr.listener.preset} @ (${pose.pos.map((v) => v.toFixed(1)).join(", ")})`],
      ["Panning", `${this.arr.audio.panning_model}, distance model inverse`],
      ["Reverb mix", this.arr.audio.reverb_mix.toFixed(2)],
    ];
    if (inst) {
      const sp = this._def(inst).spatial;
      const src = [inst.position[0], SOURCE_HEIGHT * inst.scale, inst.position[2]];
      const d = distance3(pose.pos, src);
      const dg = inverseDistanceGain(d, sp.ref_distance, sp.max_distance, sp.rolloff);
      rows.push(
        ["Selected", this._def(inst).name],
        ["Source pos", `(${src.map((v) => v.toFixed(2)).join(", ")})`],
        ["Distance", `${d.toFixed(2)} m`],
        ["Azimuth", azimuthLabel(azimuth(pose.pos, pose.forward, src))],
        ["Distance gain", `${fmt(gainToDb(dg), 1)} dB (ref ${sp.ref_distance} m, rolloff ${sp.rolloff})`],
        ["Cone", `${sp.cone_inner_deg}°/${sp.cone_outer_deg}°, outer ${sp.cone_outer_gain}`],
        ["Volume x mute/solo", effectiveGain(inst, anySolo(this.arr.instruments)).toFixed(2)],
        ["Channel", this.channels.has(inst.uid) ? "connected" : "not created yet"],
      );
    } else rows.push(["Selected", "none (click an instrument)"]);
    kv($("#diag-kv"), rows);
    const [l, r] = eng.levels();
    for (const [side, db] of [["l", l], ["r", r]]) {
      const pct = Number.isFinite(db) ? Math.max(0, Math.min(100, ((db + 60) / 60) * 100)) : 0;
      $(`#meter-${side}`).style.width = `${pct}%`;
      $(`#meter-${side}-db`).textContent = Number.isFinite(db) ? `${db.toFixed(1)} dBFS` : "silent";
    }
  }

  _loop() {
    if (!this.visible) return;
    this._raf = requestAnimationFrame(() => this._loop());
    this.stage.render();
    if (this.arr && this.arr.listener.preset === "camera") this._updateListener();
    const now = performance.now();
    if (!$("#audio-diag").hidden && this.arr && now - (this._diagAt || 0) > 100) {
      this._diagAt = now;
      this._renderDiagnostics();
    }
  }
}

function wrapDeg(d) {
  let v = ((d + 180) % 360 + 360) % 360 - 180;
  if (v === -180) v = 180;
  return v;
}

function azimuthLabel(rad) {
  const deg = (rad * 180) / Math.PI;
  if (Math.abs(deg) < 3) return "centre";
  return `${Math.abs(deg).toFixed(0)}° ${deg > 0 ? "right" : "left"}`;
}

function renderComparison(c) {
  const rows = c.rows.map((r) => `<tr>
    <td>${escapeHtml(r.instrument)}</td>
    <td class="${r.movedMeters > 0.01 ? "changed" : ""}">${r.movedMeters.toFixed(2)} m</td>
    <td class="${Math.abs(r.rotationDeltaDeg) > 0.5 ? "changed" : ""}">${r.rotationDeltaDeg > 0 ? "+" : ""}${r.rotationDeltaDeg}°</td>
    <td class="${r.gainDeltaDb ? "changed" : ""}">${r.gainDeltaDb === null ? "mute" : `${r.gainDeltaDb > 0 ? "+" : ""}${r.gainDeltaDb} dB`}</td>
    <td class="${r.articulationChanged ? "changed" : ""}">${escapeHtml(r.articulationA)} → ${escapeHtml(r.articulationB)}</td>
    <td class="${r.mutedChanged || r.soloChanged ? "changed" : ""}">${r.mutedChanged ? "mute " : ""}${r.soloChanged ? "solo" : ""}${!r.mutedChanged && !r.soloChanged ? "—" : ""}</td>
  </tr>`).join("");
  const only = [...c.onlyA.map((n) => `${escapeHtml(n)} only in A`), ...c.onlyB.map((n) => `${escapeHtml(n)} only in B`)];
  return `
    <p><strong>${c.countA}</strong> instruments in A, <strong>${c.countB}</strong> in B &middot;
      ${c.changedCount} difference(s) &middot; listener ${escapeHtml(c.audio.listener[0])} / ${escapeHtml(c.audio.listener[1])}
      &middot; tempo ${c.audio.tempo[0]} / ${c.audio.tempo[1]} BPM &middot; reverb ${c.audio.reverb[0]} / ${c.audio.reverb[1]}</p>
    ${only.length ? `<p class="warn-text">${only.join(", ")}</p>` : ""}
    <table class="compare-table"><thead><tr><th>Instrument</th><th>Moved</th><th>Rotation</th><th>Volume</th><th>Articulation</th><th>Mute/Solo</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="6">No matching instruments.</td></tr>`}</tbody></table>`;
}
