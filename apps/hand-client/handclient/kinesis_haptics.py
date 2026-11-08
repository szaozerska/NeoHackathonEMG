"""Buzzes the band through Kinesis's `POST /haptics?token=…&ms=…`, served next to the sensor feed.

Runs on its own thread so a slow request never holds up the asyncio loop or the feed reader.
"""

from __future__ import annotations

import logging
import queue
import threading
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

QUEUE_POLL_S = 0.2
REQUEST_TIMEOUT_S = 2.0


def haptics_url(feed_url: str, duration_ms: int) -> str:
    """The feed's `…/events?token=T` becomes `…/haptics?token=T&ms=N`, with the same token."""
    parts = urllib.parse.urlsplit(feed_url)
    query = urllib.parse.urlencode({"token": urllib.parse.parse_qs(parts.query)["token"][0], "ms": duration_ms})
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/haptics", query, ""))


class HapticsWorker:
    def __init__(self, feed_url: str, durations_ms: queue.Queue[int]) -> None:
        self._feed_url = feed_url
        self._durations_ms = durations_ms

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                duration_ms = self._durations_ms.get(timeout=QUEUE_POLL_S)
            except queue.Empty:
                continue
            self._buzz(duration_ms)

    def _buzz(self, duration_ms: int) -> None:
        """A failed buzz is dropped with a warning: missing one must not stop the hand client."""
        request = urllib.request.Request(haptics_url(self._feed_url, duration_ms), data=b"", method="POST")
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S):
                log.debug("haptic %d ms", duration_ms)
        except OSError as exc:
            log.warning("Kinesis rejected a %d ms haptic (%s); does this Kinesis build serve POST /haptics?", duration_ms, exc)
