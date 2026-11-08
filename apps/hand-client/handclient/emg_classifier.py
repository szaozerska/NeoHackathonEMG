"""The classifier thread: turns the EMG stream into hand-sign predictions, off the Kinesis reader thread."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from spellgame import protocol as p

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


NEURAL_SIGNS = {"open": p.Sign.OPEN_PALM, "fist": p.Sign.FIST, "infinite_void": p.Sign.INFINITE_VOID}
"""Neural hand states the game has signs for; everything else (relaxed, unsure) is reported as none."""


class NeuralSignClassifier:
    """Runs a trained `spelltrain` neural bundle (hand-state model + snap detector) on the live EMG stream.

    A detected snap is reported as a momentary `snap`; the next hand-state reading follows it, so the server sees the
    rising edge into `snap` once per detection. Held states are reported on change and re-sent every `heartbeat_s`.
    """

    def __init__(self, model_dir: str | Path, heartbeat_s: float = 1.0, predictor: object | None = None) -> None:
        if predictor is None:
            from spelltrain.neural import NeuralEMGPredictor

            predictor = NeuralEMGPredictor(model_dir)
        self._predictor = predictor
        self._heartbeat_s = heartbeat_s
        self._sign: str | None = None
        self._sent_at = -float("inf")

    def push(self, batch: EmgBatch) -> SignPrediction | None:
        outputs = self._predictor.feed(  # type: ignore[attr-defined]
            {"source_seq": batch.sequence, "source_t": batch.band_timestamp_us, "samples": batch.samples.astype(float)}
        )
        snap = next((o for o in outputs if o["kind"] == "neural_event"), None)
        state = next((o for o in reversed(outputs) if o["kind"] == "neural_state"), None)
        if snap is not None:
            return self._report(batch.host_time_s, p.Sign.SNAP, snap["confidence"])
        if state is None:
            return None
        sign = NEURAL_SIGNS.get(state["label"], p.Sign.NONE)
        if sign != self._sign or batch.host_time_s - self._sent_at >= self._heartbeat_s:
            return self._report(batch.host_time_s, sign, state["confidence"])
        return None

    def _report(self, t: float, sign: str, confidence: float) -> SignPrediction:
        if sign != self._sign:
            log.info("neural sign: %s (%.2f)", sign, confidence)
        self._sign, self._sent_at = sign, t
        return SignPrediction(t, sign, float(confidence))


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
