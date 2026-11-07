"""Authoritative game server (architecture.md §2.3): TCP for game traffic, UDP discovery beacon, fixed tick."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import socket
from dataclasses import dataclass, field

from . import protocol as p
from .discovery import run_beacon
from .game_state import GameState, PlayerInput, Tuning

log = logging.getLogger(__name__)

HELLO_TIMEOUT_S = 10.0
MAX_WRITE_BUFFER = 1 << 20


class ClientConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.peer = writer.get_extra_info("peername")
        self.role: str | None = None
        self.player_id: str | None = None

    def send(self, message: p.Message) -> None:
        self.send_line(p.encode_line(message))

    def send_line(self, line: bytes) -> None:
        if self.writer.is_closing():
            return
        if self.writer.transport.get_write_buffer_size() > MAX_WRITE_BUFFER:
            log.warning("%s is not reading; disconnecting", self.peer)
            self.writer.close()
            return
        self.writer.write(line)


@dataclass
class PlayerSlot:
    player_id: str
    join_order: int
    vr: ClientConnection | None = None
    classifier: ClientConnection | None = None
    input: PlayerInput = field(default_factory=PlayerInput)
    pose_dirty: bool = False


class GameServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = p.GAME_PORT,
        tick_hz: float = 30.0,
        discovery_port: int = p.DISCOVERY_PORT,
        beacon_address: str | None = "255.255.255.255",
        tuning: Tuning | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.dt = 1.0 / tick_hz
        self.discovery_port = discovery_port
        self.beacon_address = beacon_address
        self.game = GameState(tuning=tuning or Tuning())
        self.players: dict[str, PlayerSlot] = {}
        self.unpaired_classifiers: list[ClientConnection] = []
        self._server: asyncio.Server | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._joins = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        log.info("game server listening on TCP %s:%d, tick %.0f Hz", self.host, self.port, 1.0 / self.dt)
        self._tasks.append(asyncio.create_task(self._tick_loop()))
        if self.beacon_address:
            self._tasks.append(asyncio.create_task(run_beacon(self.port, self.discovery_port, self.beacon_address)))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._server is not None:
            self._server.close()
            for slot in self.players.values():
                for conn in (slot.vr, slot.classifier):
                    if conn is not None:
                        conn.writer.close()
            for conn in self.unpaired_classifiers:
                conn.writer.close()
            await self._server.wait_closed()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.get_extra_info("socket").setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn = ClientConnection(reader, writer)
        try:
            hello = await self._read_hello(conn)
            if hello is None:
                return
            if hello.role == p.Role.VR:
                self._join_vr(conn, hello.player_id)
            else:
                self._join_classifier(conn, hello.player_id)
            while line := await reader.readline():
                try:
                    message = p.decode(line)
                except p.ProtocolError as exc:
                    log.warning("%s sent a bad message: %s", conn.peer, exc)
                    continue
                self._on_message(conn, message)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._leave(conn)
            writer.close()

    async def _read_hello(self, conn: ClientConnection) -> p.Hello | None:
        try:
            line = await asyncio.wait_for(conn.reader.readline(), HELLO_TIMEOUT_S)
            message = p.decode(line)
        except (TimeoutError, p.ProtocolError) as exc:
            conn.send(p.Error(message=f"expected hello: {exc}"))
            return None
        if not isinstance(message, p.Hello) or message.role not in (p.Role.VR, p.Role.CLASSIFIER):
            conn.send(p.Error(message='first message must be {"type":"hello","role":"vr"|"classifier"}'))
            return None
        conn.role = message.role
        return message

    def _join_vr(self, conn: ClientConnection, requested_id: str | None) -> None:
        slot = self.players.get(requested_id) if requested_id else None
        if slot is None or slot.vr is not None:
            self._joins += 1
            slot = PlayerSlot(player_id=f"P{self._joins}", join_order=self._joins)
            self.players[slot.player_id] = slot
            self.game.add_player(slot.player_id)
        slot.vr = conn
        slot.input.connected = True
        conn.player_id = slot.player_id
        conn.send(p.Welcome(player_id=slot.player_id))
        log.info("%s joined as %s (headset)", conn.peer, slot.player_id)
        if slot.classifier is not None:
            conn.send(p.Paired(player_id=slot.player_id))
        self._pair_waiting_classifiers()

    def _join_classifier(self, conn: ClientConnection, requested_id: str | None) -> None:
        conn.send(p.Welcome(player_id=None))
        slot = self.players.get(requested_id) if requested_id else None
        if slot is not None and slot.classifier is None:
            self._pair(conn, slot)
            return
        self.unpaired_classifiers.append(conn)
        log.info("%s connected as a classifier, waiting to pair", conn.peer)
        self._pair_waiting_classifiers()

    def _pair_waiting_classifiers(self) -> None:
        """Join-order pairing (§5): each waiting classifier gets the most recently joined headset without a band."""
        while self.unpaired_classifiers:
            candidates = [s for s in self.players.values() if s.vr is not None and s.classifier is None]
            if not candidates:
                return
            self._pair(self.unpaired_classifiers.pop(0), max(candidates, key=lambda s: s.join_order))

    def _pair(self, conn: ClientConnection, slot: PlayerSlot) -> None:
        slot.classifier = conn
        slot.input.band_paired = True
        conn.player_id = slot.player_id
        paired = p.Paired(player_id=slot.player_id)
        conn.send(paired)
        self._broadcast([paired])
        log.info("%s paired with %s (band)", conn.peer, slot.player_id)

    def _leave(self, conn: ClientConnection) -> None:
        if conn in self.unpaired_classifiers:
            self.unpaired_classifiers.remove(conn)
        slot = self.players.get(conn.player_id) if conn.player_id else None
        if slot is None:
            return
        if slot.vr is conn:
            slot.vr = None
            slot.input.connected = False
            log.info("%s headset disconnected", slot.player_id)
        elif slot.classifier is conn:
            slot.classifier = None
            slot.input.band_paired = False
            slot.input.sign = p.Sign.NONE
            log.info("%s band disconnected", slot.player_id)
            self._pair_waiting_classifiers()

    def _on_message(self, conn: ClientConnection, message: p.Message) -> None:
        slot = self.players.get(conn.player_id) if conn.player_id else None
        if slot is None:
            return
        if conn is slot.vr and isinstance(message, p.Pose):
            message.player_id = slot.player_id
            slot.input.pose = message
            slot.pose_dirty = True
        elif conn is slot.classifier and isinstance(message, p.SignMessage):
            if message.sign == p.Sign.SNAP and slot.input.sign != p.Sign.SNAP:
                slot.input.snapped = True
            slot.input.sign = message.sign
            slot.input.hand = message.hand
        elif conn is slot.classifier and isinstance(message, p.Gesture):
            message.player_id = slot.player_id
            self._broadcast([message])

    async def _tick_loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            self.tick()
            next_tick += self.dt
            delay = next_tick - loop.time()
            if delay < -5 * self.dt:
                next_tick = loop.time()
            await asyncio.sleep(max(0.0, delay))

    def tick(self) -> None:
        events = self.game.step({slot.player_id: slot.input for slot in self.players.values()}, self.dt)
        outgoing: list[p.Message] = []
        for slot in self.players.values():
            slot.input.snapped = False
            if slot.pose_dirty and slot.input.pose is not None:
                outgoing.append(slot.input.pose)
                slot.pose_dirty = False
        outgoing.append(self.game.snapshot())
        outgoing.extend(events)
        for event in events:
            log.info("event: %s", p.encode(event))
        self._broadcast(outgoing)

    def _broadcast(self, messages: list[p.Message]) -> None:
        payload = b"".join(p.encode_line(message) for message in messages)
        for slot in self.players.values():
            if slot.vr is not None:
                slot.vr.send_line(payload)


async def _serve(args: argparse.Namespace) -> None:
    server = GameServer(
        host=args.host,
        port=args.port,
        tick_hz=args.tick_hz,
        discovery_port=args.discovery_port,
        beacon_address=None if args.no_beacon else args.beacon_address,
    )
    await server.start()
    try:
        await asyncio.Event().wait()
    finally:
        await server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=p.GAME_PORT)
    parser.add_argument("--tick-hz", type=float, default=30.0)
    parser.add_argument("--discovery-port", type=int, default=p.DISCOVERY_PORT)
    parser.add_argument("--beacon-address", default="255.255.255.255")
    parser.add_argument("--no-beacon", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve(args))


if __name__ == "__main__":
    main()
