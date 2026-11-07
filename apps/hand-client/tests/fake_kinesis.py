"""A stand-in for Kinesis's loopback SSE feed, serving schema-version-1 events like SensorStreamEvent.swift encodes."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TOKEN = "0123456789abcdef0123456789abcdef"


def event(kind: str, payload: dict[str, Any], sequence: int = 0, band_timestamp_us: int | None = None) -> str:
    body: dict[str, Any] = {
        "schema_version": 1,
        "type": kind,
        "stream_session_id": "session",
        "event_sequence": sequence,
        "host_time_s": 100.0 + sequence,
        "payload": payload,
    }
    if band_timestamp_us is not None:
        body["band_timestamp_us"] = band_timestamp_us
    return f"id: {sequence}\nevent: {kind}\ndata: {json.dumps(body)}\n\n"


def status(hand: str | None = "right", emg_active: bool = True) -> dict[str, Any]:
    return {
        "connected": True,
        "hand": hand,
        "emg_requested": True,
        "emg_active": emg_active,
        "emg_changing": False,
        "gyro_requested": True,
        "orientation_requested": True,
        "band_connection_id": "epoch-1",
        "model_capture_active": False,
    }


def hello(hand: str | None = "right") -> str:
    return event("hello", {"protocol": "kinesis.sensor-stream", "status": status(hand)})


def emg_configuration() -> str:
    return event(
        "emg_configuration",
        {
            "sample_rate_hz": 2048,
            "channels": 8,
            "adc_bits": 16,
            "samples_per_batch": 16,
            "encoding": 0,
            "supported": True,
            "units": "unsigned_adc_counts",
            "calibration": "unknown; no voltage conversion applied",
        },
    )


def emg(batch_sequence: int, value: int = 32768) -> str:
    return event(
        "emg",
        {
            "sequence": batch_sequence,
            "sample_rate_hz": 2048,
            "sample_interval_us": 488.28125,
            "channels": 8,
            "samples_per_batch": 16,
            "layout": "sample_major",
            "units": "unsigned_adc_counts",
            "values": [[value + channel for channel in range(8)] for _ in range(16)],
        },
        band_timestamp_us=batch_sequence * 7812,
    )


def gesture(sequence: int, finger: str, action: str, derived_action: str = "unknown", at_s: float = 0.0) -> str:
    return event(
        "gesture",
        {
            "sequence": sequence,
            "finger": finger,
            "action": action,
            "derived_action": derived_action,
            "synthetic": False,
            "received_at_s": at_s,
            "timestamp_us": sequence * 1000,
            "label": None,
        },
        band_timestamp_us=sequence * 1000,
    )


class FakeKinesis:
    """Streams every event in `events` to each reader, including ones `send` adds later, with keepalives between."""

    def __init__(self, events: list[str]) -> None:
        self.events = list(events)
        stopping = self._stopping = threading.Event()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                if self.path != f"/events?token={TOKEN}":
                    self.send_response(403)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b": connected\n\n")
                sent = 0
                while not stopping.wait(0.05):
                    pending = fake.events[sent:]
                    sent += len(pending)
                    self.wfile.write("".join(pending).encode() if pending else b": keepalive\n\n")
                    self.wfile.flush()

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_port}/events?token={TOKEN}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def send(self, *events: str) -> None:
        self.events.extend(events)

    def __enter__(self) -> FakeKinesis:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stopping.set()
        self._server.shutdown()
        self._server.server_close()
        time.sleep(0.05)
