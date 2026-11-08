"""Kinesis SSE adapter and source-verified upstream raw JSONL tailer."""
from __future__ import annotations
import json
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
import numpy as np
from .common import finite

DEFAULT_ADAPTER = {"type_path": "type", "emg_type": "emg", "samples_path": "samples",
                   "layout": "sample_major", "sequence_path": "sequence", "timestamp_path": "timestamp",
                   "uptime_path": None}
# Kinesis SensorStreamEvent schema 1: host_time_s is Mac monotonic receipt uptime.
KINESIS_STREAM_ADAPTER = {"type_path": "type", "emg_type": "emg", "samples_path": "payload.values",
                          "layout": "sample_major", "sequence_path": "payload.sequence",
                          "timestamp_path": "band_timestamp_us", "uptime_path": "host_time_s"}


def get_path(value, path, default=None):
    if not path:
        return default
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def sse_events(lines):
    event, data, size = "message", [], 0
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n") if isinstance(raw, bytes) else raw.rstrip("\r\n")
        if not line:
            if data:
                yield event, json.loads("\n".join(data))
            event, data, size = "message", [], 0
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
            size += len(line)
            if size > 1_000_000:
                raise ValueError("SSE event exceeds size limit")
    if data:
        yield event, json.loads("\n".join(data))


def normalize_sse(payload, event="message", config=None):
    c = DEFAULT_ADAPTER | (config or {})
    kind = get_path(payload, c["type_path"], event)
    if kind != c["emg_type"]:
        return None
    x = np.asarray(get_path(payload, c["samples_path"]), dtype=float)
    if c["layout"] == "channel_major":
        x = x.T
    elif c["layout"] == "flat":
        x = x.reshape(-1, 8)
    elif c["layout"] != "sample_major":
        raise ValueError("Unknown EMG layout")
    if x.ndim != 2 or x.shape[1] != 8 or not 1 <= len(x) <= 2048 or not np.isfinite(x).all():
        raise ValueError("EMG must have shape [samples, 8] with finite values")
    if np.any((x < 0) | (x > 65535)):
        raise ValueError("ADC counts must be unsigned 16-bit values")
    packet = {"samples": x.tolist(), "source_seq": get_path(payload, c["sequence_path"]),
              "source_t": get_path(payload, c["timestamp_path"])}
    if c["uptime_path"]:
        packet["source_uptime"] = finite(get_path(payload, c["uptime_path"]))
    return packet


def _varint(data, i):
    result = 0
    for shift in range(0, 70, 7):
        if i >= len(data):
            raise ValueError("Truncated protobuf")
        byte = data[i]
        i += 1
        result |= (byte & 127) << shift
        if byte < 128:
            return result, i
    raise ValueError("Invalid protobuf varint")


def decode_kinesis_raw(row):
    # Verified against callbacked/kinesis 5c78485, EMGReadings.swift and BandModel.swift.
    if row.get("kind") != "0x0200020a":
        return None
    data = bytes.fromhex(row["payload"])
    fields, i = {}, 0
    while i < len(data):
        tag, i = _varint(data, i)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            fields[number], i = _varint(data, i)
        elif wire == 2:
            size, i = _varint(data, i)
            if i + size > len(data):
                raise ValueError("Truncated protobuf field")
            fields[number], i = data[i:i+size], i + size
        else:
            raise ValueError("Unsupported raw EMG protobuf wire type")
    if len(fields.get(3, b"")) != 256 or 1 not in fields or 2 not in fields:
        raise ValueError("Expected Kinesis 16-sample eight-channel raw payload")
    x = np.frombuffer(fields[3], dtype="<u2").reshape(16, 8)
    return {"samples": x.tolist(), "source_seq": fields[1], "source_t": fields[2],
            "source_uptime": finite(row["uptime"])}


class BatchTimeline:
    """Preserve sequence gaps; timing remains explicitly receive-anchored unless uptime is verified."""
    def __init__(self, fs=2048):
        self.fs, self.last_end, self.last_seq = fs, None, None

    def align(self, packet, received, uptime_end=None):
        size = len(packet["samples"])
        seq = packet.get("source_seq")
        contiguous = self.last_seq is not None and seq is not None and int(seq) == int(self.last_seq) + 1
        if seq is None and self.last_seq is None and self.last_end is not None:
            contiguous = abs(received - (self.last_end + size/self.fs)) < .025
        if uptime_end is not None:
            end, basis = uptime_end, "kinesis_system_uptime"
        elif contiguous and self.last_end is not None and abs(received - (self.last_end + size/self.fs)) < .05:
            end, basis = self.last_end + size/self.fs, "sequence_receive_anchored"
        else:
            end, basis = received, "receive_anchored"
        gap = self.last_end is not None and (not contiguous or end <= self.last_end or end - self.last_end > (size + 2.5)/self.fs)
        self.last_end, self.last_seq = end, seq
        return {"t": end, "start": end - (size - 1)/self.fs, "timing": basis, "gap": bool(gap), **packet}


def read_sse(url, adapter, stop, callback, error):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Kinesis feed URL must be loopback HTTP")
    while not stop.is_set():
        try:
            request = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
            with urllib.request.urlopen(request, timeout=5) as stream:
                for event, payload in sse_events(stream):
                    if stop.is_set():
                        return
                    packet = normalize_sse(payload, event, adapter)
                    if packet is not None:
                        callback(packet)
        except Exception as exc:
            # urllib exceptions may contain the secret token; never stringify them.
            error("Kinesis feed disconnected or incompatible: " + type(exc).__name__ + "; check feed/token/adapter")
            stop.wait(1)


def tail_kinesis(filename, stop, callback, error):
    filename = Path(filename)
    # Allow the dashboard to start before the user chooses Kinesis's recording path.
    was_waiting = not filename.exists()
    while not filename.exists() and not stop.is_set():
        stop.wait(.1)
    if stop.is_set():
        return
    try:
        with open(filename) as stream:
            if not was_waiting:
                stream.seek(0, 2)  # Do not replay an old recording as new live data.
            while not stop.is_set():
                position = stream.tell()
                line = stream.readline()
                if not line.endswith("\n"):
                    stream.seek(position)
                    stop.wait(.02)
                    continue
                try:
                    packet = decode_kinesis_raw(json.loads(line))
                    if packet is not None:
                        callback(packet)
                except (ValueError, KeyError, TypeError) as exc:
                    error("Invalid raw Kinesis record: " + type(exc).__name__)
    except OSError:
        error("Could not open Kinesis raw recording file")
