// WebSocket connection to the local service with validation and reconnect.
import { command, parseServerMessage, samplesMessage } from "./core/protocol.js";
import { logEvent } from "./ui.js";

export class ServiceLink extends EventTarget {
  constructor(url) {
    super();
    this.url = url;
    this.ws = null;
    this.state = "connecting";      // connecting | open | closed
    this.lastMessageAt = null;
    this.serverInfo = null;
    this.invalidCount = 0;
    this._retry = 500;
    this._outbox = [];
    this.connect();
  }

  connect() {
    this._setState("connecting");
    let ws;
    try {
      ws = new WebSocket(this.url);
    } catch (e) {
      this._scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this._retry = 500;
      this._setState("open");
      logEvent("Connected to analysis service");
      for (const m of this._outbox.splice(0)) ws.send(m);
    };
    ws.onmessage = (ev) => {
      this.lastMessageAt = performance.now();
      const res = parseServerMessage(ev.data);
      if (!res.ok) {
        this.invalidCount++;
        logEvent(`Ignored invalid message: ${res.error}`, "warn", "invalid-msg");
        return;
      }
      if (res.msg.type === "hello") this.serverInfo = res.msg;
      this.dispatchEvent(new CustomEvent(res.msg.type, { detail: res.msg }));
      this.dispatchEvent(new CustomEvent("message", { detail: res.msg }));
    };
    ws.onclose = () => {
      if (this.state === "open") logEvent("Service connection lost; reconnecting", "bad");
      this._setState("closed");
      this._scheduleReconnect();
    };
    ws.onerror = () => {};
  }

  _scheduleReconnect() {
    clearTimeout(this._timer);
    this._timer = setTimeout(() => this.connect(), this._retry);
    this._retry = Math.min(5000, this._retry * 1.6);
  }

  _setState(s) {
    this.state = s;
    this.dispatchEvent(new CustomEvent("connection", { detail: s }));
  }

  _send(text, queueIfClosed) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(text);
      return true;
    }
    if (queueIfClosed && this._outbox.length < 20) this._outbox.push(text);
    return false;
  }

  command(name, args = {}) {
    return this._send(command(name, args), true);
  }

  // Live samples are never queued: stale movement data is worse than none.
  samples(source, points) {
    return this._send(samplesMessage(source, points), false);
  }
}
