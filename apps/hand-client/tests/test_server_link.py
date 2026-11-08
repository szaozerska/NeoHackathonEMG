from spellgame import protocol as p

from handclient.server_link import ServerLink


def test_grip_calibration_starts_only_when_a_headset_asks():
    calls = []
    link = ServerLink("127.0.0.1", 0, on_haptic=lambda _: None, on_calibrate=lambda: calls.append(1))
    link._on_message(p.Paired(player_id="P1"))
    assert link.player_id == "P1" and calls == []
    link._on_message(p.Calibrate(player_id="P1"))
    assert calls == [1]
