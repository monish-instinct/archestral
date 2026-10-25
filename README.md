# Archestral: Adaptive Orchestral Sandbox

*A dual-mode system for embodied conducting and spatial orchestration learning.*

Archestral teaches the link between conducting gestures, musical timing, orchestral dynamics,
instrument placement and spatial sound. It runs entirely on a laptop: a local Python service
does the webcam hand tracking and gesture analysis, and a browser UI provides the 3D stage
and spatial audio. You don't need a GPU, a headset or a cloud account.

| Mode | What you do | What the system does |
|---|---|---|
| **A: Conductor** | Conduct a 4/4 pattern with your hand in front of the webcam (or with the mouse) | Tracks your wrist (MediaPipe Hands), detects beats (ictus), estimates tempo, compares your pattern against a reference with Dynamic Time Warping, and plays a short chorale that follows your beats, getting louder as your gestures get bigger |
| **B: Composer** | Place, move and rotate instruments on a 3D stage; set volume, mute, solo and articulation | Renders each instrument as a positioned HRTF sound source, moves the listener between podium and audience, and lets you save, load and A/B compare arrangements |

## Quick start (macOS / Linux)

```bash
./run.sh
```

The first run creates `.venv` and installs the pinned dependencies (Python 3.10–3.12). After
that it starts the service on `http://127.0.0.1:8765` and opens your browser. Stop it with **Ctrl+C**.

Manual equivalent:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m archestral
```

**Camera permission (macOS):** the first time you choose *Webcam* in Conductor mode, macOS asks
whether the app running Archestral (e.g. Terminal or iTerm) may use the camera. If you dismissed
that prompt, enable it under *System Settings → Privacy & Security → Camera*, then press **Start**
again. Mouse and Test-data input work without a camera.

## Implemented features

- **Conductor:** four interchangeable inputs that all feed one analysis pipeline:
  webcam (MediaPipe Hands, wrist or index tip), mouse/trackpad pad, recorded *synthetic* test
  trajectories (always labelled as test input), and a WebXR controller adapter.
- Preprocessing with timestamp validation, invalid-sample rejection, calibration-based
  normalization, One Euro smoothing, gap segmentation and uniform resampling.
- Beat (ictus) detection from speed dips plus down→up direction reversal, with a refractory window.
- Tempo from the rolling median of beat intervals (`BPM = 60 / T`), tempo deviation, beat timing
  error, a DTW gesture-similarity estimate (labelled *prototype*), tracking confidence and tracking gaps.
- Live dashboard: trajectory pad with the reference-pattern overlay, beat-in-bar indicator, tempo
  chart, status banners (camera unavailable, tracking lost, calibration, no tempo yet, service
  disconnected, audio unavailable), and a session Results page.
- Beat-reactive audio (click and chorale chords whose loudness follows gesture size) plus an optional
  reference metronome scheduled on the audio clock.
- **Composer:** procedural 3D stage, five data-driven instruments (violin, cello, flute, horn,
  timpani; placeholder models), drag/keyboard placement with grid snapping, stage bounds and
  minimum spacing, rotation, scale, volume, mute, solo, articulations (unsupported ones disabled
  with a reason), and Web Audio spatialization (HRTF, inverse distance, directional cones, reverb).
- Audio diagnostics with **measured** L/R output levels, so you can watch placement change the mix.
- Versioned JSON arrangements: save, load, new, rename, duplicate, delete (with confirmation),
  and A/B comparison with a measured difference table.
- Persistent validated settings, a Diagnostics page and a first-run explainer.

## Architecture (short)

```
 webcam ─► tracking thread (OpenCV + MediaPipe) ─┐
 mouse / WebXR (browser) ── WebSocket samples ───┼─► SessionAnalyzer (NumPy) ─► beats, feedback, summary
 recorded synthetic fixtures ────────────────────┘          │
                                                  WebSocket JSON (protocol v1, 127.0.0.1)
                                                            ▼
            Browser UI: Conductor dashboard · Three.js stage · Web Audio spatial mixer
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Tests

```bash
.venv/bin/python -m pytest
node --test web/tests/*.test.mjs
```

There are 100 Python tests (preprocessing, beats, tempo, DTW, patterns, the streaming session,
protocol, storage, and end-to-end HTTP/WebSocket) and 12 JavaScript tests (protocol parsing,
mixer, stage rules, A/B comparison). See [docs/TESTING.md](docs/TESTING.md).

## Supported platforms

Developed and tested on macOS 26 (Apple Silicon) with Python 3.12 and a Chromium-based browser.
It should run anywhere MediaPipe 0.10.21 has wheels (macOS, Windows, Linux x86-64; Python
3.10–3.12). Without MediaPipe the app still runs, and webcam input reports itself unavailable.

## Documentation

- [docs/SETUP.md](docs/SETUP.md): step-by-step developer setup
- [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md): a 5-minute walkthrough for presenting the project
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/PROTOCOL.md](docs/PROTOCOL.md), [docs/TECHNICAL_DECISIONS.md](docs/TECHNICAL_DECISIONS.md)
- [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md): status of every feature
- [docs/TESTING.md](docs/TESTING.md), [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md)

## Troubleshooting

| Symptom | Fix |
|---|---|
| Beats missed or tempo jumps around | Stand about an arm's length from the camera, use big gestures with a small bounce on each beat, then press Recalibrate. Settings → Analysis has the beat thresholds |
| "Camera unavailable" banner | Grant camera access to your terminal app (see above) and press Start again; or pick another camera index |
| `./run.sh` says Python 3.10–3.12 is needed | `brew install python@3.12` (MediaPipe 0.10.21 has no Python 3.13 wheels) |
| Port 8765 in use | `./run.sh --port 8800` |
| No sound | Click anywhere in the page first (browsers block audio until a user gesture); check the Audio chip |
| "Analysis service disconnected" | The Python process stopped; restart `./run.sh` and the page reconnects automatically |

## Known limitations

The models are placeholders and the instrument audio is synthesized test audio, not real
recordings. The similarity score is uncalibrated, and the WebXR path has not been tested on a
headset. The full list is in [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Third-party licenses

three.js r170 (MIT, vendored in `web/vendor/three`), MediaPipe (Apache 2.0), OpenCV (Apache 2.0),
NumPy (BSD), aiohttp (Apache 2.0).
