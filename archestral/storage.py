"""Local persistence: settings, arrangements and the instrument library.

Everything is plain JSON validated field-by-field before use. File names are
derived only from validated ids and are checked to stay inside the storage
directory (no path traversal). Writes are atomic (temp file + rename).
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis.config import config_from_dict

log = logging.getLogger("archestral.storage")

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PATH = ROOT / "library" / "instruments.json"
ARRANGEMENT_SCHEMA_VERSION = 1
MAX_FILE_BYTES = 256 * 1024
MAX_INSTRUMENTS = 48
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_UID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class ValidationError(ValueError):
    pass


def default_data_dir() -> Path:
    return Path(os.environ.get("ARCHESTRAL_DATA_DIR", ROOT / "data"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_json(path: Path) -> Any:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValidationError(f"{path.name} is larger than {MAX_FILE_BYTES} bytes")
    return json.loads(path.read_text(encoding="utf-8"))


def _num(v: Any, lo: float, hi: float, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValidationError(f"{name} must be a finite number")
    if not (lo <= v <= hi):
        raise ValidationError(f"{name}={v} outside [{lo}, {hi}]")
    return float(v)


def _text(v: Any, name: str, max_len: int = 80) -> str:
    if not isinstance(v, str):
        raise ValidationError(f"{name} must be a string")
    v = "".join(ch for ch in v if ch.isprintable()).strip()
    if not v:
        raise ValidationError(f"{name} must not be empty")
    return v[:max_len]


# ---------------------------------------------------------------------- library
def load_library(path: Path = LIBRARY_PATH) -> dict[str, Any]:
    lib = json.loads(path.read_text(encoding="utf-8"))
    validate_library(lib)
    return lib


def validate_library(lib: Any) -> None:
    if not isinstance(lib, dict) or lib.get("schema_version") != 1:
        raise ValidationError("library schema_version must be 1")
    stage = lib.get("stage")
    if not isinstance(stage, dict):
        raise ValidationError("library needs a stage definition")
    for k in ("half_width", "depth_front", "depth_back"):
        _num(stage.get(k), 0.5, 100, f"stage.{k}")
    seen = set()
    instruments = lib.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        raise ValidationError("library needs instruments")
    for inst in instruments:
        iid = inst.get("id")
        if not isinstance(iid, str) or not _ID_RE.match(iid) or iid in seen:
            raise ValidationError(f"bad or duplicate instrument id {iid!r}")
        seen.add(iid)
        arts = inst.get("articulations")
        if not isinstance(arts, list) or not arts:
            raise ValidationError(f"{iid}: articulations required")
        if inst.get("default_articulation") not in [a.get("id") for a in arts if a.get("supported")]:
            raise ValidationError(f"{iid}: default_articulation must be a supported articulation")


def library_index(lib: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["id"]: i for i in lib["instruments"]}


# ---------------------------------------------------------------------- arrangements
def validate_arrangement(doc: Any, lib: dict[str, Any]) -> dict[str, Any]:
    """Return a cleaned copy of an arrangement or raise ValidationError."""
    if not isinstance(doc, dict):
        raise ValidationError("arrangement must be an object")
    version = doc.get("schema_version")
    if version != ARRANGEMENT_SCHEMA_VERSION:
        raise ValidationError(f"unsupported arrangement schema_version {version!r}")
    aid = doc.get("id")
    if not isinstance(aid, str) or not _ID_RE.match(aid):
        raise ValidationError("arrangement id must be lowercase letters, digits and '-'")
    stage = lib["stage"]
    index = library_index(lib)
    out: dict[str, Any] = {
        "schema_version": ARRANGEMENT_SCHEMA_VERSION,
        "id": aid,
        "name": _text(doc.get("name"), "name"),
        "created_at": _text(doc.get("created_at", _now_iso()), "created_at", 40),
        "modified_at": _text(doc.get("modified_at", _now_iso()), "modified_at", 40),
    }
    audio = doc.get("audio", {})
    if not isinstance(audio, dict):
        raise ValidationError("audio must be an object")
    out["audio"] = {
        "master_gain": _num(audio.get("master_gain", 0.8), 0, 2, "audio.master_gain"),
        "reverb_mix": _num(audio.get("reverb_mix", 0.25), 0, 1, "audio.reverb_mix"),
        "tempo_bpm": _num(audio.get("tempo_bpm", 72), 30, 200, "audio.tempo_bpm"),
        "panning_model": audio.get("panning_model", "HRTF") if audio.get("panning_model", "HRTF") in
        ("HRTF", "equalpower") else _raise("audio.panning_model must be HRTF or equalpower"),
    }
    listener = doc.get("listener", {})
    if not isinstance(listener, dict) or listener.get("preset", "podium") not in ("podium", "audience", "camera"):
        raise ValidationError("listener.preset must be podium, audience or camera")
    out["listener"] = {"preset": listener.get("preset", "podium")}
    items = doc.get("instruments")
    if not isinstance(items, list):
        raise ValidationError("instruments must be a list")
    if len(items) > MAX_INSTRUMENTS:
        raise ValidationError(f"at most {MAX_INSTRUMENTS} instruments")
    uids = set()
    clean_items = []
    for n, it in enumerate(items):
        where = f"instruments[{n}]"
        if not isinstance(it, dict):
            raise ValidationError(f"{where} must be an object")
        uid = it.get("uid")
        if not isinstance(uid, str) or not _UID_RE.match(uid) or uid in uids:
            raise ValidationError(f"{where}.uid missing, invalid or duplicated")
        uids.add(uid)
        iid = it.get("instrument_id")
        if iid not in index:
            raise ValidationError(f"{where}: unknown instrument {iid!r}")
        definition = index[iid]
        pos = it.get("position")
        if not isinstance(pos, list) or len(pos) != 3:
            raise ValidationError(f"{where}.position must be [x, y, z]")
        x = _num(pos[0], -stage["half_width"], stage["half_width"], f"{where}.position.x")
        y = _num(pos[1], 0, 5, f"{where}.position.y")
        z = _num(pos[2], -stage["depth_back"], stage["depth_front"], f"{where}.position.z")
        supported = [a["id"] for a in definition["articulations"] if a.get("supported")]
        art = it.get("articulation", definition["default_articulation"])
        if art not in supported:
            raise ValidationError(f"{where}: articulation {art!r} not supported by {iid}")
        clean_items.append({
            "uid": uid,
            "instrument_id": iid,
            "position": [x, y, z],
            "rotation_y_deg": _num(it.get("rotation_y_deg", 0), -360, 360, f"{where}.rotation_y_deg"),
            "scale": _num(it.get("scale", 1), 0.25, 3, f"{where}.scale"),
            "gain": _num(it.get("gain", definition.get("default_gain", 0.8)), 0, 2, f"{where}.gain"),
            "muted": bool(it.get("muted", False)),
            "solo": bool(it.get("solo", False)),
            "articulation": art,
        })
    out["instruments"] = clean_items
    return out


def _raise(msg: str):
    raise ValidationError(msg)


class ArrangementStore:
    def __init__(self, root: Path, library: dict[str, Any]) -> None:
        self.root = Path(root).resolve()
        self.library = library
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, aid: str) -> Path:
        if not isinstance(aid, str) or not _ID_RE.match(aid):
            raise ValidationError("invalid arrangement id")
        path = (self.root / f"{aid}.json").resolve()
        if path.parent != self.root:
            raise ValidationError("invalid arrangement path")
        return path

    def list(self) -> list[dict[str, Any]]:
        out = []
        for path in sorted(self.root.glob("*.json")):
            entry = {"id": path.stem, "file": path.name}
            try:
                doc = validate_arrangement(_read_json(path), self.library)
                entry.update({"name": doc["name"], "modified_at": doc["modified_at"],
                              "instrument_count": len(doc["instruments"]), "valid": True})
            except (ValidationError, json.JSONDecodeError, OSError, KeyError, TypeError) as e:
                entry.update({"valid": False, "error": str(e)[:200]})
            out.append(entry)
        return out

    def get(self, aid: str) -> dict[str, Any]:
        path = self._path(aid)
        if not path.exists():
            raise FileNotFoundError(aid)
        try:
            return validate_arrangement(_read_json(path), self.library)
        except json.JSONDecodeError as e:
            raise ValidationError(f"file is not valid JSON: {e.msg}") from e

    def put(self, aid: str, doc: Any) -> dict[str, Any]:
        path = self._path(aid)
        if not isinstance(doc, dict):
            raise ValidationError("arrangement must be an object")
        doc = copy.deepcopy(doc)
        doc["id"] = aid
        if path.exists():
            try:
                doc["created_at"] = _read_json(path).get("created_at", _now_iso())
            except (ValueError, OSError):
                pass
        doc.setdefault("created_at", _now_iso())
        doc["modified_at"] = _now_iso()
        clean = validate_arrangement(doc, self.library)
        _atomic_write(path, json.dumps(clean, indent=2))
        log.info("arrangement saved id=%s instruments=%d", aid, len(clean["instruments"]))
        return clean

    def delete(self, aid: str) -> None:
        path = self._path(aid)
        if not path.exists():
            raise FileNotFoundError(aid)
        path.unlink()
        log.info("arrangement deleted id=%s", aid)


# ---------------------------------------------------------------------- settings
DEFAULT_SETTINGS: dict[str, Any] = {
    "schema_version": 1,
    "input_mode": "webcam",
    "camera_index": 0,
    "mirror_camera": True,
    "tracked_landmark": "wrist",
    "pattern": "4-4",
    "target_bpm": 90,
    "analysis": {},
    "audio": {"master_gain": 0.8, "metronome_gain": 0.6, "orchestra_gain": 0.7, "reference_metronome": False,
              "reverb_mix": 0.25, "panning_model": "HRTF"},
    "ui": {"first_run_done": False, "show_preview": True},
    "log_level": "INFO",
    "record_sessions": True,
}


def validate_settings(data: Any) -> tuple[dict[str, Any], list[str]]:
    """Merge untrusted settings onto defaults; invalid fields fall back with a message."""
    s = copy.deepcopy(DEFAULT_SETTINGS)
    problems: list[str] = []
    if not isinstance(data, dict):
        return s, ["settings file is not an object; defaults used"]

    def pick(key, ok, conv=lambda v: v):
        if key in data:
            if ok(data[key]):
                s[key] = conv(data[key])
            else:
                problems.append(f"invalid setting '{key}'; default kept")

    pick("input_mode", lambda v: v in ("webcam", "mouse", "webxr", "recorded"))
    pick("camera_index", lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 9)
    pick("mirror_camera", lambda v: isinstance(v, bool))
    pick("tracked_landmark", lambda v: v in ("wrist", "index_tip"))
    pick("pattern", lambda v: isinstance(v, str) and len(v) <= 32)
    pick("target_bpm", lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 20 <= v <= 300)
    pick("log_level", lambda v: v in ("DEBUG", "INFO", "WARNING", "ERROR"))
    pick("record_sessions", lambda v: isinstance(v, bool))
    if "analysis" in data:
        _, issues = config_from_dict(data["analysis"])
        if issues:
            problems += [f"analysis: {p}" for p in issues]
        if isinstance(data["analysis"], dict):
            cfg_keys = config_from_dict({})[0].to_dict()
            s["analysis"] = {k: v for k, v in data["analysis"].items()
                             if k in cfg_keys and not config_from_dict({k: v})[1]}
    for group, spec in (("audio", {"master_gain": (0, 2), "metronome_gain": (0, 2), "orchestra_gain": (0, 2),
                                   "reverb_mix": (0, 1)}),):
        g = data.get(group, {})
        if not isinstance(g, dict):
            problems.append(f"'{group}' must be an object")
            continue
        for k, (lo, hi) in spec.items():
            if k in g:
                try:
                    s[group][k] = _num(g[k], lo, hi, f"{group}.{k}")
                except ValidationError as e:
                    problems.append(str(e))
        if "reference_metronome" in g and isinstance(g["reference_metronome"], bool):
            s[group]["reference_metronome"] = g["reference_metronome"]
        if g.get("panning_model") in ("HRTF", "equalpower"):
            s[group]["panning_model"] = g["panning_model"]
    ui = data.get("ui", {})
    if isinstance(ui, dict):
        for k in ("first_run_done", "show_preview"):
            if isinstance(ui.get(k), bool):
                s["ui"][k] = ui[k]
    return s, problems


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.problems: list[str] = []
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return copy.deepcopy(DEFAULT_SETTINGS)
        try:
            data, self.problems = validate_settings(_read_json(self.path))
        except (ValueError, OSError) as e:
            backup = self.path.with_suffix(f".invalid-{int(time.time())}.json")
            try:
                self.path.replace(backup)
                self.problems = [f"settings file unreadable ({e}); moved to {backup.name}, defaults used"]
            except OSError:
                self.problems = [f"settings file unreadable ({e}); defaults used"]
            data = copy.deepcopy(DEFAULT_SETTINGS)
        for p in self.problems:
            log.warning("settings: %s", p)
        return data

    def update(self, patch: Any) -> tuple[dict[str, Any], list[str]]:
        if not isinstance(patch, dict):
            raise ValidationError("settings update must be an object")
        merged = copy.deepcopy(self.data)
        for k, v in patch.items():
            if k != "analysis" and isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
        clean, problems = validate_settings(merged)
        self.data = clean
        _atomic_write(self.path, json.dumps(clean, indent=2))
        return clean, problems
