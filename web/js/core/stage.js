// Stage geometry rules: bounds, grid snapping and minimum spacing. Pure module.

export function snap(value, step) {
  return step > 0 ? Math.round(value / step) * step : value;
}

/**
 * Check a proposed floor position for instrument `uid`.
 * Returns {ok:true} or {ok:false, reason}.
 */
export function checkPlacement(stage, instruments, uid, x, z, labelOf = (i) => i.instrument_id) {
  if (!Number.isFinite(x) || !Number.isFinite(z)) return { ok: false, reason: "Position is not a number." };
  if (Math.abs(x) > stage.half_width) return { ok: false, reason: "Outside the stage (left/right edge)." };
  if (z > stage.depth_front) return { ok: false, reason: "Too far forward: the front of the stage is reserved for the conductor." };
  if (z < -stage.depth_back) return { ok: false, reason: "Outside the stage (back wall)." };
  for (const other of instruments) {
    if (other.uid === uid) continue;
    const d = Math.hypot(other.position[0] - x, other.position[2] - z);
    if (d < stage.min_spacing) return { ok: false, reason: `Too close to ${labelOf(other)} (${d.toFixed(2)} m).` };
  }
  return { ok: true };
}

/** Nearest free grid position to (x, z), searching outward in rings. */
export function findFreeSpot(stage, instruments, x, z) {
  const step = stage.grid || 0.5;
  for (let r = 0; r <= 12; r++) {
    for (let dx = -r; dx <= r; dx++) {
      for (let dz = -r; dz <= r; dz++) {
        if (Math.max(Math.abs(dx), Math.abs(dz)) !== r) continue;
        const px = snap(x + dx * step, step);
        const pz = snap(z + dz * step, step);
        if (checkPlacement(stage, instruments, null, px, pz).ok) return [px, pz];
      }
    }
  }
  return null;
}

export function slugify(name) {
  const s = String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
  return s || "arrangement";
}

export function newId(name, now = Date.now()) {
  return `${slugify(name)}-${now.toString(36)}`.slice(0, 64);
}
