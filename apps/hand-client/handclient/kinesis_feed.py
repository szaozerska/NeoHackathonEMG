"""Kinesis's local sensor feed (Kinesis-Axo docs/sensor-stream.md, schema version 1): SSE on loopback.

Kinesis disconnects a reader whose queue holds a packet older than 1 s, so `KinesisFeed.run` only reads, parses and
hands events to `on_event`; anything slow belongs on another thread.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
EMG_SAMPLE_RATE_HZ = 2048
EMG_CHANNELS = 8
EMG_SAMPLES_PER_BATCH = 16
MAX_EVENT_BYTES = 512 * 1024
READ_TIMEOUT_S = 2.0
"""Kinesis sends a keepalive after 1 s of silence, so 2 s without a line means the feed is gone."""
RECONNECT_DELAY_S = 1.0


@dataclass(frozen=True)
class BandStatus:
    connected: bool
    hand: str | None
    """`left`/`right`: the wrist chosen on Kinesis's band page; None until one is chosen."""
    emg_active: bool
    band_connection_id: str | None
    """Changes on every band reconnect; EMG continuity only holds within one value."""


@dataclass(frozen=True)
class EmgBatch:
    sequence: int
    band_timestamp_us: int
    host_time_s: float
    samples: np.ndarray
    """(16 samples, 8 channels) uint16 raw ADC counts: uncentered, unfiltered."""


@dataclass(frozen=True)
class Orientation:
    band_timestamp_us: int
    host_time_s: float
    wxyz: tuple[float, float, float, float]
    """In the band's own frame; Kinesis applies no coordinate transform."""


@dataclass(frozen=True)
class BandGestureEvent:
    """One decoded message from the band's built-in gesture model, before any deduplication."""

    sequence: int
    timestamp_us: int
    host_time_s: float
    finger: str
    action: str
    derived_action: str
    synthetic: bool


FeedEvent = BandStatus | EmgBatch | Orientation | BandGestureEvent


class FeedRejected(Exception):
    """Kinesis refused the URL: the feed was stopped or restarted, which issues a new token."""


class FeedClosed(Exception):
    pass


def validate_feed_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parts.query)
    if not (
        parts.scheme == "http"
        and parts.hostname in ("127.0.0.1", "localhost")
        and parts.path == "/events"
        and list(query) == ["token"]
    ):
        raise ValueError("expected the http://127.0.0.1:8766/events?token=… URL from Kinesis's stream tab")
    return url


def parse_event(kind: str, data: str) -> FeedEvent | None:
    """Returns None for event types the hand-client doesn't use (gyro, EMG configuration once validated)."""
    event = json.loads(data)
    if event.get("schema_version") != SCHEMA_VERSION or event.get("type") != kind:
        raise ValueError(f"unsupported Kinesis event: schema {event.get('schema_version')!r}, type {kind!r}")
    payload: dict[str, Any] = event["payload"]
    match kind:
        case "hello":
            return _status(payload["status"])
        case "status":
            return _status(payload)
        case "emg_configuration":
            _require_supported_emg(payload)
            return None
        case "emg":
            return EmgBatch(
                sequence=payload["sequence"],
                band_timestamp_us=event["band_timestamp_us"],
                host_time_s=event["host_time_s"],
                samples=_emg_samples(payload["values"]),
            )
        case "orientation":
            w, x, y, z = payload["values"]
            return Orientation(event["band_timestamp_us"], event["host_time_s"], (w, x, y, z))
        case "gesture":
            return BandGestureEvent(
                sequence=payload["sequence"],
                timestamp_us=payload["timestamp_us"],
                host_time_s=payload["received_at_s"],
                finger=payload["finger"],
                action=payload["action"],
                derived_action=payload["derived_action"],
                synthetic=payload["synthetic"],
            )
        case "gyro":
            return None
    raise ValueError(f"unknown Kinesis event type {kind!r}")


def _status(fields: dict[str, Any]) -> BandStatus:
    return BandStatus(
        connected=fields["connected"],
        hand=fields["hand"],
        emg_active=fields["emg_active"],
        band_connection_id=fields["band_connection_id"],
    )


def _require_supported_emg(configuration: dict[str, Any]) -> None:
    observed = (
        configuration["supported"],
        configuration["sample_rate_hz"],
        configuration["channels"],
        configuration["samples_per_batch"],
    )
    if observed != (True, EMG_SAMPLE_RATE_HZ, EMG_CHANNELS, EMG_SAMPLES_PER_BATCH):
        raise ValueError(f"unsupported EMG format (supported, rate, channels, batch) = {observed}")


def _emg_samples(values: list[list[int]]) -> np.ndarray:
    samples = np.asarray(values, dtype=np.uint16)
    if samples.shape != (EMG_SAMPLES_PER_BATCH, EMG_CHANNELS):
        raise ValueError(f"EMG batch has shape {samples.shape}, expected ({EMG_SAMPLES_PER_BATCH}, {EMG_CHANNELS})")
    return samples


class SseParser:
    """Turns SSE lines into (event name, data) pairs; comments such as `: keepalive` yield nothing."""

    def __init__(self) -> None:
        self._kind = "message"
        self._data: list[str] = []

    def feed_line(self, line: str) -> tuple[str, str] | None:
        line = line.rstrip("\r\n")
        if not line:
            event = (self._kind, "\n".join(self._data)) if self._data else None
            self._kind, self._data = "message", []
            return event
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "event":
            self._kind = value
        elif field == "data":
            self._data.append(value)
        return None


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


class KinesisFeed:
    """Stays connected to the feed, reconnecting when it drops, until `stop` is set or Kinesis rejects the URL."""

    def __init__(self, url: str, on_event: Callable[[FeedEvent], None]) -> None:
        self._url = validate_feed_url(url)
        self._on_event = on_event
        # No proxy: the token in the URL must never leave this Mac.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirects())

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self._read_until_closed(stop)
            except urllib.error.HTTPError as exc:
                raise FeedRejected(
                    f"Kinesis rejected the stream URL (HTTP {exc.code}); copy a fresh one from its stream tab"
                ) from exc
            except (OSError, FeedClosed) as exc:
                log.warning("Kinesis feed unavailable (%s); retrying in %.0f s", exc, RECONNECT_DELAY_S)
                stop.wait(RECONNECT_DELAY_S)

    def _read_until_closed(self, stop: threading.Event) -> None:
        request = urllib.request.Request(self._url, headers={"Accept": "text/event-stream"})
        with self._opener.open(request, timeout=READ_TIMEOUT_S) as response:
            if response.headers.get_content_type() != "text/event-stream":
                raise ValueError(f"Kinesis feed returned {response.headers.get_content_type()}")
            log.info("connected to the Kinesis feed")
            parser = SseParser()
            while not stop.is_set():
                line = response.readline(MAX_EVENT_BYTES + 1)
                if not line:
                    raise FeedClosed("Kinesis closed the stream")
                if len(line) > MAX_EVENT_BYTES:
                    raise ValueError("Kinesis sent an oversized SSE line")
                parsed = parser.feed_line(line.decode())
                if parsed is None:
                    continue
                event = parse_event(*parsed)
                if event is not None:
                    self._on_event(event)
