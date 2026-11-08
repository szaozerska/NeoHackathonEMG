"""Signal-quality filter for reserved validation captures (Spacebar-labelled collector format).

Writes `truth-values.filtered.json` (kept intervals, labels and timestamps unchanged) and `quality-filter.json`
(every decision with its reason). Raw streams and original labels are never modified. Decisions use only
signal-quality rules (stream resets, dropouts, ADC clipping, tap length, burst size) — no model predictions —
so the filtered labels stay valid for scoring a frozen model.

    python -m spelltrain.validation_filter "data/sophie/<capture>" [--rest-context TEXT]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy import signal

from .dataset_policy import require_usable_capture

FS = 2048
ADC_MIN, ADC_MAX = 100, 65435
"""Raw counts at or beyond these are treated as clipped (the band's ADC spans 0–65535)."""
MIN_INTERVAL_S = 0.25
"""Shorter Spacebar intervals are accidental taps, not actions."""
RESET_CLUSTER = (3, 5.0)
"""At least this many stream resets within this many seconds marks the band stream as unstable."""
UNSTABLE_GUARD_S = 2.0
CLIPPED_SHARE = 0.001
"""Intervals with more clipped samples than this stay for gesture scoring but not for tension: clipping caps strength."""
SNAP_PEAK_RATIO = 5.0
"""A snap interval's envelope peak must exceed this multiple of its own median."""
BURST_OF_SNAP = 0.5
"""Non-intended intervals whose peak exceeds this fraction of the median snap peak may hide an unlabelled action."""
ENVELOPE_S = 0.125
SETTLE_S = 0.25
FILTERS = (signal.butter(4, 20, btype="high", fs=FS, output="sos"),)
NOTCH = signal.iirnotch(60, 30, fs=FS)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def stream_path(directory: Path) -> Path:
    for p in (directory/"streams.jsonl", directory/"streams.jsonl.gz", directory/"original/streams.jsonl.gz"):
        if p.exists():
            return p
    raise FileNotFoundError(f"no streams.jsonl(.gz) in {directory}")


def load_stream(path: Path) -> dict:
    """EMG on the capture_t clock (band-timestamp mapped when available), sequence gaps and reset times."""
    opener = gzip.open if path.suffix == ".gz" else open
    times, seqs, batches, resets = [], [], [], []
    with opener(path, "rt") as f:
        for line in f:
            row = json.loads(line)
            if row.get("kind") == "stream_reset":
                resets.append(float(row["capture_t"]))
            if row.get("kind") != "emg":
                continue
            packet = row["packet"]
            mapped = (packet.get("timing") or {}).get("mapped_band_host_uptime_estimate")
            t = mapped - (row["host_uptime"] - row["capture_t"]) if mapped is not None and "host_uptime" in row else row["capture_t"]
            times.append(float(t))
            seqs.append(int(packet.get("source_seq", len(seqs))))
            batches.append(np.asarray(packet["samples"], dtype=np.float64))
    raw = np.concatenate(batches)
    per = len(batches[0])
    t = (np.asarray(times)[:, None] + np.arange(per)[None, :]/FS).ravel()
    seq = np.asarray(seqs)
    breaks = np.flatnonzero(np.diff(seq) != 1)
    edges = np.r_[0, (breaks+1)*per, len(raw)]
    filtered = np.full_like(raw, np.nan)
    for a, b in zip(edges[:-1], edges[1:]):
        seg = raw[a:b] - raw[a:b][:min(256, b-a)].mean(0)
        for sos in FILTERS:
            seg = signal.sosfilt(sos, seg, axis=0)
        seg = signal.lfilter(*NOTCH, seg, axis=0)
        seg[:int(SETTLE_S*FS)] = np.nan
        filtered[a:b] = seg
    k = int(ENVELOPE_S*FS)
    valid = np.isfinite(filtered).all(axis=1)
    power = np.where(valid[:, None], filtered, 0.0)**2
    power = power.mean(axis=1)
    envelope = np.sqrt(np.convolve(power, np.ones(k), "same") /
                       np.maximum(np.convolve(valid, np.ones(k), "same"), 1))
    envelope[~valid] = np.nan
    clipped = ((raw <= ADC_MIN) | (raw >= ADC_MAX)).any(axis=1)
    gaps = np.asarray(times)[breaks+1] if len(breaks) else np.array([])
    return {"t": t, "envelope": envelope, "clipped": clipped, "gaps": gaps, "resets": np.asarray(sorted(resets))}


def unstable_spans(resets: np.ndarray) -> list[tuple[float, float]]:
    count, window = RESET_CLUSTER
    spans: list[list[float]] = []
    for i in range(len(resets)-count+1):
        if resets[i+count-1] - resets[i] <= window:
            a, b = resets[i]-UNSTABLE_GUARD_S, resets[i+count-1]+UNSTABLE_GUARD_S
            if spans and a <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], b)
            else:
                spans.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in spans]


def decide(stream: dict, intervals: list[dict]) -> list[dict]:
    t, env, clipped = stream["t"], stream["envelope"], stream["clipped"]
    spans = unstable_spans(stream["resets"])
    in_span = lambda x: any(a < x <= b for a, b in spans)
    isolated = [r for r in stream["resets"] if not in_span(r)]
    dropouts = np.r_[stream["gaps"], isolated]

    def window(a, b):
        i0, i1 = np.searchsorted(t, [a, b])
        return env[i0:i1], clipped[i0:i1]

    motion = lambda iv: (iv.get("selected_motion") or {}).get("motion")
    snap_peaks = [np.nanmax(e) for iv in intervals if iv["label"] == "intended" and motion(iv) == "snap"
                  for e, _ in [window(iv["start"], iv["end"])] if np.isfinite(e).any()]
    snap_ref = float(np.median(snap_peaks)) if snap_peaks else None
    out = []
    for i, iv in enumerate(intervals):
        a, b = iv["start"], iv["end"]
        e, c = window(a, b)
        exclude, flags = [], []
        if any(x < b and a < y for x, y in spans):
            exclude.append("band stream unstable (reset cluster)")
        if b - a < MIN_INTERVAL_S:
            exclude.append("accidental tap (shorter than %.2f s)" % MIN_INTERVAL_S)
        if any(a < g < b for g in dropouts):
            exclude.append("stream dropout inside interval")
        if not np.isfinite(e).any():
            exclude.append("no usable signal")
        else:
            if iv["label"] == "intended" and motion(iv) == "snap" and np.nanmax(e) < SNAP_PEAK_RATIO*np.nanmedian(e):
                exclude.append("no snap peak")
            if iv["label"] == "non_intended" and snap_ref and np.nanmax(e) > BURST_OF_SNAP*snap_ref:
                exclude.append("snap-sized burst in non-intended time (possible unlabelled action)")
            if c.mean() > CLIPPED_SHARE:
                flags.append("ADC clipping")
        out.append({"index": i, "start": a, "end": b, "label": iv["label"], "motion": motion(iv),
                    "effort": (iv.get("selected_motion") or {}).get("effort"),
                    "decision": "excluded" if exclude else "kept", "reasons": exclude, "flags": flags,
                    "use_for_gesture": not exclude, "use_for_tension": not exclude and not flags})
    return out


def filter_capture(directory: Path, rest_context: str | None = None) -> dict:
    directory = Path(directory)
    require_usable_capture(directory)
    truth_path = directory/"truth-values.json"
    truth = json.loads(truth_path.read_text())
    raw_path = stream_path(directory)
    stream = load_stream(raw_path)
    decisions = decide(stream, truth["intervals"])
    kept = []
    for d, iv in zip(decisions, truth["intervals"]):
        if d["decision"] != "kept":
            continue
        row = dict(iv, original_index=d["index"], quality_flags=d["flags"], use_for_tension=d["use_for_tension"])
        if rest_context and iv["label"] == "non_intended":
            row["non_intended_context"] = rest_context
        kept.append(row)
    rules = {"min_interval_s": MIN_INTERVAL_S, "reset_cluster": {"count": RESET_CLUSTER[0], "within_s": RESET_CLUSTER[1],
             "guard_s": UNSTABLE_GUARD_S}, "adc_clip_counts": [ADC_MIN, ADC_MAX], "clipped_share_for_tension": CLIPPED_SHARE,
             "snap_peak_ratio": SNAP_PEAK_RATIO, "non_intended_burst_fraction_of_median_snap_peak": BURST_OF_SNAP,
             "envelope": "20 Hz 4th-order high-pass + 60 Hz notch, channel-mean RMS over %.3f s" % ENVELOPE_S}
    summary: dict = {}
    for d in decisions:
        key = d["motion"] or d["label"]
        s = summary.setdefault(key, {"intervals": 0, "kept": 0, "kept_seconds": 0.0, "kept_for_tension": 0})
        s["intervals"] += 1
        if d["decision"] == "kept":
            s["kept"] += 1
            s["kept_seconds"] = round(s["kept_seconds"] + d["end"] - d["start"], 2)
            s["kept_for_tension"] += d["use_for_tension"]
    report = {"schema": 1, "session_id": directory.name, "purpose": "reserved_validation", "do_not_train": True,
              "do_not_tune_thresholds": True, "method": "signal_quality_rules_only", "model_predictions_used": False,
              "labels_or_timestamps_changed": False, "inputs": {"truth-values.json": _sha256(truth_path),
              str(raw_path.relative_to(directory)): _sha256(raw_path)}, "rules": rules,
              "unstable_spans": unstable_spans(stream["resets"]), "summary": summary, "intervals": decisions}
    filtered = dict(truth, intervals=kept, cleanup_applied=True, filter_report="quality-filter.json",
                    note=truth.get("note", "") + " Filtered copy: signal-quality exclusions only; see quality-filter.json.")
    if rest_context:
        filtered["non_intended_context"] = rest_context
    (directory/"quality-filter.json").write_text(json.dumps(report, indent=1) + "\n")
    (directory/"truth-values.filtered.json").write_text(json.dumps(filtered, indent=1) + "\n")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("capture")
    p.add_argument("--rest-context", help="Describe what non-intended time contains, e.g. aggressive movement, not rest")
    args = p.parse_args(argv)
    report = filter_capture(Path(args.capture), args.rest_context)
    print(json.dumps({"unstable_spans": report["unstable_spans"], "summary": report["summary"]}, indent=1))


if __name__ == "__main__":
    main()
