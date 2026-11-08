import numpy as np

from handclient.kinesis_feed import EmgBatch
from handclient.tension import REST_S, SQUEEZE_S, CalibrationUpdate, TensionReading, TensionTracker


def batch(t: float, amplitude: float, sequence: int = 0) -> EmgBatch:
    wave = np.sin(np.linspace(0.0, 6.0 * np.pi, 16))[:, None] * amplitude
    samples = (32768 + wave + np.zeros((16, 8))).astype(np.uint16)
    return EmgBatch(sequence=sequence, band_timestamp_us=int(t * 1e6), host_time_s=t, samples=samples)


def run(tracker: TensionTracker, start: float, seconds: float, amplitude: float):
    items = []
    for i in range(int(seconds / 0.008)):
        items += tracker.push(batch(start + i * 0.008, amplitude, i))
    return items, start + seconds


def calibrate(tracker: TensionTracker, rest: float, squeeze: float) -> tuple[list, float]:
    tracker.request_calibration()
    items, t = run(tracker, 0.0, REST_S + 0.05, rest)
    more, t = run(tracker, t, SQUEEZE_S + 0.05, squeeze)
    return items + more, t


def readings(items) -> list[TensionReading]:
    return [i for i in items if isinstance(i, TensionReading)]


def test_calibration_walks_rest_then_squeeze_then_done():
    tracker = TensionTracker()
    items, _ = calibrate(tracker, rest=5.0, squeeze=400.0)
    phases = [i.phase for i in items if isinstance(i, CalibrationUpdate)]
    assert phases[0] == "rest" and "squeeze" in phases and phases[-1] == "done"
    assert tracker.calibrated
    done_at = next(i.t for i in items if isinstance(i, CalibrationUpdate) and i.phase == "done")
    assert all(r.t >= done_at for r in readings(items))


def test_weak_and_strong_grips_reach_the_same_tension_at_their_own_comfortable_squeeze():
    values = []
    for rest, squeeze in ((5.0, 150.0), (8.0, 900.0)):
        tracker = TensionTracker()
        _, t = calibrate(tracker, rest, squeeze)
        relaxed, t = run(tracker, t, 1.0, rest)
        squeezed, t = run(tracker, t, 1.0, squeeze * 0.9)
        assert readings(relaxed)[-1].value < 0.1
        values.append(readings(squeezed)[-1].value)
    assert abs(values[0] - values[1]) < 0.05
    assert all(0.85 < v < 1.15 for v in values)


def test_no_change_between_rest_and_squeeze_fails_and_stays_uncalibrated():
    tracker = TensionTracker()
    items, t = calibrate(tracker, rest=5.0, squeeze=5.0)
    assert [i for i in items if isinstance(i, CalibrationUpdate)][-1].phase == "failed"
    after, _ = run(tracker, t, 0.2, 5.0)
    assert readings(after) and not readings(after)[-1].calibrated
