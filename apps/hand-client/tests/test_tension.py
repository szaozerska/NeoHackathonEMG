import numpy as np

from handclient.kinesis_feed import EmgBatch
from handclient.tension import COMFORT_LEVEL, FIST_S, PALM_S, REST_S, CalibrationUpdate, TensionReading, TensionTracker

FIST = np.array([0.2, 1.0, 1.0, 0.5, 0.2, 0.2, 0.2, 0.6])
PALM = np.array([0.2, 0.2, 0.2, 0.2, 0.3, 0.5, 1.0, 1.0])
RNG = np.random.default_rng(0)


def batch(t: float, amplitude: np.ndarray, sequence: int = 0) -> EmgBatch:
    """Noise-like EMG (broadband) at a per-channel RMS of roughly `amplitude` counts, plus a slow drift."""
    noise = RNG.standard_normal((16, 8)) * amplitude
    samples = (32768 + 200 * np.sin(t) + noise).astype(np.uint16)
    return EmgBatch(sequence=sequence, band_timestamp_us=int(t * 1e6), host_time_s=t, samples=samples)


def run(tracker: TensionTracker, start: float, seconds: float, amplitude):
    amplitude = np.broadcast_to(np.asarray(amplitude, float), (8,))
    items = []
    for i in range(int(seconds / 0.0078125)):
        items += tracker.push(batch(start + i * 0.0078125, amplitude, i))
    return items, start + seconds


def calibrate(tracker: TensionTracker, rest, fist, palm) -> tuple[list, float]:
    tracker.request_calibration()
    items, t = run(tracker, 0.0, REST_S + 0.02, rest)
    more, t = run(tracker, t, FIST_S + 0.02, fist)
    items += more
    more, t = run(tracker, t, PALM_S + 0.02, palm)
    return items + more, t


def readings(items) -> list[TensionReading]:
    return [i for i in items if isinstance(i, TensionReading)]


def settled(tracker, t, amplitude):
    items, t = run(tracker, t, 1.0, amplitude)
    return readings(items)[-1], t


def test_calibration_walks_rest_fist_palm_then_done():
    tracker = TensionTracker()
    items, _ = calibrate(tracker, 10.0, 10.0 + 60 * FIST, 10.0 + 60 * PALM)
    phases = [i.phase for i in items if isinstance(i, CalibrationUpdate)]
    assert phases[0] == "rest" and "squeeze" in phases and "palm" in phases and phases[-1] == "done"
    assert phases.index("squeeze") < phases.index("palm")
    assert tracker.calibrated
    done_at = next(i.t for i in items if isinstance(i, CalibrationUpdate) and i.phase == "done")
    assert all(r.t >= done_at for r in readings(items))


def test_weak_and_strong_players_read_the_comfort_level_at_their_own_calibration_clench():
    for scale in (15.0, 130.0):
        tracker = TensionTracker()
        _, t = calibrate(tracker, 10.0, 10.0 + scale * FIST, 10.0 + scale * PALM)
        relaxed, t = settled(tracker, t, 10.0)
        fist, t = settled(tracker, t, 10.0 + scale * FIST)
        harder, t = settled(tracker, t, 10.0 + 1.4 * scale * FIST)
        assert relaxed.value < 0.15
        assert abs(fist.value - COMFORT_LEVEL) < 0.15 and fist.pose == "fist"
        assert harder.value > fist.value + 0.15


def test_fist_and_palm_are_scored_against_their_own_reference():
    tracker = TensionTracker()
    _, t = calibrate(tracker, 10.0, 10.0 + 20 * FIST, 10.0 + 80 * PALM)
    palm, t = settled(tracker, t, 10.0 + 80 * PALM)
    fist, t = settled(tracker, t, 10.0 + 20 * FIST)
    assert palm.pose == "palm" and fist.pose == "fist"
    assert abs(palm.value - COMFORT_LEVEL) < 0.15 and abs(fist.value - COMFORT_LEVEL) < 0.15


def test_no_change_during_the_fist_fails_and_stays_uncalibrated():
    tracker = TensionTracker()
    items, t = calibrate(tracker, 10.0, 10.0, 10.0)
    assert [i for i in items if isinstance(i, CalibrationUpdate)][-1].phase == "failed"
    after, _ = run(tracker, t, 0.2, 10.0)
    assert readings(after) and not readings(after)[-1].calibrated
