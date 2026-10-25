// REST helpers for the local service. Errors carry the server's message.

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error("The local service is not reachable. Is `python -m archestral` still running?");
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) throw new Error((data && data.error) || `${method} ${path} failed (${res.status})`);
  return data;
}

export const api = {
  capabilities: () => request("GET", "/api/capabilities"),
  settings: () => request("GET", "/api/settings"),
  saveSettings: (patch) => request("PUT", "/api/settings", patch),
  patterns: () => request("GET", "/api/patterns"),
  fixtures: () => request("GET", "/api/fixtures"),
  library: () => request("GET", "/api/library"),
  arrangements: () => request("GET", "/api/arrangements"),
  arrangement: (id) => request("GET", `/api/arrangements/${encodeURIComponent(id)}`),
  saveArrangement: (id, doc) => request("PUT", `/api/arrangements/${encodeURIComponent(id)}`, doc),
  deleteArrangement: (id) => request("DELETE", `/api/arrangements/${encodeURIComponent(id)}`),
};
