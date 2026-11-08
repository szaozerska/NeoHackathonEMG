from spellgame import protocol as p

from handclient.server_link import ServerLink


def test_pairing_sets_the_player_id_and_a_calibrate_request_is_ignored():
    link = ServerLink("127.0.0.1", 0, on_haptic=lambda _: None)
    link._on_message(p.Paired(player_id="P1"))
    link._on_message(p.Calibrate(player_id="P1"))
    assert link.player_id == "P1"
