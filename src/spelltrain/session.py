from __future__ import annotations
from pathlib import Path
import json
import threading
import time
import uuid
from collections import Counter
from .common import SCHEMA, annotation_valid, json_lines, read_json, write_json


class Session:
    def __init__(self, directory, subject=None, notes="", create=True):
        self.created_here = create
        self.directory = Path(directory)
        self.lock = threading.RLock()
        self.active = {}
        self.counts = Counter()
        if create:
            self.directory.mkdir(parents=True, exist_ok=False)
            self.meta = {"schema": SCHEMA, "id": self.directory.name, "subject": subject,
                         "side": "right", "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "origin_monotonic": time.monotonic(), "notes": notes, "synthetic": False,
                         "time_basis": "Mac monotonic seconds relative to session origin"}
            write_json(self.directory / "metadata.json", self.meta)
            write_json(self.directory / "annotations.json", [])
        else:
            self.meta = read_json(self.directory / "metadata.json")
        self.annotations = read_json(self.directory / "annotations.json")
        self.stream = (self.directory / "streams.jsonl").open("a", buffering=1)

    def now(self):
        return time.monotonic() - self.meta["origin_monotonic"]

    def append(self, row):
        with self.lock:
            self.stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
            self.counts[row["kind"]] += 1

    def annotate(self, row):
        row = annotation_valid({"id": uuid.uuid4().hex, **row})
        with self.lock:
            self.annotations = [a for a in self.annotations if a["id"] != row["id"]] + [row]
            self.annotations.sort(key=lambda a: a["start"])
            write_json(self.directory / "annotations.json", self.annotations)
        return row

    def delete(self, annotation_id):
        with self.lock:
            self.annotations = [a for a in self.annotations if a["id"] != annotation_id]
            write_json(self.directory / "annotations.json", self.annotations)

    def close(self):
        with self.lock:
            self.stream.close()
            if self.created_here:
                self.meta["recording_closed"] = True
                write_json(self.directory / "metadata.json", self.meta)


def load_session(directory):
    directory = Path(directory)
    meta = read_json(directory / "metadata.json")
    annotations = [annotation_valid(a) for a in read_json(directory / "annotations.json")]
    return meta, annotations, list(json_lines(directory / "streams.jsonl"))
