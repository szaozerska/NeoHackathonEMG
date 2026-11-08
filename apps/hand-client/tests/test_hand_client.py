import asyncio
import contextlib
import itertools
import logging

from spellgame import protocol as p
from spellgame.client import Connection
from spellgame.server import GameServer

from handclient.emg_classifier import EmgLogger
from handclient.main import run_hand_client
from handclient.server_picker import parse_choice
from tests import fake_kinesis as fk


async def until(conn: Connection, predicate, timeout=5.0):
    async def wait():
        while (message := await conn.receive()) is not None:
            if predicate(message):
                return message
        raise AssertionError("connection closed")

    return await asyncio.wait_for(wait(), timeout)


async def pair_by_pinching(vr: Connection, kinesis: fk.FakeKinesis) -> None:
    """Starts pairing mode from the headset, then pinches on the band until the hand-client is connected and pairs."""
    vr.send(p.PairStart())
    await until(vr, lambda m: isinstance(m, p.PairPrompt))
    for sequence in itertools.count(1000):
        kinesis.send(fk.gesture(sequence, "index", "tap", at_s=float(sequence)))
        with contextlib.suppress(TimeoutError):
            await until(vr, lambda m: isinstance(m, p.Paired), timeout=0.2)
            return


def test_band_gestures_reach_the_headset_and_emg_is_logged(caplog):
    caplog.set_level(logging.INFO)
    events = [fk.emg_configuration()]
    events += [fk.emg(sequence) for sequence in range(1, 200)]
    events += [fk.gesture(1, "index", "tap", "singleTap", at_s=5000.0), fk.gesture(2, "index", "tap", at_s=5000.05)]

    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None)
        await server.start()
        try:
            vr = await Connection.open("127.0.0.1", server.port)
            assert (await vr.handshake(p.Role.VR)).player_id == "P1"
            with fk.FakeKinesis([fk.hello("right")]) as kinesis:
                client = asyncio.create_task(
                    run_hand_client(kinesis.url, ("127.0.0.1", server.port), EmgLogger(report_every_s=0.0))
                )
                await pair_by_pinching(vr, kinesis)
                kinesis.send(*events)
                gesture = await until(vr, lambda m: isinstance(m, p.Gesture))
                client.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await client
            assert (gesture.player_id, gesture.hand, gesture.finger, gesture.action) == ("P1", "right", "index", "tap")
        finally:
            await server.stop()

    asyncio.run(asyncio.wait_for(scenario(), 20))
    assert any("emg:" in record.getMessage() for record in caplog.records)


def test_server_haptics_reach_kinesis_with_the_feed_token():
    async def scenario():
        server = GameServer(host="127.0.0.1", port=0, beacon_address=None)
        await server.start()
        try:
            vr = await Connection.open("127.0.0.1", server.port)
            await vr.handshake(p.Role.VR)
            with fk.FakeKinesis([fk.hello("right")]) as kinesis:
                client = asyncio.create_task(run_hand_client(kinesis.url, ("127.0.0.1", server.port), EmgLogger()))
                await pair_by_pinching(vr, kinesis)
                band = server.players["P1"].classifier
                assert band is not None
                band.send(p.Haptic(duration_ms=120))
                while not kinesis.haptics_ms:
                    await asyncio.sleep(0.02)
                client.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await client
                assert kinesis.haptics_ms == [120]
        finally:
            await server.stop()

    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_server_choice_accepts_a_number_or_an_address():
    servers = [("10.0.0.5", 9000), ("10.0.0.6", 9001)]
    assert parse_choice("2", servers) == ("10.0.0.6", 9001)
    assert parse_choice("", servers) is None
    assert parse_choice("3", servers) is None
    assert parse_choice("192.168.1.9", servers) == ("192.168.1.9", p.GAME_PORT)
    assert parse_choice("192.168.1.9:9100", servers) == ("192.168.1.9", 9100)
