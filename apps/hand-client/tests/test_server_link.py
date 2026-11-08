import asyncio

from spellgame import protocol as p
from spellgame.client import Connection
from spellgame.server import GameServer

from handclient.band_gestures import CleanGesture, Finger, GestureAction
from handclient.server_link import ServerLink


def test_pairing_sets_the_player_id_and_a_calibrate_request_is_ignored():
    link = ServerLink("127.0.0.1", 0, on_haptic=lambda _: None)
    link._on_message(p.Paired(player_id="P1"))
    link._on_message(p.Calibrate(player_id="P1"))
    assert link.player_id == "P1"


def test_a_band_remembering_a_player_id_the_restarted_server_lacks_pairs_again_by_pinching():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None)
        await server.start()
        link = ServerLink("127.0.0.1", server.port, on_haptic=lambda _: None)
        link.player_id = "P1"
        running = asyncio.create_task(link.run())
        try:
            await until(lambda: any(c.role == p.Role.CLASSIFIER for c in server.connections) and link.player_id is None)
            vr = await Connection.open("127.0.0.1", server.port)
            await vr.handshake(p.Role.VR)
            server.start_pairing()
            link.send_gesture(CleanGesture(t=0.0, finger=Finger.INDEX, action=GestureAction.TAP), "right")
            await until(lambda: link.player_id == "P1" and server.players["P1"].classifier is not None)
            await vr.close()
        finally:
            running.cancel()
            await server.stop()

    asyncio.run(asyncio.wait_for(scenario(), 10))


async def until(condition) -> None:
    while not condition():
        await asyncio.sleep(0.01)
