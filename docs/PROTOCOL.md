# Service ↔ Client Protocol (v1)

Transport: WebSocket at `ws://127.0.0.1:8765/ws`, one UTF-8 JSON object per text frame.
The service binds to loopback by default; `--host` is required to expose it.

## Envelope

| Field | Type | Required | Notes |
|---|---|---|---|
| `v` | int | yes | Protocol version, currently `1`. Other versions are rejected (`bad_version`). |
| `type` | string | yes | Message type from the whitelists below |
| `seq` | int ≥ 0 | server: yes; client: optional | Per-sender counter |
| `ts` | float | server only | Sender's monotonic clock, in seconds |

Payload fields sit next to the envelope fields. A server payload can never override `v`, `type`, `seq` or `ts`.

## Limits and validation

- Max frame size 64 KiB from the client (WebSocket `max_msg_size`) and 512 KiB accepted by the client.
- At most 256 points per `samples` message.
- Every number must be finite (`NaN`/`Infinity` are rejected); confidence must be in [0, 1].
- Unknown types or commands are rejected with an `error` reply. The message is never executed or used as a path.
- The client ignores (and counts) invalid server frames. They show up on the Diagnostics page.

## Client → service

### `samples`
```json
{"v":1,"type":"samples","seq":12,"source":"mouse","points":[[12.503,0.52,0.41,1.0],[12.519,0.53,0.39]]}
```
`source` ∈ `mouse`, `webxr`. Each point is `[t_seconds, x, y, confidence?]` in normalized space
(x right, y up, nominally 0..1). Timestamps come from the client's monotonic clock
(`performance.now()/1000` or the XR frame time) and must increase. Samples whose source is not
the active one are ignored.

### `command`
```json
{"v":1,"type":"command","seq":3,"name":"set_target_bpm","args":{"bpm":100}}
```
| name | args |
|---|---|
| `set_source` | `source` ∈ webcam, mouse, webxr, recorded, none; `camera` 0..9 (webcam); `fixture` name (recorded) |
| `start`, `pause`, `resume`, `stop`, `calibrate` | none |
| `set_target_bpm` | `bpm` 20..300 |
| `set_pattern` | `pattern` id (e.g. `4-4`) |
| `set_preview` | `enabled` bool (webcam JPEG preview for this client) |

### `ping` → `pong` (`echo_seq`)

## Service → client

| type | When | Key fields |
|---|---|---|
| `hello` | on connect | `service`, `version`, `protocol_version` |
| `status` | 1 Hz and after commands | `input{source,label,test_input,state,message,camera_state?,fps?}`, `session_state`, `pattern`, `target_bpm`, `last_error`, `last_sample_age_s` |
| `samples` | ≤ 30 Hz | `points: [[t, x, y] or [t, x, y, nx, ny]]`; `nx, ny` are normalized once calibrated |
| `session_state` | on transitions | `state` ∈ idle, calibrating, running, paused, stopped; `message` |
| `calibration` | calibration done | `normalization{center:[x,y], scale}` |
| `beat` | per detected beat | `index`, `t` (source clock, s), `beat_in_bar` (1..B or null), `confidence` 0..1, `amplitude` (normalized vertical drop), `x`, `y` (normalized) |
| `feedback` | 5 Hz while active | see below |
| `summary` | on stop | feedback fields plus `similarity_mean`, `similarity_bars`, `mean_tracking_confidence`, `rejected{…}`, `beats[]`, `beats_per_position`, `tempo_history[[t,bpm]]` |
| `preview` | ≤ 12 Hz, opt-in | `jpeg` (base64, ≤ 320 px tall) |
| `error` | on rejected input | `code`, `message` |

### `feedback` fields and units
| field | unit | null when |
|---|---|---|
| `estimated_bpm` | BPM | fewer than 3 valid beat intervals |
| `target_bpm` | BPM | never |
| `tempo_deviation_pct` | % = (est − target)/target × 100 | no estimate, or invalid target |
| `beat_timing_error_ms` | ms | fewer than 2 beats |
| `similarity.estimate` | 0..1, prototype, uncalibrated | no full bar yet |
| `similarity.normalized_distance` | DTW cost / path length, in shape-normalized units | as above |
| `tracking_confidence` | mean confidence over the last 1 s (rejected samples count as 0) | never |
| `session_duration_s` | s, excluding pauses | never |
| `beat_count`, `invalid_intervals`, `invalid_time_s`, `rejected_samples` | counts / s | never |
| `tracking` | `tracking` / `lost` / `waiting` | never |
| `calibrated`, `calibration_progress`, `insufficient_movement` | bool / 0..1 / bool | never |

## Example exchange

```text
C→S {"v":1,"type":"command","name":"set_source","args":{"source":"recorded","fixture":"reference_90bpm"}}
S→C {"v":1,"type":"status","seq":4,"ts":812.1,"input":{"source":"recorded","test_input":true,...},"session_state":"idle",...}
C→S {"v":1,"type":"command","name":"start"}
S→C {"v":1,"type":"session_state","seq":5,"ts":812.2,"state":"calibrating","message":"Calibrating: ..."}
S→C {"v":1,"type":"beat","seq":40,"ts":815.0,"index":1,"t":814.98,"beat_in_bar":null,"confidence":1.0,"amplitude":1.31,"x":0.01,"y":-0.86}
S→C {"v":1,"type":"feedback","seq":41,"ts":815.0,"state":"running","estimated_bpm":null,"tempo_status":"insufficient_beats",...}
```

## Error codes
`bad_json`, `bad_envelope`, `bad_version`, `unknown_type`, `unknown_command`, `bad_args`,
`bad_source`, `bad_points`, `too_many_points`, `too_large`, `bad_encoding`, `no_source`,
`source_unavailable`, `camera_unavailable`, `bad_pattern`.

## Versioning
Breaking changes increment `v`, and both sides reject unknown versions. New optional fields can be added
within v1 because receivers ignore unknown fields.
