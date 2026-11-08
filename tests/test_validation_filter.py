import json

import numpy as np
import pytest
from spelltrain.validation_filter import filter_capture

FS = 2048


def capture(tmp_path, resets=(), gap_at=None, clip_at=None, bursts=(20.0,)):
    rng = np.random.default_rng(0)
    rows, seq = [], 0
    n = int(40*FS/16)
    for i in range(n):
        t = i*16/FS
        x = rng.normal(0, 10, (16, 8))
        if 10 <= t < 13 or 25 <= t < 28:
            x *= 8
        if any(b <= t < b+0.03 for b in bursts):
            x *= 60
        if clip_at and clip_at <= t < clip_at+0.05:
            x[:, 0] = 40000
        seq += 1 + (5 if gap_at and abs(t-gap_at) < 8/FS else 0)
        rows.append({"kind": "emg", "capture_t": t, "packet": {"samples": (32768+x).tolist(), "source_seq": seq}})
    rows += [{"kind": "stream_reset", "capture_t": r} for r in resets]
    (tmp_path/"streams.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    iv = lambda a, b, motion=None, effort=None: {"start": a, "end": b, "label": "intended" if motion else "non_intended",
                                                 "selected_motion": {"motion": motion, "effort": effort} if motion else None}
    intervals = [iv(0, 9), iv(10, 13, "sword_hold", "high"), iv(14, 14.1), iv(19.5, 20.5, "snap"),
                 iv(21, 24), iv(25, 28, "shield_hold", "low"), iv(29, 39)]
    (tmp_path/"truth-values.json").write_text(json.dumps({"intervals": intervals}))
    return tmp_path


def by_index(report):
    return {d["index"]: d for d in report["intervals"]}


def test_quality_rules_exclude_bad_parts_and_keep_labels(tmp_path):
    d = capture(tmp_path, resets=(3, 4, 5), gap_at=26.0, clip_at=11.0)
    report = filter_capture(d, rest_context="aggressive movement, not rest")
    r = by_index(report)
    assert r[0]["reasons"] == ["band stream unstable (reset cluster)"]
    assert r[1]["decision"] == "kept" and r[1]["flags"] == ["ADC clipping"] and not r[1]["use_for_tension"]
    assert "accidental tap" in r[2]["reasons"][0]
    assert r[3]["decision"] == "kept" and r[3]["use_for_tension"]
    assert r[5]["reasons"] == ["stream dropout inside interval"]
    assert r[6]["decision"] == "kept"
    filtered = json.loads((d/"truth-values.filtered.json").read_text())
    original = json.loads((d/"truth-values.json").read_text())["intervals"]
    for row in filtered["intervals"]:
        src = original[row["original_index"]]
        assert (row["start"], row["end"], row["label"]) == (src["start"], src["end"], src["label"])
    assert all(row["non_intended_context"] for row in filtered["intervals"] if row["label"] == "non_intended")
    assert report["model_predictions_used"] is False and report["do_not_train"] is True


def test_snap_sized_burst_in_non_intended_time_is_excluded(tmp_path):
    d = capture(tmp_path, bursts=(20.0, 30.2))
    truth = json.loads((d/"truth-values.json").read_text())
    truth["intervals"][3] = {"start": 19.5, "end": 20.5, "label": "non_intended", "selected_motion": None}
    truth["intervals"].append({"start": 30, "end": 31, "label": "intended", "selected_motion": {"motion": "snap"}})
    (d/"truth-values.json").write_text(json.dumps(truth))
    r = by_index(filter_capture(d))
    assert "snap-sized burst" in r[3]["reasons"][0]
    assert r[7]["decision"] == "kept"


def test_rejected_capture_is_refused(tmp_path):
    d = capture(tmp_path)
    (d/"DO_NOT_USE.json").write_text("{}")
    with pytest.raises(ValueError, match="DO NOT USE"):
        filter_capture(d)
