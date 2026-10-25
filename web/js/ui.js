// Small DOM helpers: element lookup, toasts, modal dialogs, event log.
import { escapeHtml } from "./core/format.js";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c instanceof Node ? c : String(c));
  return node;
}

export function toast(message, kind = "info", ms = 3800) {
  const t = el("div", { class: `toast ${kind}`, role: "status" }, message);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), ms);
  logEvent(message, kind === "bad" ? "bad" : kind === "warn" ? "warn" : "");
}

// --- event log shown in Diagnostics (bounded) ------------------------------
const LOG_MAX = 200;
export const eventLog = [];
const lastByKey = new Map();
export function logEvent(message, level = "", rateKey = null, intervalMs = 5000) {
  if (rateKey) {
    const now = performance.now();
    if (now - (lastByKey.get(rateKey) || -Infinity) < intervalMs) return;
    lastByKey.set(rateKey, now);
  }
  eventLog.push({ time: new Date(), message, level });
  if (eventLog.length > LOG_MAX) eventLog.shift();
}

// --- modal ------------------------------------------------------------------
export function modal({ title, body = "", okLabel = "OK", cancelLabel = "Cancel", danger = false, wide = false }) {
  const dlg = $("#modal");
  $("#modal-title").textContent = title;
  const bodyEl = $("#modal-body");
  bodyEl.replaceChildren();
  if (typeof body === "string") bodyEl.append(el("p", {}, body));
  else bodyEl.append(body);
  const ok = $("#modal-ok");
  ok.textContent = okLabel;
  ok.className = `btn ${danger ? "danger" : "primary"}`;
  const cancel = $("#modal-cancel");
  cancel.hidden = cancelLabel === null;
  cancel.textContent = cancelLabel || "";
  dlg.style.width = wide ? "760px" : "";
  return new Promise((resolve) => {
    dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok"), { once: true });
    dlg.returnValue = "cancel";
    dlg.showModal();
    const input = bodyEl.querySelector("input");
    (input || ok).focus();
  });
}

export const confirmAction = (title, text, okLabel = "Delete") =>
  modal({ title, body: text, okLabel, danger: true });

export async function promptText(title, label, initial = "") {
  const input = el("input", { type: "text", value: initial, maxlength: "80", "aria-label": label });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $("#modal").close("ok"); }
  });
  const wrap = el("div", {}, el("label", { class: "field-label" }, label), input);
  const ok = await modal({ title, body: wrap, okLabel: "Save" });
  const v = input.value.trim();
  return ok && v ? v : null;
}

export function setChip(id, state, title) {
  const chip = document.getElementById(id);
  chip.classList.remove("ok", "warn", "bad");
  if (state) chip.classList.add(state);
  if (title) chip.title = title;
}

export function kv(dl, rows) {
  dl.innerHTML = rows.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v ?? "—")}</dd>`).join("");
}

export function setupCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.round(r.width * dpr));
  const h = Math.max(1, Math.round(r.height * dpr));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: r.width, h: r.height };
}
