import json
import math

import pytest

from archestral.protocol import MAX_POINTS_PER_MESSAGE, Encoder, ProtocolError, decode_client
from archestral.storage import (ArrangementStore, SettingsStore, ValidationError, load_library,
                                validate_arrangement, validate_settings)
from archestral.tracking.recorded import RecordedSource

LIB = load_library()


# ----------------------------------------------------------------- protocol
def test_encode_envelope():
    enc = Encoder()
    a = json.loads(enc.encode("beat", {"index": 1, "t": 1.5}))
    b = json.loads(enc.encode("feedback", {"estimated_bpm": None}))
    assert a["v"] == 1 and a["type"] == "beat" and a["index"] == 1
    assert b["seq"] == a["seq"] + 1
    assert isinstance(a["ts"], float)
    with pytest.raises(ValueError):
        enc.encode("evil")
    with pytest.raises(ValueError):          # NaN is never emitted
        enc.encode("beat", {"x": math.nan})


def test_payload_cannot_override_envelope():
    msg = json.loads(Encoder().encode("beat", {"type": "hacked", "v": 99}))
    assert msg["type"] == "beat" and msg["v"] == 1


def test_decode_valid_messages():
    m = decode_client(json.dumps({"v": 1, "type": "command", "seq": 3, "name": "set_target_bpm",
                                  "args": {"bpm": 100}}))
    assert m.data == {"name": "set_target_bpm", "bpm": 100.0}
    m = decode_client(json.dumps({"v": 1, "type": "samples", "source": "mouse",
                                  "points": [[1.0, 0.5, 0.5], [1.1, 0.6, 0.4, 0.8]]}))
    assert m.data["points"][0] == [1.0, 0.5, 0.5, 1.0]
    m = decode_client(json.dumps({"v": 1, "type": "command", "name": "set_source",
                                  "args": {"source": "recorded", "fixture": "reference_90bpm"}}))
    assert m.data["fixture"] == "reference_90bpm"
    assert decode_client(b'{"v":1,"type":"ping"}').type == "ping"


@pytest.mark.parametrize("raw,code", [
    ("not json", "bad_json"),
    ("[1,2]", "bad_envelope"),
    ('{"v":2,"type":"ping"}', "bad_version"),
    ('{"v":1,"type":"exec"}', "unknown_type"),
    ('{"v":1,"type":"ping","seq":-1}', "bad_envelope"),
    ('{"v":1,"type":"command","name":"rm"}', "unknown_command"),
    ('{"v":1,"type":"command","name":"set_target_bpm","args":{"bpm":"fast"}}', "bad_args"),
    ('{"v":1,"type":"command","name":"set_target_bpm","args":{"bpm":1000}}', "bad_args"),
    ('{"v":1,"type":"command","name":"set_source","args":{"source":"recorded","fixture":"../../etc/passwd"}}',
     "bad_args"),
    ('{"v":1,"type":"command","name":"set_source","args":{"source":"webcam","camera":true}}', "bad_args"),
    ('{"v":1,"type":"samples","source":"webcam","points":[[0,0,0]]}', "bad_source"),
    ('{"v":1,"type":"samples","source":"mouse","points":[[0,0]]}', "bad_points"),
    ('{"v":1,"type":"samples","source":"mouse","points":[[0,0,0,2]]}', "bad_points"),
    ('{"v":1,"type":"samples","source":"mouse","points":[[0,"x",0]]}', "bad_points"),
    ('{"v":1,"type":"samples","source":"mouse","points":[]}', "bad_points"),
])
def test_decode_rejects_malformed(raw, code):
    with pytest.raises(ProtocolError) as e:
        decode_client(raw)
    assert e.value.code == code


def test_decode_size_limits():
    pts = [[i * 0.01, 0.5, 0.5] for i in range(MAX_POINTS_PER_MESSAGE + 1)]
    with pytest.raises(ProtocolError) as e:
        decode_client(json.dumps({"v": 1, "type": "samples", "source": "mouse", "points": pts}))
    assert e.value.code == "too_many_points"
    with pytest.raises(ProtocolError) as e:
        decode_client("x" * (70 * 1024))
    assert e.value.code == "too_large"


def test_nan_literal_rejected_in_points():
    with pytest.raises(ProtocolError):
        decode_client('{"v":1,"type":"samples","source":"mouse","points":[[NaN,0.5,0.5]]}')


# ----------------------------------------------------------------- arrangements
def arrangement(**over):
    doc = {"schema_version": 1, "id": "test-a", "name": "Test A",
           "instruments": [{"uid": "v1", "instrument_id": "violin", "position": [-2, 0, 0.5],
                            "rotation_y_deg": 15, "scale": 1, "gain": 0.7, "muted": False, "solo": False,
                            "articulation": "pizzicato"}]}
    doc.update(over)
    return doc


def test_arrangement_round_trip(tmp_path):
    store = ArrangementStore(tmp_path, LIB)
    saved = store.put("test-a", arrangement())
    loaded = store.get("test-a")
    assert loaded == saved
    assert loaded["instruments"][0]["articulation"] == "pizzicato"
    assert loaded["instruments"][0]["position"] == [-2.0, 0.0, 0.5]
    assert loaded["audio"]["panning_model"] == "HRTF"
    created = loaded["created_at"]
    again = store.put("test-a", arrangement(name="Renamed"))
    assert again["created_at"] == created and again["name"] == "Renamed"
    assert [e["id"] for e in store.list()] == ["test-a"]
    store.delete("test-a")
    assert store.list() == []


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.update(schema_version=99), "schema_version"),
    (lambda d: d["instruments"][0].update(instrument_id="kazoo"), "unknown instrument"),
    (lambda d: d["instruments"][0].update(articulation="col_legno"), "not supported"),
    (lambda d: d["instruments"][0].update(position=[50, 0, 0]), "position.x"),
    (lambda d: d["instruments"][0].update(gain=float("inf")), "gain"),
    (lambda d: d["instruments"].append(dict(d["instruments"][0])), "uid"),
    (lambda d: d.update(name=""), "name"),
    (lambda d: d.update(instruments="nope"), "instruments"),
])
def test_arrangement_validation_errors(mutate, msg):
    d = arrangement()
    mutate(d)
    with pytest.raises(ValidationError, match=msg):
        validate_arrangement(d, LIB)


def test_store_rejects_path_traversal(tmp_path):
    store = ArrangementStore(tmp_path / "arr", LIB)
    for bad in ("../evil", "a/b", "", "UPPER", ".hidden", "x" * 80):
        with pytest.raises(ValidationError):
            store.put(bad, arrangement())
    assert not (tmp_path / "evil.json").exists()


def test_invalid_files_fail_safely(tmp_path):
    store = ArrangementStore(tmp_path, LIB)
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "wrong.json").write_text(json.dumps(arrangement(id="wrong", schema_version=7)))
    listing = {e["id"]: e for e in store.list()}
    assert listing["broken"]["valid"] is False and listing["wrong"]["valid"] is False
    with pytest.raises(ValidationError):
        store.get("broken")
    with pytest.raises(FileNotFoundError):
        store.get("missing")


# ----------------------------------------------------------------- settings
def test_saved_20_bpm_target_is_reset(tmp_path):
    """An earlier UI bug saved 20 BPM; values outside 40..200 fall back to the default."""
    s, problems = validate_settings({"target_bpm": 20.0})
    assert s["target_bpm"] == 90 and problems


def test_settings_defaults_and_validation(tmp_path):
    s, problems = validate_settings({"target_bpm": 500, "camera_index": 2, "audio": {"reverb_mix": 3},
                                     "analysis": {"dip_ratio": 0.4, "bogus": 1}})
    assert s["target_bpm"] == 90 and s["camera_index"] == 2
    assert s["audio"]["reverb_mix"] == 0.25
    assert s["analysis"] == {"dip_ratio": 0.4}
    assert len(problems) == 3


def test_corrupt_settings_recovered(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{{{")
    store = SettingsStore(p)
    assert store.data["target_bpm"] == 90
    assert store.problems and "defaults used" in store.problems[0]
    store.update({"target_bpm": 110, "audio": {"master_gain": 0.5}})
    assert SettingsStore(p).data["target_bpm"] == 110
    assert SettingsStore(p).data["audio"]["metronome_gain"] == 0.6


# ----------------------------------------------------------------- recorded source
def test_recorded_source_replays_in_time_and_rejects_unknown():
    clock = [100.0]
    src = RecordedSource("reference_90bpm", clock=lambda: clock[0], loop=False)
    assert src.status()["test_input"] is True and "synthetic" in src.label
    src.start()
    assert len(src.poll()) == 1                  # only t=0 is due
    clock[0] += 1.0
    batch = src.poll()
    assert 59 <= len(batch) <= 61
    assert all(b.t >= 100.0 for b in batch)
    with pytest.raises(FileNotFoundError):
        RecordedSource("../settings")
