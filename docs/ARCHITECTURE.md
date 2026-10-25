# Architecture

## Components and runtime boundaries

| Component | Runtime | Location | Responsibility |
|---|---|---|---|
| Service / CLI | Python 3.12, aiohttp | `archestral/__main__.py`, `archestral/server.py` | HTTP + WebSocket on 127.0.0.1, owns the active input source and the single analysis pipeline, REST for settings/patterns/library/arrangements |
| Gesture analysis | Python, NumPy | `archestral/analysis/` | Preprocessing, beat detection, tempo, DTW, similarity, streaming session state machine |
| Input sources | Python | `archestral/tracking/` | Webcam (OpenCV + MediaPipe, background thread), recorded synthetic fixtures, external samples (mouse, WebXR) |
| Persistence | Python | `archestral/storage.py` | Validated settings, instrument library, versioned arrangements (atomic JSON writes, no path traversal) |
| Web client | Browser, ES modules, no build step | `web/` | App shell and router, Conductor dashboard, Three.js stage, Web Audio engine, settings, diagnostics |

Everything runs on one machine. The browser talks only to `127.0.0.1:8765`. Camera frames never
leave the Python process except as an optional low-resolution JPEG preview sent to the local page.

## Data flow (Conductor)

```
Webcam thread ──Sample(t,x,y,conf)──► BoundedSampleQueue ─┐
RecordedSource (fixture replay) ──────────────────────────┼─► ConductorService._tick (60 Hz)
ExternalSource ◄── WebSocket "samples" (mouse / WebXR) ───┘            │
                                                                       ▼
                                                     SessionAnalyzer.push(sample)
                                     validation → calibration → One Euro smoothing → buffer
                                       → (every 33 ms) uniform resample → detect_beats
                                       → tempo / timing error / DTW similarity
                                                                       │
                      events: session_state, calibration, beat, feedback (5 Hz), summary
                                                                       ▼
                                      WebSocket broadcast (protocol v1) → browser
```

**Shared trajectory format.** Every source produces `Sample(t, x, y, confidence)` in normalized 2D
space (x right, y up, nominally 0..1). The webcam converts from image space (`y = 1 - y_img`,
optionally mirrored), the mouse pad maps its square region into 0..1, and WebXR maps a
1 m × 1 m box around chest height (1.3 m). All of them go through the same `SessionAnalyzer`,
so the algorithm exists only once.

## Gesture-analysis pipeline

1. **Timestamp validation.** Timestamps must be finite and strictly increasing; anything else is rejected and counted.
2. **Invalid-sample rejection.** Non-finite coordinates (no hand), out-of-range coordinates and
   low confidence (< `min_confidence`) count as tracking loss but still advance the clock.
3. **Calibration.** The first `calibration_s` seconds of movement give the robust center and scale
   (midpoint and half-extent of the 5th–95th percentile box). Too little movement means "insufficient movement" and calibration retries.
4. **Normalization.** `(p - center) / scale`, so a typical pattern spans about [-1, 1].
5. **Smoothing.** One Euro filter (min cutoff 2.5 Hz, β 0.4). The cutoff rises with speed, so jitter is removed while the
   sharp ictus keeps its timing.
6. **Gaps.** A gap longer than `gap_threshold_s` ends the segment: the buffer is cleared, nothing is
   interpolated across it, and an invalid interval is recorded.
7. **Resampling.** Linear interpolation to 60 Hz inside the current segment.
8. **Beat detection** (`beats.py`). A beat is a local speed minimum where the stroke peak in the last 0.35 s
   is ≥ `min_approach_speed`, speed ≤ `dip_ratio` × peak, vertical velocity reverses from
   down to up, and the minimum is outside the refractory window (60 / `max_bpm`). The down→up rule
   rejects the apex of each rebound. A candidate is only finalized after a lookahead of
   `detection_lookahead_s` (150 ms), so beat events arrive about 150–250 ms after the physical ictus.
9. **Tempo** (`tempo.py`). The median of the last `tempo_window` valid intervals; `BPM = 60 / T`. Intervals
   outside [60/max_bpm, 60/min_bpm] are rejected. With fewer than 3 valid intervals the tempo is
   reported as unavailable (`null`).
10. **Beat timing error.** The mean |offset| of recent beats from a grid at the target tempo whose
    phase is the circular mean of the beat phases (in ms).
11. **Similarity** (`similarity.py`, `dtw.py`). The last full bar (between beats *n−B* and *n*) and the
    reference template are each resampled to 64 points and shape-normalized (mean removed, divided
    by RMS radius). DTW (Euclidean, Sakoe-Chiba band 25%, length-normalized) runs against every
    rotation of the template; the best rotation also labels beat-in-bar. The estimate is
    `exp(-d / 0.35)`, an uncalibrated prototype indicator.

### Reference patterns

`patterns/*.json` (schema v1) stores ordered ictus points with rebound and approach heights, and the
derived one-bar trajectory `points: [phase, x, y]`. 4/4 is the primary exercise; 3/4 and 2/4 are
included as data only, to show that new patterns need no code changes. The patterns are generated by
`python -m archestral gen-fixtures` from `BUILTIN_SPECS` with cubic Bézier strokes.

### Future ML classifier (not implemented)

The analysis layer is modular: `gesture_similarity` could be swapped for (or compared against) a learned
classifier that consumes the same resampled 64-point bar. A sound study would need:
labelled real recordings from several conductors (beat positions annotated against audio or video),
features made of normalized position, velocity and acceleration per resampled bar, a split by person
(not by window) into train/validation/test, per-beat F1 and tempo MAE as metrics, a model serialized with
version metadata, a runtime interface `predict(bar_xy) -> (label, confidence)`, calibrated confidence
(reliability diagrams or temperature scaling), and a head-to-head comparison against the DTW baseline.
No model was trained here, because there is no real labelled data.

## Audio architecture (browser, Web Audio)

```
voice nodes ─► channel.input ─► volume (gain × mute/solo) ─► PannerNode (HRTF, inverse, cone) ─┬─► master ─► limiter ─► destination
                                                                                              └─► reverb send ─► Convolver (generated IR) ─► return ─► master
limiter ─► ChannelSplitter ─► AnalyserNode L / R   (measured levels for diagnostics)
directBus (conductor clicks & chords, metronome) ─► master + reverb
```

- `AudioEngine` (`web/js/audio/engine.js`) is created on the first user gesture (browser autoplay policy).
- Voices (`voices.js`) are synthesized **test** timbres: detuned saw with vibrato and tremolo
  (bowed), Karplus-Strong (pizzicato), sine and breath noise (flute), filtered saw (brass), and
  pitched sine with noise (timpani). Each articulation changes the synthesis, not just a label.
- **Composer scheduling.** Lookahead scheduler (25 ms timer, 150 ms horizon) on `AudioContext.currentTime`, so it is sample-accurate.
- **Conductor synchronisation policy.** Beat-triggered sounds are *reactive*: they play
  immediately when a beat event arrives (detection latency + network ≈ 150–250 ms after the ictus).
  The optional reference metronome is scheduled sample-accurately at the target tempo but is *not*
  phase-locked to the user's beats.
- Middleware boundary: all spatial routing goes through `createSpatialChannel()` / `setListener()`,
  which is the integration point for an FMOD or Wwise backend.

## Composer

- Instrument library (`library/instruments.json`, schema v1): id, name, family, section, model
  reference, default transform, gain, articulations (with `supported` and a reason), audio voice/part/octave
  (with an optional sample slot), and spatial settings (ref/max distance, rolloff, cone).
- Stage rules (`web/js/core/stage.js`): x within ±`half_width`, z within [−`depth_back`, `depth_front`],
  minimum spacing `min_spacing`, grid snap `grid`. If a move is invalid, the ring turns red, a toast explains why, and the instrument reverts to its last valid position.
- Coordinates: x right (from the audience), y up, z toward the audience. `rotation_y_deg = 0` faces the audience.
- Listener presets: podium (0, 1.6, 4.2), audience (0, 1.2, 11), or the camera, followed every frame.

## Persistence

| Data | Where | Format |
|---|---|---|
| Settings | `data/settings.json` | Validated field by field. An unreadable file is moved aside to `settings.invalid-<ts>.json` and defaults are used |
| Arrangements | `data/arrangements/<id>.json` | Schema v1, ids `[a-z0-9-]`, ≤ 48 instruments, ≤ 256 KB, validated against the library on save and load |
| Patterns | `patterns/*.json` | Schema v1, validated; built-ins are the fallback |
| Fixtures | `tests/fixtures/synthetic/*.json` | `"synthetic": true`, deterministic (seeded) |

`ARCHESTRAL_DATA_DIR` or `--data-dir` moves the data folder.

## XR architecture

- **VR conducting:** `web/js/conductor/xr.js` uses WebXR (`immersive-vr`, `local-floor`) through
  three.js. The controller position is mapped into the shared 2D trajectory space and sent as
  `samples` with `source: "webxr"`, so it uses the same analyzer as the webcam. A visual ring pulses on
  each beat, and haptics are sent only if `gamepad.hapticActuators[0].pulse` exists.
- **Capability checks:** secure context, `navigator.xr`, `isSessionSupported("immersive-vr")`. On a
  laptop without a headset, the VR option is disabled with an explanation.
- **Not implemented:** VR manipulation of Composer instruments, and AR stage placement (WebXR
  `immersive-ar` with hit-test would be the path). See KNOWN_LIMITATIONS.
