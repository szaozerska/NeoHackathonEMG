"""Causal filters and feature windows, identical offline and live."""
from collections import deque
import numpy as np
from scipy.signal import butter, iirnotch, tf2sos, sosfilt

DEFAULT_SIGNAL = {"sample_rate": 2048, "channels": 8, "state_window": 410,
                  "state_hop": 102, "snap_window": 256, "snap_hop": 32,
                  "notch": True, "noise_threshold": 3.0, "warmup_samples": 512}


def features(window, noise=3.0):
    x = np.asarray(window, dtype=float)
    d = np.diff(x, axis=0)
    zc = ((x[1:] * x[:-1] < 0) & (np.abs(d) > noise)).sum(axis=0)
    ssc = ((d[1:] * d[:-1] < 0) & (np.abs(d[1:]) > noise) & (np.abs(d[:-1]) > noise)).sum(axis=0)
    return np.concatenate([np.sqrt(np.mean(x*x, axis=0)), np.mean(np.abs(x), axis=0),
                           np.mean(np.abs(d), axis=0), zc / len(x), ssc / len(x)])


def snap_features(window, noise=3.0):
    # Preserve temporal burst order; use only the past window.
    return np.concatenate([features(part, noise) for part in np.array_split(window, 4)])


class SignalWindows:
    def __init__(self, config=None, include_waveforms=False):
        self.include_waveforms = include_waveforms
        self.config = DEFAULT_SIGNAL | (config or {})
        c = self.config
        sos = butter(4, [20, 450], fs=c["sample_rate"], btype="bandpass", output="sos")
        if c["notch"]:
            b, a = iirnotch(60, 30, fs=c["sample_rate"])
            sos = np.vstack([sos, tf2sos(b, a)])
        self.sos = sos
        self.reset()

    def reset(self):
        c = self.config
        self.zi = np.zeros((len(self.sos), 2, c["channels"]))
        self.samples = deque(maxlen=max(c["state_window"], c["snap_window"]))
        self.times = deque(maxlen=self.samples.maxlen)
        self.count = 0
        self.last_time = None

    def feed(self, samples, times):
        samples = np.asarray(samples, dtype=float)
        times = np.asarray(times, dtype=float)
        if samples.shape != (len(times), self.config["channels"]) or not np.isfinite(samples).all() or not np.isfinite(times).all():
            raise ValueError("Bad EMG sample shape or non-finite values")
        rows = []
        fs = self.config["sample_rate"]
        # Filtering per contiguous segment preserves state across packet boundaries.
        boundaries = [0] + list(np.flatnonzero((np.diff(times) > 2.5/fs) | (np.diff(times) <= 0)) + 1) + [len(times)]
        for a, b in zip(boundaries, boundaries[1:]):
            if a == b:
                continue
            if self.last_time is not None and not (0 < times[a] - self.last_time <= 2.5/fs):
                self.reset()
            filtered, self.zi = sosfilt(self.sos, samples[a:b], axis=0, zi=self.zi)
            for x, t in zip(filtered, times[a:b]):
                self.samples.append(x)
                self.times.append(float(t))
                self.last_time = float(t)
                self.count += 1
                for kind in ("state", "snap"):
                    size, hop = self.config[kind + "_window"], self.config[kind + "_hop"]
                    if self.count >= self.config["warmup_samples"] + size and self.count % hop == 0:
                        data = np.asarray(self.samples)[-size:]
                        fn = features if kind == "state" else snap_features
                        rows.append({"kind": kind, "start": self.times[-size], "t": float(t),
                                     "x": fn(data, self.config["noise_threshold"])})
                        if self.include_waveforms:
                            rows[-1]["waveform"] = data.T.astype(np.float32)
        return rows
