"""Grip tension from raw EMG, scaled to each player's own range so strong and light grips play alike.

PLACEHOLDER: `emg_activation` guesses "how hard" from raw ADC counts (per-channel RMS around the batch mean) and the
thresholds below are untuned. Replace both once we know what the band / Kinesis actually exposes for tension (it may
already provide a filtered envelope or a force estimate). The calibration flow and per-player normalisation stay.

Calibration: relax the band hand (`REST_S`), then squeeze as hard as is comfortable (`SQUEEZE_S`). The relaxed level
is the median at rest; the comfortable maximum is `COMFORT_FRACTION` of the way to the squeeze's 95th percentile, so
nobody has to strain to reach 1. During play the maximum creeps up if a player keeps exceeding it (band shifts,
warming up), and the reading is smoothed over `SMOOTHING_S`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .kinesis_feed import EmgBatch

REST_S = 2.0
SQUEEZE_S = 3.0
COMFORT_FRACTION = 0.9
MIN_RANGE = 5.0
"""Squeeze minus rest activation (raw counts, PLACEHOLDER) below which calibration fails: the band isn't reading."""
SMOOTHING_S = 0.12
SEND_EVERY_S = 0.05
ADAPT_RATE = 0.02
"""Share of the overshoot the comfortable maximum moves up by per batch when a reading exceeds it."""


def emg_activation(samples: np.ndarray) -> float:
    """PLACEHOLDER muscle activation for one (samples, channels) batch of raw counts: mean per-channel RMS."""
    centred = samples.astype(np.float64) - samples.mean(axis=0, dtype=np.float64)
    return float(np.sqrt((centred**2).mean(axis=0)).mean())


@dataclass(frozen=True)
class TensionReading:
    t: float
    value: float
    """0 (relaxed) to 1 (comfortable maximum); may slightly exceed 1 before the maximum adapts."""
    calibrated: bool


@dataclass(frozen=True)
class CalibrationUpdate:
    t: float
    phase: str
    """`spellgame.protocol.CalibrationPhase`: rest, squeeze, done or failed."""
    progress: float


TensionItem = TensionReading | CalibrationUpdate


class TensionTracker:
    """Runs on the classifier thread: `push` each EMG batch, get readings and calibration progress to forward.

    `request_calibration` may be called from any thread (e.g. when the band pairs or a headset asks).
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock
        self._requested = False
        self._phase: str | None = None
        self._phase_start = 0.0
        self._samples: list[float] = []
        self._rest: float | None = None
        self._max: float | None = None
        self._smoothed: float | None = None
        self._last_time: float | None = None
        self._last_sent = float("-inf")
        self._last_progress = -1.0

    @property
    def calibrated(self) -> bool:
        return self._rest is not None and self._max is not None

    def request_calibration(self) -> None:
        self._requested = True

    def push(self, batch: EmgBatch) -> list[TensionItem]:
        now = self._clock() if self._clock is not None else batch.host_time_s
        activation = emg_activation(batch.samples)
        items: list[TensionItem] = []
        if self._requested:
            self._requested = False
            self._start_phase("rest", now)
        if self._phase is not None:
            items.extend(self._calibrate(activation, now))
        self._smooth(activation, now)
        if self._phase is None and now - self._last_sent >= SEND_EVERY_S:
            self._last_sent = now
            items.append(TensionReading(t=now, value=self._normalised(), calibrated=self.calibrated))
        return items

    def _start_phase(self, phase: str, now: float) -> None:
        self._phase = phase
        self._phase_start = now
        self._samples = []
        self._last_progress = -1.0

    def _calibrate(self, activation: float, now: float) -> list[TensionItem]:
        assert self._phase is not None
        duration = REST_S if self._phase == "rest" else SQUEEZE_S
        self._samples.append(activation)
        progress = min(1.0, (now - self._phase_start) / duration)
        items: list[TensionItem] = []
        if progress - self._last_progress >= 0.1 or progress >= 1.0:
            self._last_progress = progress
            items.append(CalibrationUpdate(t=now, phase=self._phase, progress=round(progress, 2)))
        if progress < 1.0:
            return items
        if self._phase == "rest":
            self._pending_rest = float(np.median(self._samples))
            self._start_phase("squeeze", now)
            items.append(CalibrationUpdate(t=now, phase="squeeze", progress=0.0))
            return items
        rest = self._pending_rest
        peak = float(np.percentile(self._samples, 95))
        self._phase = None
        if peak - rest < MIN_RANGE:
            items.append(CalibrationUpdate(t=now, phase="failed", progress=1.0))
            return items
        self._rest = rest
        self._max = rest + COMFORT_FRACTION * (peak - rest)
        items.append(CalibrationUpdate(t=now, phase="done", progress=1.0))
        return items

    def _smooth(self, activation: float, now: float) -> None:
        if self._smoothed is None or self._last_time is None:
            self._smoothed = activation
        else:
            alpha = 1.0 - float(np.exp(-max(0.0, now - self._last_time) / SMOOTHING_S))
            self._smoothed += (activation - self._smoothed) * alpha
        self._last_time = now
        if self._max is not None and self._phase is None and self._smoothed > self._max:
            self._max += (self._smoothed - self._max) * ADAPT_RATE

    def _normalised(self) -> float:
        if self._rest is None or self._max is None or self._smoothed is None:
            return 0.0
        return round(max(0.0, (self._smoothed - self._rest) / (self._max - self._rest)), 3)
