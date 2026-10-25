# Technical Decisions

### TD-1: A browser client instead of Unity
**Context.** The brief proposed Unity with C#. The repository was empty, and this machine (macOS 26,
Apple Silicon) has no Unity Editor. The product also had to be demonstrable from a student laptop
without installing a multi-gigabyte, licence-gated engine.
**Decision.** Keep the specified Python tracking and analysis service. Build the application shell,
both modes, the 3D stage and the spatial audio as a local web client (ES modules, three.js r170
vendored, Web Audio), served by the same Python process.
**Consequences.** One command starts everything and nothing needs compiling. Web Audio provides HRTF
panning, distance attenuation, cones, convolution reverb and sample-accurate scheduling with no
middleware licence. WebXR replaces the Unity OpenXR/AR Foundation path. A Unity front end could
later reuse the same service and protocol: only the WebSocket client would need porting.

### TD-2: Single analysis implementation in Python/NumPy
Every input source (webcam, mouse, WebXR, recorded fixtures) produces the same `Sample` type and feeds
the same `SessionAnalyzer`. Offline analysis (`python -m archestral analyze`) goes through the exact
streaming code path, which keeps tests and live behaviour identical.

### TD-3: WebSocket JSON instead of UDP
Browsers cannot open UDP sockets. WebSocket on loopback gives ordered, framed and
connection-aware messaging. The message schema is still small, versioned and whitelisted
(see PROTOCOL.md), as the brief required.

### TD-4: Beat = speed dip with a down→up reversal
Local minima of position or speed alone also fire at the apex of every rebound. Requiring a downward
approach and an upward departure, a strong approach stroke, a clear deceleration and a refractory window
keeps one event per ictus and bounds the beat rate on noisy input. Test: `test_noise_does_not_create_unbounded_beats`.

### TD-5: One Euro filter for smoothing
Its speed-adaptive cutoff removes slow jitter but follows fast strokes, so beat timing is not blurred
(unlike a fixed moving average). Test: `test_one_euro_reduces_jitter_but_follows_fast_motion`.

### TD-6: Tempo = median of recent valid intervals
The median resists the occasional missed or extra beat. Implausible intervals are rejected. With
fewer than 3 intervals the tempo is reported as unavailable rather than guessed.

### TD-7: Similarity is a labelled, uncalibrated prototype
DTW distance is length-normalized and computed on shape-normalized bars, against every template
rotation (so the bar can start on any beat; this also labels beat-in-bar). It is mapped with
`exp(-d/0.35)`. The constant was chosen so the clean schematic pattern scores about 0.85–0.9 and a
3/4 or 2/4 gesture against the 4/4 template scores about 0.15–0.2. It is **not** validated against
expert judgement, and the UI says so.

### TD-8: MediaPipe 0.10.21 pinned
Newer releases (0.10.30+, 1.x) removed the legacy `solutions.hands` API that bundles the hand model.
The Tasks API would need a separate model download. 0.10.21 also pins NumPy below 2, so
`opencv-contrib-python 4.11` is used (it comes with MediaPipe) instead of `opencv-python 5`.
Python 3.13 is not supported by this MediaPipe version.

### TD-9: The camera is opened on the main thread
On macOS, OpenCV can only show the camera-permission prompt from the main thread. The service
opens the device inside `WebcamSource.start()`, which runs on the asyncio main thread. Only frame
reading and MediaPipe inference run in the background thread. Pressing Start retries a camera that was unavailable.

### TD-10: Synthesized test audio
No licensed orchestral samples were available. Each voice and articulation is synthesized (Karplus-Strong
pizzicato, bowed saw with vibrato and tremolo, and so on), so routing, articulation and spatial effects can be heard.
The library has a `sample` slot for replacing them with real assets. The audio is labelled as
test audio in the UI and docs.

### TD-11: Server-side validated persistence
Arrangements and settings are stored as local JSON by the service. Ids are restricted to
`[a-z0-9-]` and resolved paths are checked against the storage root. Writes are atomic. Loaded
documents are validated against the instrument library before the client applies them.

### TD-12: Screens instead of separate scenes
The brief listed Bootstrap/MainMenu/Conductor/Composer/Settings/Results scenes. In the web client
these are hash-routed screens (`#/menu`, `#/conductor`, ...), with `main.js` acting as the
bootstrap (configuration, capability detection, connection, error handling).
