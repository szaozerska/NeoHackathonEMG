from __future__ import annotations
from collections import Counter
import platform
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import numpy as np
import joblib
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .common import STATE_LABELS, read_json, write_json
from .session import load_session
from .signals import SignalWindows, DEFAULT_SIGNAL


def emg_windows(rows, config=None):
    windows = SignalWindows(config)
    for row in rows:
        if row["kind"] != "emg":
            continue
        if row.get("gap"):
            windows.reset()
        count = len(row["samples"])
        fs = windows.config["sample_rate"]
        times = row["t"] - np.arange(count-1, -1, -1)/fs
        for feature in windows.feed(row["samples"], times):
            yield feature


def label_window(feature, annotations):
    verified = [a for a in annotations if a["verified"]]
    start, t = feature["start"], feature["t"]
    if feature["kind"] == "state":
        matches = [a for a in verified if a["label"] in STATE_LABELS and a["start"] <= start and t <= a["end"]]
        if len({a["label"] for a in matches}) == 1:
            return matches[0]["label"], matches[0]["trial_id"]
    else:
        snaps = [a for a in verified if a["label"] == "snap"]
        positive = [a for a in snaps if a["start"] <= t <= a["start"] + .09]
        if positive:
            return "snap", positive[0]["trial_id"]
        if any(start - .15 <= a["start"] <= t + .15 for a in snaps):
            return None
        matches = [a for a in verified if a["label"] in (*STATE_LABELS, "hard_negative", "background")
                   and a["start"] <= start and t <= a["end"]]
        if matches:
            return "negative", matches[0]["trial_id"]
    return None


def dataset(directories, signal=None):
    sets = {k: {"x": [], "y": [], "groups": [], "t": [], "session": []} for k in ("state", "snap")}
    identities, manifests = set(), []
    for directory in directories:
        meta, annotations, rows = load_session(directory)
        if meta.get("incomplete"):
            raise ValueError("Recording is marked incomplete due to capture failure: " + meta["id"])
        identities.add((meta["subject"], meta["side"], bool(meta.get("synthetic"))))
        manifests.append({"id": meta["id"], "path": str(Path(directory).resolve()),
                          "sha256": hashlib.sha256((Path(directory)/"streams.jsonl").read_bytes()).hexdigest(),
                          "annotations_sha256": hashlib.sha256((Path(directory)/"annotations.json").read_bytes()).hexdigest()})
        for feature in emg_windows(rows, signal):
            labeled = label_window(feature, annotations)
            if labeled is None:
                continue
            label, trial = labeled
            dest = sets[feature["kind"]]
            dest["x"].append(feature["x"])
            dest["y"].append(label)
            dest["groups"].append(meta["id"] + ":" + trial)
            dest["t"].append(feature["t"])
            dest["session"].append(meta["id"])
    if len(identities) != 1:
        raise ValueError("Use one subject/right side and do not mix real with synthetic sessions")
    for values in sets.values():
        for key in values:
            values[key] = np.asarray(values[key])
    return sets, identities.pop(), manifests


def unique_sessions(train, validation):
    if set(Path(p).resolve() for p in train) & set(Path(p).resolve() for p in validation):
        raise ValueError("Training and validation sessions must be disjoint")
    ids = [read_json(Path(p)/"metadata.json")["id"] for p in train + validation]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate session identities; record independent sessions")


def fit_models(train, validation, output, signal=None):
    if Path(output).exists():
        raise ValueError("Model output already exists; choose a new artifact version")
    unique_sessions(train, validation)
    config = DEFAULT_SIGNAL | (signal or {})
    tr, identity, manifest = dataset(train, config)
    va, other, val_manifest = dataset(validation, config)
    if identity != other:
        raise ValueError("Training and validation subject/side/synthetic identity mismatch")
    required = {"state": set(STATE_LABELS), "snap": {"snap", "negative"}}
    for kind in required:
        for name, data in (("training", tr), ("validation", va)):
            if not required[kind].issubset(set(data[kind]["y"])):
                raise ValueError(f"{name} needs verified {kind} labels {sorted(required[kind])}")
            for label in required[kind]:
                groups = set(data[kind]["groups"][data[kind]["y"] == label])
                if len(groups) < 2:
                    raise ValueError(f"{name}: collect at least two independent {label} trials; more recommended")
    candidates = {
        "lda": make_pipeline(StandardScaler(), LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto")),
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced", random_state=7)),
    }
    scores = {}
    for name, model in candidates.items():
        model.fit(tr["state"]["x"], tr["state"]["y"])
        scores[name] = float(f1_score(va["state"]["y"], model.predict(va["state"]["x"]), average="macro"))
    best = max(scores, key=scores.get)
    snap = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced", random_state=7))
    # Give independent trials similar influence, not thousands of overlapping windows.
    groups = Counter(tr["snap"]["groups"])
    weights = np.array([1/groups[g] for g in tr["snap"]["groups"]])
    weights *= len(weights)/weights.sum()
    snap.fit(tr["snap"]["x"], tr["snap"]["y"], logisticregression__sample_weight=weights)
    state = candidates[best]
    state_prob = state.predict_proba(va["state"]["x"])
    threshold_scores = {}
    for threshold in (.55, .65, .75, .85, .9):
        predicted = state.classes_[state_prob.argmax(axis=1)].copy()
        predicted[state_prob.max(axis=1) < threshold] = "none"
        threshold_scores[threshold] = float(f1_score(va["state"]["y"], predicted, average="macro"))
    state_threshold = max(threshold_scores, key=lambda k: (threshold_scores[k], k))
    # Select snap threshold by one-to-one event F1 on validation, including false events outside labels.
    from .evaluation import event_metrics
    event_scores = {}
    for threshold in (.55, .65, .75, .85, .9, .95):
        total = Counter()
        for directory in validation:
            _, ann, rows = load_session(directory)
            runner = PrimitivePredictor({"state_model": state, "snap_model": snap, "signal": config,
                                         "state_threshold": state_threshold, "snap_threshold": threshold})
            events = [p for p in runner.replay(rows) if p["kind"] == "snap"]
            metric = event_metrics([a["start"] for a in ann if a["verified"] and a["label"] == "snap"],
                                   [e["t"] for e in events], tolerance=.2)
            for key in ("tp", "fp", "fn"):
                total[key] += metric[key]
        denominator = 2*total["tp"] + total["fp"] + total["fn"]
        event_scores[threshold] = 2*total["tp"]/denominator if denominator else 0.
    snap_threshold = max(event_scores, key=lambda k: (event_scores[k], k))
    report = {"versions": {"python": platform.python_version(), **{name: version(name) for name in ("numpy", "scipy", "scikit-learn", "joblib")}},
              "subject": identity[0], "side": identity[1], "synthetic": identity[2],
              "state_candidates_validation_macro_f1": scores, "selected_state_model": best,
              "state_threshold": state_threshold, "snap_threshold": snap_threshold,
              "snap_validation_event_f1_by_threshold": event_scores,
              "state_validation": classification_report(va["state"]["y"], state.predict(va["state"]["x"]), output_dict=True, zero_division=0),
              "counts": {k: dict(Counter(tr[k]["y"])) for k in tr},
              "training_sessions": manifest, "validation_sessions": val_manifest,
              "warning": "Validation selected models/thresholds. Run evaluate on an independent test session. Synthetic scores do not measure hardware accuracy."}
    artifact = {"schema": 1, "state_model": state, "snap_model": snap, "signal": config,
                "state_threshold": state_threshold, "snap_threshold": snap_threshold, "report": report}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    joblib.dump(artifact, output/"model.joblib")
    write_json(output/"training-report.json", report)
    return report


class PrimitivePredictor:
    def __init__(self, artifact):
        self.artifact = artifact
        self.windows = SignalWindows(artifact["signal"])
        self.label, self.candidate, self.votes = "none", "none", 0
        self.last_state = -float("inf")
        self.last_snap = -float("inf")
        self.snap_rearmed = True
        self.snap_id = 0

    def reset(self):
        self.windows.reset()
        self.label, self.candidate, self.votes = "none", "none", 0
        self.snap_rearmed = False

    def feed(self, row):
        if row.get("gap"):
            self.reset()
        fs = self.windows.config["sample_rate"]
        times = row["t"] - np.arange(len(row["samples"])-1, -1, -1)/fs
        output = []
        for f in self.windows.feed(row["samples"], times):
            model = self.artifact[f["kind"] + "_model"]
            scores = model.predict_proba([f["x"]])[0]
            t = f["t"]
            if f["kind"] == "state":
                index = int(np.argmax(scores))
                score = float(scores[index])
                label = str(model.classes_[index]) if score >= self.artifact["state_threshold"] else "none"
                self.votes = self.votes + 1 if label == self.candidate else 1
                self.candidate = label
                # Opening is an explicit release signal; uncertainty is separately debounced.
                needed = 1 if label == "open" and self.label == "fist" else 2
                if self.votes >= needed:
                    self.label = label
                output.append({"kind": "state", "t": t, "label": self.label, "confidence": score})
                self.last_state = t
            else:
                score = float(scores[list(model.classes_).index("snap")])
                if score < .4:
                    self.snap_rearmed = True
                if score >= self.artifact["snap_threshold"] and self.snap_rearmed and t - self.last_snap >= .35:
                    self.last_snap, self.snap_rearmed = t, False
                    self.snap_id += 1
                    output.append({"kind": "snap", "t": t, "event_id": str(self.snap_id), "confidence": score})
        return output

    def replay(self, rows):
        for row in rows:
            if row["kind"] == "emg":
                yield from self.feed(row)


def load_artifact(path):
    path = Path(path)
    # joblib is pickle-based: only load locally trained/trusted models.
    return joblib.load(path/"model.joblib" if path.is_dir() else path)
