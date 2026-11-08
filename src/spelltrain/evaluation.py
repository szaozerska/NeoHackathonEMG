from __future__ import annotations
from collections import Counter
from pathlib import Path
import numpy as np
from sklearn.metrics import classification_report, confusion_matrix
from .common import STATE_LABELS, write_json
from .fusion import SpellEngine, DEFAULT_MOTION, torso_coordinates
from .models import dataset, PrimitivePredictor
from .session import load_session


def event_metrics(expected, predicted, tolerance=.2):
    expected, predicted = sorted(expected), sorted(predicted)
    unmatched, errors = set(range(len(expected))), []
    for t in predicted:
        candidates = [i for i in unmatched if abs(t - expected[i]) <= tolerance]
        if candidates:
            index = min(candidates, key=lambda i: abs(t - expected[i]))
            unmatched.remove(index)
            errors.append(t - expected[index])
    tp, fp, fn = len(errors), len(predicted)-len(errors), len(unmatched)
    precision = tp/(tp+fp) if tp+fp else None
    recall = tp/(tp+fn) if tp+fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
            "signed_timing_errors_seconds": errors}


def replay(rows, artifact, motion=None):
    predictor, engine = PrimitivePredictor(artifact), SpellEngine(motion)
    events, primitives = [], []
    # Preserve receive order, including inference availability; never apply an EMG window before its batch arrived.
    for row in sorted(rows, key=lambda r: r.get("received", r["t"])):
        t = row.get("received", row["t"])
        events.extend(engine.expire(t))
        if row["kind"] == "emg":
            for p in predictor.feed(row):
                primitives.append(p)
                if p["kind"] == "state":
                    events.extend(engine.state(p["label"], t, p["confidence"]))
                else:
                    events.extend(engine.snap(t, p["event_id"]))
        elif row["kind"] == "pose":
            events.extend(engine.pose_sample(row["pose"], t, sample_t=row["t"]))
    if rows:
        events.extend(engine.expire(max(r.get("received", r["t"]) for r in rows) + .31))
    return events, primitives


def quality(directory):
    meta, annotations, rows = load_session(directory)
    emg = [r for r in rows if r["kind"] == "emg"]
    pose = [r for r in rows if r["kind"] == "pose"]
    duration = max((r.get("received", r["t"]) for r in rows), default=0)
    samples = np.concatenate([r["samples"] for r in emg]) if emg else np.empty((0, 8))
    return {"session": meta["id"], "subject": meta["subject"], "synthetic": meta.get("synthetic", False),
            "duration_seconds": duration, "emg_batches": len(emg), "emg_samples": len(samples),
            "received_sample_rate_over_session": len(samples)/duration if duration else 0,
            "emg_gaps": sum(bool(r.get("gap")) for r in emg),
            "adc_extreme_fraction": float(np.mean((samples == 0) | (samples == 65535))) if len(samples) else None,
            "channel_std": np.std(samples, axis=0).tolist() if len(samples) else [],
            "pose_frames": len(pose), "valid_hand_fraction": sum(bool(r["pose"]["hand"]["valid"]) for r in pose)/len(pose) if pose else None,
            "timing_modes": dict(Counter(r.get("timing", "unknown") for r in rows)),
            "verified_labels": dict(Counter(a["label"] for a in annotations if a["verified"])),
            "unverified_annotations": sum(not a["verified"] for a in annotations)}


def evaluate(directories, artifact, output, motion=None, allow_development=False):
    report = artifact["report"]
    used = {r["id"] for r in report["training_sessions"] + report["validation_sessions"]}
    motion = motion or DEFAULT_MOTION
    if motion.get("subject") not in (None, report["subject"]) or motion.get("side", "right") != report["side"] or motion.get("synthetic", report["synthetic"]) != report["synthetic"]:
        raise ValueError("Motion calibration identity differs from the model")
    used |= set(motion.get("calibration_sessions", []))
    for directory in directories:
        meta, _, _ = load_session(directory)
        if meta["id"] in used and not allow_development:
            raise ValueError("Evaluation session was used for training, validation or motion calibration. Use a fresh test session.")
        if (meta["subject"], meta["side"], bool(meta.get("synthetic"))) != (report["subject"], report["side"], report["synthetic"]):
            raise ValueError("Evaluation subject/side/synthetic identity mismatch")
    sets, _, _ = dataset(directories, artifact["signal"])
    state = sets["state"]
    state_report = None
    matrix = None
    if len(state["x"]):
        model = artifact["state_model"]
        scores = model.predict_proba(state["x"])
        predicted = model.classes_[scores.argmax(axis=1)].copy()
        predicted[scores.max(axis=1) < artifact["state_threshold"]] = "none"
        state_report = classification_report(state["y"], predicted, labels=list(STATE_LABELS), output_dict=True, zero_division=0)
        matrix = confusion_matrix(state["y"], predicted, labels=list(STATE_LABELS)).tolist()
    sessions = []
    all_events = []
    for directory in directories:
        meta, ann, rows = load_session(directory)
        events, primitives = replay(rows, artifact, motion)
        snap_predicted = [p["t"] for p in primitives if p["kind"] == "snap"]
        event_report = {}
        for name in ("snap", "shield_boost", "sword_cast", "sword_dismiss", "fireball_spawn", "fireball_throw"):
            expected = [a["start"] for a in ann if a["verified"] and a["label"] == name]
            predicted = snap_predicted if name == "snap" else [e["t"] for e in events if e["event"] == name]
            event_report[name] = event_metrics(expected, predicted, tolerance=.2 if name == "snap" else .4)
            event_report[name]["annotation_coverage_warning"] = "Predictions outside annotated events count as false positives; annotate the whole evaluation recording."
        backgrounds = [a for a in ann if a["verified"] and a["label"] == "background"]
        false_activations = [e for e in events if e["event"] in ("sword_cast", "shield_boost", "fireball_spawn", "fireball_throw")
                             and any(a["start"] <= e["t"] <= a["end"] for a in backgrounds)]
        duration = sum(a["end"]-a["start"] for a in backgrounds)
        sessions.append({"session": meta["id"], "quality": quality(directory), "events": event_report,
                         "background_false_activations": len(false_activations), "background_minutes": duration/60,
                         "false_activations_per_minute": len(false_activations)/(duration/60) if duration else None})
        all_events += [{"session": meta["id"], **e} for e in events]
    result = {"synthetic": report["synthetic"], "development_evaluation": allow_development,
              "state_label_order": STATE_LABELS, "state_confusion_matrix": matrix, "state": state_report,
              "sessions": sessions, "timing_note": "Events replayed in recorded receive order; annotate physical onset separately to measure latency. Receive-anchored EMG is approximate.",
              "limitation": "No physical accuracy claim from synthetic data; unannotated event classes have undefined recall."}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/"evaluation.json", result)
    with (output/"spell-events.jsonl").open("w") as stream:
        import json
        for e in all_events:
            stream.write(json.dumps(e) + "\n")
    return result


def calibrate_motion(directories, output):
    config, observations, hips, identities, session_ids = dict(DEFAULT_MOTION), [], [], set(), []
    for directory in directories:
        meta, ann, rows = load_session(directory)
        identities.add((meta["subject"], meta["side"], bool(meta.get("synthetic"))))
        session_ids.append(meta["id"])
        engine = SpellEngine()
        verified = [a for a in ann if a["verified"]]
        for row in rows:
            if row["kind"] != "pose":
                continue
            t, p = row["t"], row["pose"]
            engine.pose_sample(p, t)
            if engine.metrics:
                observations.append((engine.metrics, verified))
            if p["hand"]["valid"] and p["chest"]["valid"] and any(a["label"] == "hip_calibration" and a["start"] <= t <= a["end"] for a in verified):
                hips.append(torso_coordinates(np.asarray(p["hand"]["pos"])-p["chest"]["pos"], p["chest"]))
    if len(identities) != 1:
        raise ValueError("Motion calibration needs one subject/side/synthetic identity")
    if not hips:
        raise ValueError("Record and verify a hip_calibration interval with valid Quest hand/chest tracking")
    config["hip"] = np.median(hips, axis=0).tolist()
    config["hip_radius"] = float(np.clip(np.quantile(np.linalg.norm(hips - np.asarray(config["hip"]), axis=1), .95) + .12, .12, .3))
    summary = {"hip_samples": len(hips)}
    for event, key, metric, floor in (("shield_boost", "push_speed", "outward_speed", .3),
                                      ("shield_boost", "push_acceleration", "outward_acceleration", 1.),
                                      ("fireball_throw", "throw_speed", "speed", .5)):
        # Per-event peaks, so overlapping frames do not count as independent attempts.
        peaks = {}
        for obs, ann in observations:
            for a in ann:
                if a["label"] == event and abs(obs["t"] - a["start"]) <= .15:
                    peaks[a["id"]] = max(peaks.get(a["id"], 0), obs[metric])
        if len(peaks) < 3:
            raise ValueError(f"Need at least three verified {event} events with valid surrounding Quest motion")
        config[key] = max(floor, float(np.quantile(list(peaks.values()), .2)*.75))
        summary[key] = {"independent_events": len(peaks), "event_peaks": list(peaks.values())}
    identity = identities.pop()
    config.update({"subject": identity[0], "side": identity[1], "synthetic": identity[2],
                   "calibration_sessions": session_ids, "calibration_summary": summary,
                   "note": "Positive-example initial calibration; evaluate negatives on validation, then freeze before final test. Other parameters remain documented defaults."})
    if Path(output).exists():
        raise ValueError("Motion output already exists; choose a new path")
    write_json(output, config)
    return config
