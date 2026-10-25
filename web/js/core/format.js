// Display formatting. Missing values render as an em dash, never as a fake number.

export const DASH = "—";

export function fmt(v, digits = 0, suffix = "") {
  return v === null || v === undefined || !Number.isFinite(v) ? DASH : `${v.toFixed(digits)}${suffix}`;
}

export function signed(v, digits = 1, suffix = "") {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}${suffix}`;
}

export function duration(seconds) {
  if (!Number.isFinite(seconds)) return DASH;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
