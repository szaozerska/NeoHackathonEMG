"""Grip tension from raw EMG, scaled to each player's own comfortable clench so strong and light grips play alike.

Signal: each channel is high-passed (20 Hz) and notched (60 Hz mains), then its RMS over the last `WINDOW_S` is the
channel's envelope. Recordings of two players put relaxed hands at ~10 counts and holds at ~25–140, so the absolute
level means nothing across people; only the rise over that player's own calibration does.

Calibration (about 8 s): relax (`REST_S`), then make a fist at a comfortably firm ~70% (`FIST_S`), then hold the
shield hand palm out, also ~70% (`PALM_S`). The first `SETTLE_S` of each step is skipped. Fist and open palm use
different muscles (in the recordings the palm drives channels 6–8, the fist 2–3), so each pose keeps its own
per-channel weights: how much each channel rose during that hold. Live, the pose whose channel pattern matches best
is scored as `COMFORT_LEVEL` × (weighted rise now) / (weighted rise during its hold), so a calibration-strength
clench reads 0.7, relaxed reads 0, and harder than comfortable goes up to `MAX_VALUE`.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .kinesis_feed import EMG_CHANNELS, EMG_SAMPLE_RATE_HZ, EMG_SAMPLES_PER_BATCH, EmgBatch

REST_S = 2.0
FIST_S = 3.0
PALM_S = 3.0
SETTLE_S = 0.5
"""Skipped at the start of each calibration step while the player gets into the pose."""
COMFORT_LEVEL = 0.7
"""The tension a calibration-strength ("comfortably firm") clench reads as."""
MAX_VALUE = 1.2
MIN_RISE = 4.0
"""Envelope rise over rest (filtered counts) below which a calibration hold fails: the band isn't reading the pose.
Relaxed hands sit at ~10 counts; the lightest recorded hold (a light fist) rose ~15."""
WINDOW_S = 0.125
SMOOTHING_S = 0.12
SEND_EVERY_S = 0.05

STEPS = (("rest", REST_S), ("squeeze", FIST_S), ("palm", PALM_S))
"""Calibration steps as `spellgame.protocol.CalibrationPhase` values (squeeze = the fist)."""


def _biquad(kind: str, freq: float, q: float) -> tuple[np.ndarray, np.ndarray]:
    """RBJ cookbook high-pass or notch, normalised so a[0] = 1."""
    w = 2.0 * math.pi * freq / EMG_SAMPLE_RATE_HZ
    alpha = math.sin(w) / (2.0 * q)
    cos = math.cos(w)
    if kind == "highpass":
        b = np.array([(1 + cos) / 2, -(1 + cos), (1 + cos) / 2])
    else:
        b = np.array([1.0, -2.0 * cos, 1.0])
    a = np.array([1.0 + alpha, -2.0 * cos, 1.0 - alpha])
    return b / a[0], a / a[0]


FILTERS = (_biquad("highpass", 20.0, 0.54), _biquad("highpass", 20.0, 1.31), _biquad("notch", 60.0, 30.0))
"""4th-order Butterworth high-pass at 20 Hz (two biquads) removes drift and movement; the notch removes mains hum."""


class EmgEnvelope:
    """Streaming per-channel envelope: filtered RMS over the last `WINDOW_S`."""

    def __init__(self) -> None:
        self._state = np.zeros((len(FILTERS), 2, EMG_CHANNELS))
        self._squares: deque[np.ndarray] = deque(
            maxlen=max(1, round(WINDOW_S * EMG_SAMPLE_RATE_HZ / EMG_SAMPLES_PER_BATCH))
        )
        self._offset: np.ndarray | None = None

    def push(self, samples: np.ndarray) -> np.ndarray:
        x = samples.astype(np.float64)
        if self._offset is None:
            self._offset = x.mean(axis=0)
        x = x - self._offset
        for i, (b, a) in enumerate(FILTERS):
            z = self._state[i]
            y = np.empty_like(x)
            for n in range(len(x)):  # transposed direct form II
                y[n] = b[0] * x[n] + z[0]
                z[0] = b[1] * x[n] - a[1] * y[n] + z[1]
                z[1] = b[2] * x[n] - a[2] * y[n]
            x = y
        self._squares.append((x**2).mean(axis=0))
        return np.sqrt(np.mean(self._squares, axis=0))


@dataclass(frozen=True)
class PoseReference:
    weights: np.ndarray
    """Per-channel rise over rest during this pose's hold, normalised to sum 1."""
    rise: float
    """Weighted rise during the hold: what reads as `COMFORT_LEVEL`."""


@dataclass(frozen=True)
class TensionReading:
    t: float
    value: float
    """0 (relaxed) to `MAX_VALUE`; `COMFORT_LEVEL` = the clench strength used in calibration."""
    calibrated: bool
    pose: str | None = None
    """"fist" or "palm": the pose whose channel pattern matches best (None when relaxed or uncalibrated)."""
    fist: float | None = None
    """Tension against the fist calibration alone (the sword), whatever pose is held; None until calibrated."""
    palm: float | None = None
    """Tension against the shield-hand calibration alone; None until calibrated or if that step didn't register."""


@dataclass(frozen=True)
class CalibrationUpdate:
    t: float
    phase: str
    """`spellgame.protocol.CalibrationPhase`: rest, squeeze (fist), palm, done or failed."""
    progress: float


TensionItem = TensionReading | CalibrationUpdate


class TensionTracker:
    """Runs on the classifier thread: `push` each EMG batch, get readings and calibration progress to forward.

    `request_calibration` may be called from any thread (e.g. when the band pairs or a headset asks).
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock
        self._envelope = EmgEnvelope()
        self._requested = False
        self._step: int | None = None
        self._step_start = 0.0
        self._held: list[np.ndarray] = []
        self._pending: dict[str, np.ndarray] = {}
        self._rest: np.ndarray | None = None
        self._poses: dict[str, PoseReference] = {}
        self._smoothed = 0.0
        self._smoothed_poses: dict[str, float] = {}
        self._pose: str | None = None
        self._last_time: float | None = None
        self._last_sent = float("-inf")
        self._last_progress = -1.0

    @property
    def calibrated(self) -> bool:
        return self._rest is not None and bool(self._poses)

    def request_calibration(self) -> None:
        self._requested = True

    def push(self, batch: EmgBatch) -> list[TensionItem]:
        now = self._clock() if self._clock is not None else batch.host_time_s
        envelope = self._envelope.push(batch.samples)
        items: list[TensionItem] = []
        if self._requested:
            self._requested = False
            self._pending = {}
            items.extend(self._start_step(0, now))
        if self._step is not None:
            items.extend(self._calibrate(envelope, now))
        self._smooth(envelope, now)
        if self._step is None and now - self._last_sent >= SEND_EVERY_S:
            self._last_sent = now
            per_pose = {pose: round(value, 3) for pose, value in self._smoothed_poses.items()}
            items.append(
                TensionReading(
                    t=now,
                    value=round(self._smoothed, 3),
                    calibrated=self.calibrated,
                    pose=self._pose,
                    fist=per_pose.get("fist"),
                    palm=per_pose.get("palm"),
                )
            )
        return items

    def _start_step(self, step: int, now: float) -> list[TensionItem]:
        self._step = step
        self._step_start = now
        self._held = []
        self._last_progress = 0.0
        return [CalibrationUpdate(t=now, phase=STEPS[step][0], progress=0.0)]

    def _calibrate(self, envelope: np.ndarray, now: float) -> list[TensionItem]:
        assert self._step is not None
        phase, duration = STEPS[self._step]
        elapsed = now - self._step_start
        if elapsed >= SETTLE_S:
            self._held.append(envelope)
        progress = min(1.0, elapsed / duration)
        items: list[TensionItem] = []
        if progress - self._last_progress >= 0.1 or progress >= 1.0:
            self._last_progress = progress
            items.append(CalibrationUpdate(t=now, phase=phase, progress=round(progress, 2)))
        if progress < 1.0:
            return items
        self._pending[phase] = np.median(self._held, axis=0) if self._held else np.zeros(EMG_CHANNELS)
        if self._step + 1 < len(STEPS):
            return items + self._start_step(self._step + 1, now)
        self._step = None
        return items + [self._finish(now)]

    def _finish(self, now: float) -> CalibrationUpdate:
        rest = self._pending["rest"]
        poses = {}
        for pose, phase in (("fist", "squeeze"), ("palm", "palm")):
            rise = np.clip(self._pending[phase] - rest, 0.0, None)
            if rise.sum() <= 0.0:
                continue
            weights = rise / rise.sum()
            weighted = float(weights @ rise)
            if weighted >= MIN_RISE:
                poses[pose] = PoseReference(weights=weights, rise=weighted)
        if "fist" not in poses:
            return CalibrationUpdate(t=now, phase="failed", progress=1.0)
        self._rest = rest
        self._poses = poses
        self._smoothed_poses = {}
        return CalibrationUpdate(t=now, phase="done", progress=1.0)

    def _score(self, envelope: np.ndarray) -> tuple[float, str | None, dict[str, float]]:
        if self._rest is None or not self._poses:
            return 0.0, None, {}
        rise = np.clip(envelope - self._rest, 0.0, None)
        per_pose = {
            pose: min(MAX_VALUE, COMFORT_LEVEL * float(ref.weights @ rise) / ref.rise)
            for pose, ref in self._poses.items()
        }
        norm = float(np.linalg.norm(rise))
        if norm <= 0.0:
            return 0.0, None, per_pose
        pose = max(self._poses, key=lambda name: float(self._poses[name].weights @ rise) / norm)
        value = per_pose[pose]
        return value, pose if value >= 0.1 else None, per_pose

    def _smooth(self, envelope: np.ndarray, now: float) -> None:
        value, self._pose, per_pose = self._score(envelope)
        if self._last_time is None:
            alpha = 1.0
        else:
            alpha = 1.0 - math.exp(-max(0.0, now - self._last_time) / SMOOTHING_S)
        self._smoothed += (value - self._smoothed) * alpha
        for pose, pose_value in per_pose.items():
            previous = self._smoothed_poses.get(pose, pose_value)
            self._smoothed_poses[pose] = previous + (pose_value - previous) * alpha
        self._last_time = now
