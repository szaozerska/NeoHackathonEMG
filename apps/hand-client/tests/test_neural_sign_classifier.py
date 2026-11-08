import numpy as np
from spellgame import protocol as p

from handclient.emg_classifier import NeuralSignClassifier
from handclient.kinesis_feed import EmgBatch


class ScriptedPredictor:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.packets = []

    def feed(self, packet):
        self.packets.append(packet)
        return self.outputs.pop(0)


def state(label, confidence=0.9):
    return {"kind": "neural_state", "label": label, "confidence": confidence}


def snap(confidence=0.999):
    return {"kind": "neural_event", "label": "snap", "confidence": confidence}


def batch(i):
    return EmgBatch(i, 1_000_000 + i * 7812, 10.0 + i * 0.1, np.full((16, 8), 32768, dtype=np.uint16))


def test_neural_states_map_to_game_signs_and_snap_is_momentary():
    outputs = [
        [],
        [state("fist")],
        [state("fist")],
        [state("fist"), snap()],
        [state("fist")],
        [state("infinite_void")],
        [state("open")],
        [state("unknown")],
    ]
    classifier = NeuralSignClassifier("unused", heartbeat_s=5.0, predictor=ScriptedPredictor(outputs))
    signs = [prediction.sign if (prediction := classifier.push(batch(i))) else None for i in range(len(outputs))]
    assert signs == [None, p.Sign.FIST, None, p.Sign.SNAP, p.Sign.FIST, p.Sign.INFINITE_VOID, p.Sign.OPEN_PALM, p.Sign.NONE]


def test_unchanged_state_is_resent_as_heartbeat_and_packet_keeps_sensor_clock():
    predictor = ScriptedPredictor([[state("none")]] * 12)
    classifier = NeuralSignClassifier("unused", heartbeat_s=1.0, predictor=predictor)
    sent = [i for i in range(12) if classifier.push(batch(i))]
    assert sent == [0, 10]
    assert predictor.packets[1]["source_seq"] == 1 and predictor.packets[1]["source_t"] == 1_007_812
    assert predictor.packets[1]["samples"].shape == (16, 8)


def test_snap_threshold_overrides_only_the_event_task():
    predictor = ScriptedPredictor([])
    predictor.manifest = {"tasks": {"state": {"threshold": 0.55}, "snap": {"threshold": 0.995, "event_class": "snap"}}}
    NeuralSignClassifier("unused", predictor=predictor, snap_threshold=0.999)
    assert predictor.manifest["tasks"] == {
        "state": {"threshold": 0.55},
        "snap": {"threshold": 0.999, "event_class": "snap"},
    }
