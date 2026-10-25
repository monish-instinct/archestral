# Developer Setup

## Prerequisites
- Python **3.10–3.12** (MediaPipe 0.10.21 has no 3.13 wheels). On macOS: `brew install python@3.12`.
- A recent Chromium-based browser, Firefox or Safari (WebGL2 + Web Audio).
- Optional: Node 18+ to run the JavaScript unit tests. Nothing else uses Node; there is no build step.
- Optional: a webcam, and a WebXR headset for VR input.

## Steps
```bash
git clone https://github.com/monish-instinct/archestral.git
cd archestral
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m archestral diagnose            # checks numpy / aiohttp / OpenCV / MediaPipe
.venv/bin/python -m pytest                         # 99 tests should pass
.venv/bin/python -m archestral                     # starts http://127.0.0.1:8765 and opens the browser
```
`./run.sh` does all of this automatically.

## Useful options
| Option | Meaning |
|---|---|
| `--port 8800` | use another port |
| `--no-browser` | don't open a browser tab |
| `--data-dir PATH` or `ARCHESTRAL_DATA_DIR` | where settings and arrangements are stored (default `./data`, git-ignored) |
| `--host 0.0.0.0` | **explicitly** expose the service on the network (needed for a headset on the same Wi-Fi; WebXR also needs HTTPS there) |
| `--log-level DEBUG` | verbose service logs |

## Project layout
```
archestral/            Python package (service, analysis, tracking, storage, protocol)
  analysis/            config, trajectory, preprocessing, beats, tempo, dtw, patterns, similarity, session
  tracking/            base classes, webcam (MediaPipe), recorded fixtures
patterns/              reference conducting patterns (JSON, schema v1)
library/instruments.json   instrument definitions (data-driven)
web/                   browser client (no build step)
  js/core/             pure, unit-tested modules (protocol, mixer, stage rules, compare, format)
  js/audio/            Web Audio engine, synthesized voices, score
  js/conductor/        Conductor mode + WebXR adapter
  js/composer/         Composer mode + procedural three.js stage
  vendor/three/        three.js r170 (MIT)
tests/                 pytest suites + synthetic fixtures
docs/                  documentation
```

## Regenerating fixtures and patterns
```bash
.venv/bin/python -m archestral gen-fixtures
```
Generation is deterministic; `test_fixtures_are_marked_synthetic_and_deterministic` checks that the
committed files match the generator.

## Adding an instrument
Add an entry to `library/instruments.json` (voice: `bowed_string` | `flute` | `brass` | `timpani`;
part: `melody` | `descant` | `tenor` | `bass` | `timpani`) and, optionally, a new `placeholder:*` shape in
`web/js/composer/stage.js`. The library is validated at startup.

## Adding a conducting pattern
Add `patterns/<id>.json` with `beats_per_bar`, ordered `ictus` points (x, y, rebound, approach).
The trajectory `points` are regenerated on load. The pattern then appears in the Conductor selector.
