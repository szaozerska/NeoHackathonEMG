import asyncio
import socket

from spellgame import protocol as p
from spellgame.client import Connection
from spellgame.discovery import discover_servers, find_server
from spellgame.game_state import Tuning
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


async def pinch_when_prompted(band: Connection, player_id: str) -> None:
    await until(band, lambda m: isinstance(m, p.PairPrompt) and m.player_id == player_id)
    band.send(p.Pinch(t=0.0, hand="right"))
    assert (await until(band, lambda m: isinstance(m, p.Paired))).player_id == player_id


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
            server.start_pairing()
            await pinch_when_prompted(band1, "P1")
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


def test_server_records_each_clients_device_and_received_packets():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None)
        await server.start()
        try:
            vr = await Connection.open("127.0.0.1", server.port)
            await vr.handshake(p.Role.VR, device=p.DeviceInfo(name="Quest 3", id="q3"))
            band = await Connection.open("127.0.0.1", server.port)
            await band.handshake(p.Role.CLASSIFIER)
            server.start_pairing()
            await pinch_when_prompted(band, "P1")
            vr.send(standing_pose(None, 1.0))
            await until(vr, lambda m: isinstance(m, p.Pose))

            by_role = {conn.role: conn for conn in server.connections}
            assert by_role[p.Role.VR].device == p.DeviceInfo(name="Quest 3", id="q3")
            assert by_role[p.Role.CLASSIFIER].device is None
            assert by_role[p.Role.CLASSIFIER].player_id == "P1"
            assert [type(r.message) for r in by_role[p.Role.VR].recent_packets] == [p.Hello, p.Pose]
            assert by_role[p.Role.VR].packets_received == 2
            assert [type(r.message) for r in by_role[p.Role.CLASSIFIER].recent_packets] == [p.Hello, p.Pinch]

            await band.close()
            await until(vr, lambda m: isinstance(m, p.State) and not m.players[0].band_paired)
            assert [conn.role for conn in server.connections] == [p.Role.VR]
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


def test_headset_starts_pairing_mode_bands_pair_by_pinch_and_fireball_deals_damage():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, tick_hz=60, beacon_address=None)
        await server.start()
        try:
            vr1 = await Connection.open("127.0.0.1", server.port)
            assert (await vr1.handshake(p.Role.VR)).player_id == "P1"
            vr2 = await Connection.open("127.0.0.1", server.port)
            assert (await vr2.handshake(p.Role.VR)).player_id == "P2"
            band1 = await Connection.open("127.0.0.1", server.port)
            assert (await band1.handshake(p.Role.CLASSIFIER)).player_id is None
            band2 = await Connection.open("127.0.0.1", server.port)
            await band2.handshake(p.Role.CLASSIFIER)

            vr2.send(p.PairStart())
            await until(vr1, lambda m: isinstance(m, p.PairStart))
            assert (await until(vr1, lambda m: isinstance(m, p.PairPrompt))).player_id == "P1"
            await pinch_when_prompted(band2, "P1")
            await pinch_when_prompted(band1, "P2")
            assert server.prompted_player_id is None
            band1, band2 = band2, band1

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
                hp_after = Tuning().max_hp - damage.amount
                assert (damage.target_id, damage.source_id, damage.hp_after) == ("P2", "P1", hp_after)
                state = await until(vr1, lambda m: isinstance(m, p.State) and m.players[1].hp < Tuning().max_hp)
                assert {pl.player_id: pl.hp for pl in state.players} == {"P1": Tuning().max_hp, "P2": hp_after}
                assert {pl.player_id: pl.band_hand for pl in state.players} == {"P1": "right", "P2": "right"}
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
            server.start_pairing()
            await pinch_when_prompted(band, "P1")
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


def test_bands_stay_unpaired_until_pairing_mode_and_a_pinch_outside_it_is_ignored():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None)
        await server.start()
        try:
            vr = await Connection.open("127.0.0.1", server.port)
            await vr.handshake(p.Role.VR)
            band = await Connection.open("127.0.0.1", server.port)
            await band.handshake(p.Role.CLASSIFIER)
            band.send(p.Pinch(t=0.0, hand="right"))
            state = await until(vr, lambda m: isinstance(m, p.State) and m.tick > 5)
            assert not state.players[0].band_paired
            assert server.players["P1"].classifier is None
            assert server.prompted_player_id is None
        finally:
            await server.stop()

    run(scenario())


def test_pairing_mode_moves_on_when_the_prompted_headset_leaves_and_ends_when_all_are_paired():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None)
        await server.start()
        try:
            vr1 = await Connection.open("127.0.0.1", server.port)
            await vr1.handshake(p.Role.VR)
            vr2 = await Connection.open("127.0.0.1", server.port)
            await vr2.handshake(p.Role.VR)
            band = await Connection.open("127.0.0.1", server.port)
            await band.handshake(p.Role.CLASSIFIER)

            server.start_pairing()
            assert server.prompted_player_id == "P1"
            await vr1.close()
            await pinch_when_prompted(band, "P2")
            assert server.prompted_player_id is None
            assert server.players["P2"].classifier is not None
        finally:
            await server.stop()

    run(scenario())


def test_first_headset_hosts_the_anchor_and_both_report_aligned_to_it():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None, spot_distance=4.0)
        await server.start()
        try:
            vr1 = await Connection.open("127.0.0.1", server.port)
            await vr1.handshake(p.Role.VR)
            space1 = await until(vr1, lambda m: isinstance(m, p.Space))
            assert space1.host_id == "P1" and space1.anchor_uuid is None
            assert (space1.spot_pos, space1.spot_yaw) == ([0.0, 0.0, -2.0], 0.0)

            vr2 = await Connection.open("127.0.0.1", server.port)
            await vr2.handshake(p.Role.VR)
            space2 = await until(vr2, lambda m: isinstance(m, p.Space))
            assert space2.host_id == "P1" and space2.group_uuid == space1.group_uuid
            assert (space2.spot_pos, space2.spot_yaw) == ([0.0, 0.0, 2.0], 180.0)

            vr2.send(p.AnchorShared(anchor_uuid="not-the-host"))
            assert isinstance(await until(vr2, lambda m: isinstance(m, p.Error)), p.Error)

            vr1.send(p.AnchorShared(anchor_uuid="anchor-1"))
            announced = await until(vr2, lambda m: isinstance(m, p.Space) and m.anchor_uuid is not None)
            assert announced.anchor_uuid == "anchor-1"
            vr2.send(p.Aligned(method=p.AlignMethod.ANCHOR, anchor_uuid="stale"))
            await until(vr2, lambda m: isinstance(m, p.Error))
            vr1.send(p.Aligned(method=p.AlignMethod.ANCHOR, anchor_uuid="anchor-1"))
            vr2.send(p.Aligned(method=p.AlignMethod.ANCHOR, anchor_uuid="anchor-1"))
            state = await until(vr1, lambda m: isinstance(m, p.State) and all(pl.aligned for pl in m.players))
            assert {pl.player_id for pl in state.players} == {"P1", "P2"}

            await vr1.close()
            handover = await until(vr2, lambda m: isinstance(m, p.Space) and m.host_id == "P2")
            assert handover.anchor_uuid == "anchor-1"

            vr2.send(p.SpaceReset())
            reset = await until(vr2, lambda m: isinstance(m, p.Space) and m.anchor_uuid is None)
            assert reset.host_id == "P2" and reset.group_uuid != space1.group_uuid
            await until(vr2, lambda m: isinstance(m, p.State) and not m.players[1].aligned)
            await vr2.close()
        finally:
            await server.stop()

    run(scenario())


def test_solo_match_with_the_ai_counts_down_plays_and_quits_back_to_the_lobby():
    def phase_is(phase):
        return lambda m: isinstance(m, p.State) and m.match is not None and m.match.phase == phase

    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None)
        await server.start()
        try:
            vr = await Connection.open("127.0.0.1", server.port)
            await vr.handshake(p.Role.VR)
            vr.send(standing_pose("P1", 0.0))
            vr.send(p.MatchSetup(mode=p.MatchMode.SOLO, duration_s=60.0))
            ready = await until(vr, phase_is(p.MatchPhase.READY))
            assert ready.match.fighters == ["P1", p.AI_PLAYER_ID]
            assert ready.match.ready == [p.AI_PLAYER_ID]
            assert p.AI_PLAYER_ID in {player.player_id for player in ready.players}
            await until(vr, lambda m: isinstance(m, p.Pose) and m.player_id == p.AI_PLAYER_ID)

            vr.send(p.Ready(ready=True))
            await until(vr, phase_is(p.MatchPhase.COUNTDOWN))
            playing = await until(vr, phase_is(p.MatchPhase.PLAYING), timeout=5.0)
            assert playing.match.time_left <= 60.0

            vr.send(p.MatchQuit())
            ended = await until(vr, phase_is(p.MatchPhase.ENDED))
            assert (ended.match.reason, ended.match.ended_by) == (p.MatchEndReason.QUIT, "P1")
            vr.send(p.MatchQuit())
            lobby = await until(vr, phase_is(p.MatchPhase.LOBBY))
            assert p.AI_PLAYER_ID not in {player.player_id for player in lobby.players}
            await vr.close()
        finally:
            await server.stop()

    run(scenario())
