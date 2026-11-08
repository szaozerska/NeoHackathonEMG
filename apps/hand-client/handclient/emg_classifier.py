"""The classifier thread: turns the EMG stream into hand-sign predictions, off the Kinesis reader thread."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .kinesis_feed import EMG_CHANNELS, EMG_SAMPLES_PER_BATCH, EmgBatch
from .tension import TensionItem, TensionTracker

log = logging.getLogger(__name__)

QUEUE_POLL_S = 0.5


@dataclass(frozen=True)
class SignPrediction:
    t: float
    sign: str
    confidence: float


class EmgClassifier(Protocol):
    def push(self, batch: EmgBatch) -> SignPrediction | None:
        """Consume one batch; return a prediction when the current sign changes or is due for a heartbeat."""
        ...


class EmgLogger:
    """Stand-in classifier until a model exists: logs EMG rate, sequence gaps and per-channel means once a second."""

    def __init__(self, report_every_s: float = 1.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._report_every_s = report_every_s
        self._clock = clock
        self._last_sequence: int | None = None
        self._reset(clock())

    def push(self, batch: EmgBatch) -> SignPrediction | None:
        if self._last_sequence is not None and batch.sequence != self._last_sequence + 1:
            self._gaps += 1
        self._last_sequence = batch.sequence
        self._batches += 1
        self._channel_sums += batch.samples.sum(axis=0, dtype=np.int64)
        now = self._clock()
        if now - self._window_start >= self._report_every_s:
            self._report(now)
        return None

    def _report(self, now: float) -> None:
        samples = self._batches * EMG_SAMPLES_PER_BATCH
        means = np.round(self._channel_sums / samples).astype(int).tolist() if samples else []
        log.info(
            "emg: %d batches (%.0f samples/s/channel), %d sequence gaps, channel means %s",
            self._batches,
            samples / (now - self._window_start),
            self._gaps,
            means,
        )
        self._reset(now)

    def _reset(self, now: float) -> None:
        self._window_start = now
        self._batches = 0
        self._gaps = 0
        self._channel_sums = np.zeros(EMG_CHANNELS, dtype=np.int64)


class ClassifierWorker:
    def __init__(
        self,
        batches: queue.Queue[EmgBatch],
        classifier: EmgClassifier,
        on_prediction: Callable[[SignPrediction | TensionItem], None],
        tension: TensionTracker | None = None,
    ) -> None:
        self._batches = batches
        self._classifier = classifier
        self._on_prediction = on_prediction
        self._tension = tension

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                batch = self._batches.get(timeout=QUEUE_POLL_S)
            except queue.Empty:
                continue
            prediction = self._classifier.push(batch)
            if prediction is not None:
                self._on_prediction(prediction)
            if self._tension is not None:
                for item in self._tension.push(batch):
                    self._on_prediction(item)
