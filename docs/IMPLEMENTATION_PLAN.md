# Implementation Plan and Status

Legend: **Implemented** = the code exists and is wired into the app · **Auto-tested** = covered by
automated tests that pass · **Browser-verified** = exercised manually in a browser on the dev machine
(macOS 26, Apple M2) · **Not verified** = no test or manual run · **Blocked** = needs hardware or assets that aren't available.

## Phase 0: audit (done)
The repository was empty (it had been created for this project). No Unity Editor is installed, which led to
TD-1. Available: Python 3.11–3.13, Node 22, .NET 8/9, and a FaceTime HD camera.

## Status

| Area | Feature | Status |
|---|---|---|
| Foundation | Bootstrap: config, capability detection, connection, startup errors | Implemented · Browser-verified |
| | Main menu, navigation, status chips, first-run dialog | Implemented · Browser-verified |
| | Validated persistent settings; corrupt file recovery | Implemented · Auto-tested · Browser-verified |
| | Structured logging, rate-limited warnings, client event log | Implemented · Browser-verified |
| Analysis | Shared `Sample` trajectory type | Implemented · Auto-tested |
| | Validation, normalization, One Euro smoothing, gaps, resampling | Implemented · Auto-tested |
| | Beat detection | Implemented · Auto-tested |
| | Tempo, deviation, timing error | Implemented · Auto-tested |
| | DTW + similarity + beat-in-bar labelling | Implemented · Auto-tested |
| | Pattern format; 4/4 primary, 3/4 and 2/4 as data | Implemented · Auto-tested |
| | Streaming session state machine, calibration, insufficient-movement detection | Implemented · Auto-tested |
| Inputs | Recorded synthetic fixtures (7 cases), labelled as test input | Implemented · Auto-tested · Browser-verified |
| | Mouse / trackpad conducting pad | Implemented · Auto-tested (WebSocket) · Browser-verified (synthetic pointer events) |
| | Webcam: MediaPipe Hands, wrist/index tip, preview, loss, reacquire, cleanup | Implemented · **User-run on the dev Mac**: permission prompt, camera start and MediaPipe confirmed in the service log; detection accuracy on real hands not yet measured |
| | Live session recording for tuning (`data/recordings`) | Implemented · Auto-tested |
| | Robustness tuning (speed smoothing, adaptive threshold, rebound rule, tempo-aware refractory, bar-span tempo, small-movement warning) | Implemented · Auto-tested on webcam-like synthetic data (`tests/test_robustness.py`) |
| | WebXR controller conducting + haptics | Implemented · **Not verified** (no headset) |
| Service | WebSocket protocol v1 with validation | Implemented · Auto-tested |
| | REST API (settings, patterns, fixtures, library, arrangements) | Implemented · Auto-tested |
| Conductor UI | Dashboard, pad, template overlay, beat dots, tempo chart, banners, results page | Implemented · Browser-verified |
| | Beat-reactive click and chorale with dynamics; reference metronome | Implemented · Browser-verified (audio graph running; listening is a manual check) |
| Composer | Procedural stage, podium, listener, audience | Implemented · Browser-verified |
| | Data-driven library (5 instruments, placeholder models) | Implemented · Auto-tested (validation) · Browser-verified |
| | Select, drag, keyboard move/rotate, snap, bounds and spacing feedback, delete with confirm, reset | Implemented · Browser-verified (keyboard move and collision) |
| | Volume, mute, solo, articulations (unsupported disabled) | Implemented · Auto-tested (mixer rules) · Browser-verified (solo) |
| | Spatial audio: HRTF panner, distance, cones, reverb, listener presets | Implemented · Browser-verified: moving the soloed violin from x=+3 to x=−1.5 changed the measured output from R>L by ~3 dB to L>R by ~4 dB |
| | Audio diagnostics with measured L/R levels | Implemented · Browser-verified |
| | Arrangement save/load/new/rename/duplicate/delete | Implemented · Auto-tested (storage + REST) · Browser-verified (load, seed) |
| | A/B compare with difference table and A/B switch | Implemented · Auto-tested (compare) · Browser-verified (dialog) |
| XR | VR manipulation of Composer instruments | **Not implemented** |
| | AR stage placement | **Not implemented**: blocked by the lack of AR hardware; see the path in ARCHITECTURE.md |
| ML | Learned classifier | **Not implemented** by design (no labelled real data); plan in ARCHITECTURE.md |

## Highest-priority remaining work
1. Collect a few live recordings (now saved automatically) from several people and check the
   thresholds against them with `python -m archestral analyze`.
2. Record real (non-synthetic) trajectories with annotated beats and add them as a second fixture set.
3. Calibrate the similarity mapping against human ratings, or drop the 0–1 mapping in favour of raw distance bands.
4. Replace the synthesized voices with licensed samples through the library `sample` slot.
5. VR instrument manipulation (WebXR select + ray) and AR placement (WebXR hit-test).
