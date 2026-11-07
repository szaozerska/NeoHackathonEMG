import asyncio
import socket

from spellgame import protocol as p
from spellgame.client import Connection
from spellgame.discovery import discover_servers, find_server
from spellgame.haptics import CAST_MS, CHARGING_MS, HIT_DEALT_MS, HIT_TAKEN_MS
from spellgame.server import GameServer
from spellgame.sim import THROW_DURATION_S, standing_pose, throw_hand_offset


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def until(conn: Connection, predicate, timeout=3.0):
    async def wait():
        while True:
            message = await conn.receive()
            assert message is not None, "connection closed"
            if predicate(message):
                return message

    return await asyncio.wait_for(wait(), timeout)


def run(coro):
    asyncio.run(asyncio.wait_for(coro, 15))


def test_discovery_beacon_advertises_tcp_port():
    async def scenario():
        discovery_port = free_udp_port()
        server = GameServer(host="127.0.0.1", port=0, discovery_port=discovery_port, beacon_address="127.0.0.1")
        await server.start()
        try:
            host, port = await find_server(discovery_port, timeout_s=3.0)
            assert (host, port) == ("127.0.0.1", server.port)
        finally:
            await server.stop()

    run(scenario())


def test_discover_servers_lists_each_beaconing_server_once():
    async def scenario():
        discovery_port = free_udp_port()
        servers = [
            GameServer(host="127.0.0.1", port=0, discovery_port=discovery_port, beacon_address="127.0.0.1")
            for _ in range(2)
        ]
        for server in servers:
            await server.start()
        try:
            found = await discover_servers(discovery_port, listen_s=1.5)
            assert sorted(found) == sorted(("127.0.0.1", server.port) for server in servers)
        finally:
            for server in servers:
                await server.stop()

    run(scenario())


def test_band_gesture_is_relayed_to_every_headset_with_the_bands_player_id():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None)
        await server.start()
        try:
            vr1 = await Connection.open("127.0.0.1", server.port)
            await vr1.handshake(p.Role.VR)
            band1 = await Connection.open("127.0.0.1", server.port)
            await band1.handshake(p.Role.CLASSIFIER)
            await until(band1, lambda m: isinstance(m, p.Paired))
            vr2 = await Connection.open("127.0.0.1", server.port)
            await vr2.handshake(p.Role.VR)

            band1.send(
                p.Gesture(player_id=None, t=1.0, hand="right", finger=p.Finger.INDEX, action=p.GestureAction.TAP)
            )
            for vr in (vr1, vr2):
                gesture = await until(vr, lambda m: isinstance(m, p.Gesture))
                assert (gesture.player_id, gesture.finger, gesture.action) == ("P1", "index", "tap")
        finally:
            await server.stop()

    run(scenario())


def test_rejects_connection_without_hello():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None)
        await server.start()
        try:
            conn = await Connection.open("127.0.0.1", server.port)
            conn.send(p.Pinch(t=0.0, hand="right"))
            assert isinstance(await conn.receive(), p.Error)
            assert await conn.receive() is None
        finally:
            await server.stop()

    run(scenario())


def test_two_players_pair_by_join_order_and_fireball_deals_damage():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, tick_hz=60, beacon_address=None)
        await server.start()
        try:
            vr1 = await Connection.open("127.0.0.1", server.port)
            assert (await vr1.handshake(p.Role.VR)).player_id == "P1"
            band1 = await Connection.open("127.0.0.1", server.port)
            assert (await band1.handshake(p.Role.CLASSIFIER)).player_id is None
            assert (await until(band1, lambda m: isinstance(m, p.Paired))).player_id == "P1"

            vr2 = await Connection.open("127.0.0.1", server.port)
            assert (await vr2.handshake(p.Role.VR)).player_id == "P2"
            band2 = await Connection.open("127.0.0.1", server.port)
            await band2.handshake(p.Role.CLASSIFIER)
            assert (await until(band2, lambda m: isinstance(m, p.Paired))).player_id == "P2"

            loop = asyncio.get_running_loop()
            start = loop.time()

            async def stream_poses(stop: asyncio.Event):
                throw_at = None
                while not stop.is_set():
                    now = loop.time() - start
                    hand = None
                    if throw_at is not None and now - throw_at < THROW_DURATION_S:
                        hand = throw_hand_offset(now - throw_at)
                    elif throw_at is None and now > 0.3:
                        band1.send(p.SignMessage(player_id="P1", t=now, hand="right", sign=p.Sign.SNAP))
                        throw_at = now + 0.1
                    vr1.send(standing_pose("P1", now, (0.0, 0.0), 0.0, hand))
                    vr2.send(standing_pose("P2", now, (0.0, 3.0), 180.0))
                    await asyncio.sleep(1 / 60)

            stop = asyncio.Event()
            streamer = asyncio.create_task(stream_poses(stop))
            try:
                remote_pose = await until(vr2, lambda m: isinstance(m, p.Pose) and m.player_id == "P1")
                assert "r_hand" in remote_pose.joints
                cast = await until(vr2, lambda m: isinstance(m, p.Spell) and m.state == p.SpellState.CAST)
                assert cast.caster_id == "P1"
                damage = await until(vr2, lambda m: isinstance(m, p.Damage))
                assert (damage.target_id, damage.source_id, damage.hp_after) == ("P2", "P1", 80.0)
                state = await until(vr1, lambda m: isinstance(m, p.State) and m.players[1].hp < 100.0)
                assert {pl.player_id: pl.hp for pl in state.players} == {"P1": 100.0, "P2": 80.0}
                assert all(pl.band_paired for pl in state.players)
                caster_buzzes = [await until(band1, lambda m: isinstance(m, p.Haptic)) for _ in range(3)]
                assert [h.duration_ms for h in caster_buzzes] == [CHARGING_MS, CAST_MS, HIT_DEALT_MS]
                assert (await until(band2, lambda m: isinstance(m, p.Haptic))).duration_ms == HIT_TAKEN_MS
            finally:
                stop.set()
                await streamer
            for conn in (vr1, vr2, band1, band2):
                await conn.close()
        finally:
            await server.stop()

    run(scenario())


def test_headset_reconnect_reclaims_player_id_and_band():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None)
        await server.start()
        try:
            vr = await Connection.open("127.0.0.1", server.port)
            await vr.handshake(p.Role.VR)
            band = await Connection.open("127.0.0.1", server.port)
            await band.handshake(p.Role.CLASSIFIER)
            await until(band, lambda m: isinstance(m, p.Paired))
            await vr.close()
            await asyncio.sleep(0.1)
            assert server.game.players["P1"].connected is False

            vr = await Connection.open("127.0.0.1", server.port)
            assert (await vr.handshake(p.Role.VR, player_id="P1")).player_id == "P1"
            assert (await until(vr, lambda m: isinstance(m, p.Paired))).player_id == "P1"
            await vr.close()
            await band.close()
        finally:
            await server.stop()

    run(scenario())
