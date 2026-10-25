// Client side of the versioned message protocol (docs/PROTOCOL.md).
// Pure module: no DOM access, unit-tested with `node --test web/tests`.

export const PROTOCOL_VERSION = 1;
export const MAX_MESSAGE_CHARS = 512 * 1024;
export const SERVER_TYPES = new Set([
  "hello", "status", "samples", "beat", "feedback", "session_state", "calibration",
  "summary", "preview", "error", "pong",
]);

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const isNumOrNull = (v) => v === null || isNum(v);

// Per-type required-field checks. Unknown extra fields are ignored.
const VALIDATORS = {
  hello: (m) => typeof m.version === "string",
  status: (m) => typeof m.input === "object" && m.input !== null && typeof m.session_state === "string",
  samples: (m) => Array.isArray(m.points) && m.points.every((p) => Array.isArray(p) && p.length >= 3 && p.every(isNum)),
  beat: (m) => Number.isInteger(m.index) && isNum(m.t) && isNum(m.confidence) && isNum(m.amplitude)
    && (m.beat_in_bar === null || Number.isInteger(m.beat_in_bar)),
  feedback: (m) => typeof m.state === "string" && isNumOrNull(m.estimated_bpm) && isNum(m.target_bpm)
    && isNumOrNull(m.tempo_deviation_pct) && typeof m.similarity === "object" && Number.isInteger(m.beat_count),
  session_state: (m) => typeof m.state === "string" && typeof m.message === "string",
  calibration: (m) => typeof m.normalization === "object",
  summary: (m) => Number.isInteger(m.beat_count) && isNumOrNull(m.session_bpm),
  preview: (m) => typeof m.jpeg === "string" && m.jpeg.length < MAX_MESSAGE_CHARS,
  error: (m) => typeof m.code === "string" && typeof m.message === "string",
  pong: () => true,
};

/** Parse one server frame. Returns {ok:true, msg} or {ok:false, error}. Never throws. */
export function parseServerMessage(text) {
  if (typeof text !== "string") return { ok: false, error: "frame is not text" };
  if (text.length > MAX_MESSAGE_CHARS) return { ok: false, error: "frame too large" };
  let msg;
  try {
    msg = JSON.parse(text);
  } catch {
    return { ok: false, error: "invalid JSON" };
  }
  if (!msg || typeof msg !== "object" || Array.isArray(msg)) return { ok: false, error: "not an object" };
  if (msg.v !== PROTOCOL_VERSION) return { ok: false, error: `unsupported version ${msg.v}` };
  if (!SERVER_TYPES.has(msg.type)) return { ok: false, error: `unknown type ${msg.type}` };
  if (!Number.isInteger(msg.seq) || !isNum(msg.ts)) return { ok: false, error: "bad envelope" };
  if (!VALIDATORS[msg.type](msg)) return { ok: false, error: `invalid ${msg.type} payload` };
  return { ok: true, msg };
}

let seq = 0;
export function command(name, args = {}) {
  return JSON.stringify({ v: PROTOCOL_VERSION, type: "command", seq: ++seq, name, args });
}

export function samplesMessage(source, points) {
  return JSON.stringify({ v: PROTOCOL_VERSION, type: "samples", seq: ++seq, source, points });
}
