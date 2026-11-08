from __future__ import annotations
import json
import math
from pathlib import Path
import numpy as np

SCHEMA = 1
STATE_LABELS = ("open", "fist", "none")
EVENT_LABELS = ("snap", "shield_boost", "sword_cast", "sword_dismiss", "fireball_spawn", "fireball_throw", "fireball_equipped", "fireball_primed", "fireball_ready", "fireball_cancel")
INTERVAL_LABELS = STATE_LABELS + ("hard_negative", "shield", "sword", "fireball", "background", "hip_calibration")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


def json_lines(path):
    with Path(path).open() as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid JSON line {number} in {Path(path).name}") from exc


def vector(value, length=3):
    result = np.asarray(value, dtype=float)
    if result.shape != (length,) or not np.isfinite(result).all():
        raise ValueError(f"Expected {length} finite coordinates")
    return result


def unit(value):
    result = vector(value)
    norm = np.linalg.norm(result)
    if norm < 1e-8:
        raise ValueError("Zero direction")
    return result / norm


def finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Expected a finite number")
    return value


def annotation_valid(row):
    if row.get("label") not in INTERVAL_LABELS + EVENT_LABELS:
        raise ValueError("Unknown annotation label")
    start, end = finite(row["start"]), finite(row["end"])
    if start < 0 or end < start:
        raise ValueError("Annotation bounds must satisfy 0 <= start <= end")
    if row["label"] in EVENT_LABELS and end != start:
        raise ValueError("Events must have equal start/end timestamps")
    if row["label"] in INTERVAL_LABELS and end <= start:
        raise ValueError("Intervals must have positive duration")
    if not row.get("trial_id"):
        raise ValueError("A trial_id is required")
    return {"id": str(row["id"]), "label": row["label"], "start": start, "end": end,
            "trial_id": str(row["trial_id"]), "verified": row.get("verified") is True,
            "notes": str(row.get("notes", ""))[:2000]}
