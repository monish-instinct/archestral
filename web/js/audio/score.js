// A short original four-bar chorale (I - vi - IV - V in C major) used by both
// modes. Notes are [startBeat, durationBeats, midi, velocity]. Each instrument
// plays the part named in its library entry, shifted by its `octave`.

export const BEATS_PER_BAR = 4;
export const LOOP_BEATS = 16;

export const PARTS = {
  melody: [
    [0, 1, 76, 0.85], [1, 1, 79, 0.8], [2, 1, 76, 0.8], [3, 1, 72, 0.75],
    [4, 1, 69, 0.8], [5, 1, 72, 0.75], [6, 1, 76, 0.85], [7, 1, 72, 0.75],
    [8, 1, 77, 0.9], [9, 1, 76, 0.8], [10, 1, 74, 0.8], [11, 1, 72, 0.75],
    [12, 1, 74, 0.85], [13, 1, 71, 0.8], [14, 2, 67, 0.75],
  ],
  descant: [[0, 4, 67, 0.6], [4, 4, 64, 0.6], [8, 4, 69, 0.65], [12, 2, 71, 0.65], [14, 2, 74, 0.6]],
  tenor: [
    [0, 2, 64, 0.7], [2, 2, 67, 0.65], [4, 2, 64, 0.7], [6, 2, 60, 0.65],
    [8, 2, 65, 0.7], [10, 2, 69, 0.65], [12, 2, 62, 0.75], [14, 2, 59, 0.7],
  ],
  bass: [
    [0, 2, 60, 0.85], [2, 2, 55, 0.75], [4, 2, 57, 0.85], [6, 2, 64, 0.75],
    [8, 2, 53, 0.85], [10, 2, 60, 0.75], [12, 2, 55, 0.85], [14, 2, 62, 0.8],
  ],
  timpani: [
    [0, 1, 60, 0.9], [2, 1, 55, 0.5], [4, 1, 57, 0.85], [6, 1, 52, 0.5],
    [8, 1, 53, 0.85], [10, 1, 60, 0.5], [12, 2, 55, 0.95], [14, 2, 55, 0.7],
  ],
};

/** Notes of `part` that start on integer beat `beat` (0..LOOP_BEATS-1). */
export function notesAt(part, beat) {
  const notes = PARTS[part];
  if (!notes) return [];
  return notes.filter((n) => n[0] === beat);
}

/** Notes sounding (started at or before) a beat - used for reactive conductor chords. */
export function chordAt(beat) {
  const out = [];
  for (const part of ["tenor", "bass", "descant"]) {
    const n = PARTS[part].find((x) => x[0] <= beat && beat < x[0] + x[1]);
    if (n) out.push({ part, midi: n[2], vel: n[3] });
  }
  return out;
}
