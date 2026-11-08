"""Authoritative game server (architecture.md §2.3): TCP for game traffic, UDP discovery beacon, fixed tick."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import socket
import time
from collections import deque
from dataclasses import dataclass, field, replace

from . import protocol as p
from .ai import AiOpponent
from .discovery import run_beacon
from .game_state import GameState, PlayerInput, Tuning
from .haptics import MATCH_END_MS, MATCH_START_MS, haptics_for
from .match import Match
from .shared_space import FLOOR_SPOT_DISTANCE_M, SharedSpace

log = logging.getLogger(__name__)

HELLO_TIMEOUT_S = 10.0
MAX_WRITE_BUFFER = 1 << 20
RECENT_PACKETS_KEPT = 50
MAX_TENSION = 1.2
"""The hand-client caps tension here (`handclient.tension.MAX_VALUE`); 0.7 is the calibrated comfortable clench."""


@dataclass(frozen=True)
class ReceivedPacket:
    received_at: float
    """Unix time."""
    message: p.Message


class ClientConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.peer = writer.get_extra_info("peername")
        self.connected_at = time.time()
        self.role: str | None = None
        self.player_id: str | None = None
        self.device: p.DeviceInfo | None = None
        self.packets_received = 0
        self.recent_packets: deque[ReceivedPacket] = deque(maxlen=RECENT_PACKETS_KEPT)

    def record_received(self, message: p.Message) -> None:
        self.packets_received += 1
        self.recent_packets.append(ReceivedPacket(received_at=time.time(), message=message))

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
    """The number in the player ID (P1 → 1): orders pairing prompts and picks the floor spot."""
    vr: ClientConnection | None = None
    classifier: ClientConnection | None = None
    input: PlayerInput = field(default_factory=PlayerInput)
    pose_dirty: bool = False
    device_id: str | None = None
    """`DeviceInfo.id` of the headset that last held this slot, so a relaunched app gets its old ID back."""


class GameServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = p.GAME_PORT,
        tick_hz: float = 30.0,
        discovery_port: int = p.DISCOVERY_PORT,
        beacon_address: str | None = "255.255.255.255",
        tuning: Tuning | None = None,
        spot_distance: float = FLOOR_SPOT_DISTANCE_M,
    ) -> None:
        self.host = host
        self.port = port
        self.dt = 1.0 / tick_hz
        self.discovery_port = discovery_port
        self.beacon_address = beacon_address
        self.game = GameState(tuning=tuning or Tuning())
        self.space = SharedSpace(spot_distance=spot_distance)
        self.match = Match()
        self.ai: AiOpponent | None = None
        self.players: dict[str, PlayerSlot] = {}
        self.connections: set[ClientConnection] = set()
        self.prompted_player_id: str | None = None
        """The player told to pinch while pairing mode (§5) runs; None outside pairing mode."""
        self._server: asyncio.Server | None = None
        self._tasks: list[asyncio.Task[None]] = []

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
            for conn in self.connections:
                conn.writer.close()
            await self._server.wait_closed()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.get_extra_info("socket").setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn = ClientConnection(reader, writer)
        self.connections.add(conn)
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
                conn.record_received(message)
                self._on_message(conn, message)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.connections.discard(conn)
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
        conn.record_received(message)
        conn.role = message.role
        conn.device = message.device
        return message

    def _join_vr(self, conn: ClientConnection, requested_id: str | None) -> None:
        slot = self.players.get(requested_id) if requested_id else None
        if slot is not None and slot.vr is not None:
            slot = None
        slot = slot or self._slot_of_device(conn) or self._free_slot() or self._new_slot()
        slot.device_id = conn.device.id if conn.device else None
        slot.vr = conn
        slot.input.connected = True
        conn.player_id = slot.player_id
        conn.send(p.Welcome(player_id=slot.player_id))
        log.info("%s joined as %s (headset)", conn.peer, slot.player_id)
        if slot.classifier is not None:
            conn.send(p.Paired(player_id=slot.player_id))
        self._announce_space()

    def _slot_of_device(self, conn: ClientConnection) -> PlayerSlot | None:
        """The same headset relaunching its app: it takes its old slot back, dropping a connection left over from the
        previous launch (a dead link can stay open for minutes) and that launch's controller band."""
        device_id = conn.device.id if conn.device else None
        slot = next((s for s in self.players.values() if device_id and s.device_id == device_id), None)
        if slot is None or slot.vr is None:
            return slot
        stale = slot.vr
        log.info("%s relaunched on the same headset; dropping its old connection %s", slot.player_id, stale.peer)
        self._drop(stale)
        if slot.classifier is not None and _host(slot.classifier.peer) == _host(stale.peer):
            self._drop(slot.classifier)
        return slot

    def _free_slot(self) -> PlayerSlot | None:
        """The lowest-numbered player nobody uses any more (no headset, no band), so IDs don't climb with restarts."""
        free = [s for s in self.players.values() if s.vr is None and s.classifier is None]
        return min(free, key=lambda s: s.join_order, default=None)

    def _new_slot(self) -> PlayerSlot:
        number = next(n for n in itertools.count(1) if f"P{n}" not in self.players)
        slot = PlayerSlot(player_id=f"P{number}", join_order=number)
        self.players[slot.player_id] = slot
        self.game.add_player(slot.player_id)
        return slot

    def _drop(self, conn: ClientConnection) -> None:
        self._leave(conn)
        conn.player_id = None
        conn.writer.close()

    def _join_classifier(self, conn: ClientConnection, requested_id: str | None) -> None:
        conn.send(p.Welcome(player_id=None))
        slot = self.players.get(requested_id) if requested_id else None
        if slot is not None and slot.classifier is None:
            self._pair(conn, slot)
            return
        log.info("%s connected as a classifier, waiting for pairing mode", conn.peer)

    def start_pairing(self) -> None:
        """Pairing mode (§5): prompts each headset without a band, in join order, to pinch; the next pinch pairs."""
        log.info("pairing mode started")
        self._send_to_everyone([p.PairStart()])
        self._prompt_next_player()

    def _prompt_next_player(self) -> None:
        waiting = [slot for slot in self.players.values() if slot.vr is not None and slot.classifier is None]
        if not waiting:
            self.prompted_player_id = None
            log.info("pairing mode finished: every headset has a band")
            return
        slot = min(waiting, key=lambda s: s.join_order)
        self.prompted_player_id = slot.player_id
        self._send_to_everyone([p.PairPrompt(player_id=slot.player_id)])
        log.info("pairing: %s, pinch your fingers", slot.player_id)

    def _on_pinch(self, conn: ClientConnection) -> None:
        if self.prompted_player_id is None:
            return
        self._pair(conn, self.players[self.prompted_player_id])
        self._prompt_next_player()

    def _pair(self, conn: ClientConnection, slot: PlayerSlot) -> None:
        slot.classifier = conn
        slot.input.band_paired = True
        conn.player_id = slot.player_id
        paired = p.Paired(player_id=slot.player_id)
        conn.send(paired)
        self._broadcast([paired])
        log.info("%s paired with %s (band)", conn.peer, slot.player_id)

    def _leave(self, conn: ClientConnection) -> None:
        slot = self.players.get(conn.player_id) if conn.player_id else None
        if slot is None:
            return
        if slot.vr is conn:
            slot.vr = None
            slot.input.connected = False
            log.info("%s headset disconnected", slot.player_id)
            if slot.player_id == self.prompted_player_id:
                self._prompt_next_player()
            self.space.forget(slot.player_id)
            self._announce_space()
        elif slot.classifier is conn:
            slot.classifier = None
            slot.input.band_paired = False
            slot.input.sign = p.Sign.NONE
            log.info("%s band disconnected", slot.player_id)

    def _on_message(self, conn: ClientConnection, message: p.Message) -> None:
        if isinstance(message, p.PairStart):
            self.start_pairing()
            return
        if isinstance(message, p.SpaceReset):
            self.reset_space()
            return
        if isinstance(message, p.Pinch) and conn.role == p.Role.CLASSIFIER and conn.player_id is None:
            self._on_pinch(conn)
            return
        slot = self.players.get(conn.player_id) if conn.player_id else None
        if slot is None:
            return
        if conn is slot.vr and isinstance(message, p.Pose):
            message.player_id = slot.player_id
            slot.input.pose = message
            slot.pose_dirty = True
        elif conn is slot.vr and isinstance(message, p.AnchorShared):
            self._on_anchor_shared(conn, slot, message)
        elif conn is slot.vr and isinstance(message, p.Aligned):
            self._on_aligned(conn, slot, message)
        elif conn is slot.vr and isinstance(message, p.DomainExpand):
            slot.input.domain_expanded = True
        elif conn is slot.vr and isinstance(
            message, (p.MatchSetup, p.Ready, p.MatchQuit, p.Rematch, p.MatchPause, p.MatchRestart)
        ):
            self._on_match_message(conn, slot, message)
        elif conn is slot.classifier and isinstance(message, p.SignMessage):
            if message.sign == p.Sign.SNAP and slot.input.sign != p.Sign.SNAP:
                slot.input.snapped = True
            slot.input.sign = message.sign
            slot.input.hand = message.hand
        elif conn is slot.classifier and isinstance(message, p.Tension):
            slot.input.tension = _tension(message.value, message.calibrated)
            slot.input.fist_tension = _tension(message.fist, message.calibrated)
            slot.input.palm_tension = _tension(message.palm, message.calibrated)
        elif conn is slot.classifier and isinstance(message, p.CalibrationStatus):
            message.player_id = slot.player_id
            self._broadcast([message])
        elif conn is slot.vr and isinstance(message, p.Calibrate):
            if slot.classifier is not None:
                slot.classifier.send(p.Calibrate(player_id=slot.player_id))
        elif conn is slot.classifier and isinstance(message, p.Gesture):
            message.player_id = slot.player_id
            self._broadcast([message])

    def _on_match_message(self, conn: ClientConnection, slot: PlayerSlot, message: p.Message) -> None:
        if isinstance(message, p.MatchSetup):
            error = self.match.setup(slot.player_id, message.mode, message.duration_s, message.sword_only)
            if error is not None:
                conn.send(p.Error(message=error))
        elif isinstance(message, p.Ready):
            self.match.set_ready(slot.player_id, message.ready)
        elif isinstance(message, p.MatchQuit):
            self.match.quit(slot.player_id)
        elif isinstance(message, p.Rematch):
            self.match.rematch()
        elif isinstance(message, p.MatchPause):
            self.match.pause(slot.player_id, message.paused)
        elif isinstance(message, p.MatchRestart):
            self.match.vote_restart(slot.player_id, self.game)
        self._sync_ai()

    def _sync_ai(self) -> None:
        """The AI opponent exists while a solo match is set up, from the ready screen to the results."""
        ai_id = self.match.ai_id
        if ai_id is not None and self.ai is None:
            self.ai = AiOpponent(ai_id)
            self.ai.sword_only = self.match.sword_only
            self.game.add_player(ai_id)
            self.ai.place_facing(self.game, self.match.owner)
            log.info("AI opponent joined")
        elif ai_id is None and self.ai is not None:
            self.game.players.pop(self.ai.player_id, None)
            self.ai = None
            log.info("AI opponent left")

    def reset_space(self) -> None:
        """Drops the shared anchor (§5.1): a new host creates a fresh one and every headset re-aligns."""
        log.info("shared space reset: re-anchoring")
        self.space.reset()
        self._announce_space()

    def _announce_space(self) -> None:
        headsets = sorted((slot for slot in self.players.values() if slot.vr is not None), key=lambda s: s.join_order)
        previous_host = self.space.host_id
        self.space.choose_host([slot.player_id for slot in headsets])
        if self.space.host_id != previous_host and self.space.host_id is not None:
            log.info("%s hosts the shared anchor", self.space.host_id)
        for seat, slot in enumerate(headsets, start=1):
            slot.vr.send(self.space.message_for(seat))  # type: ignore[union-attr]

    def _on_anchor_shared(self, conn: ClientConnection, slot: PlayerSlot, message: p.AnchorShared) -> None:
        if not self.space.share_anchor(slot.player_id, message.anchor_uuid):
            conn.send(p.Error(message=f"only the anchor host ({self.space.host_id}) can share the anchor"))
            return
        log.info("%s shared anchor %s", slot.player_id, message.anchor_uuid)
        self._announce_space()

    def _on_aligned(self, conn: ClientConnection, slot: PlayerSlot, message: p.Aligned) -> None:
        if not self.space.mark_aligned(slot.player_id, message.method, message.anchor_uuid):
            reason = f"{message.method} to anchor {message.anchor_uuid}, current anchor is {self.space.anchor_uuid}"
            conn.send(p.Error(message=f"aligned rejected: {reason}"))
            return
        log.info("%s aligned to the shared frame (%s)", slot.player_id, message.method)
        if self.space.mixed_methods():
            log.warning("headsets aligned by different methods do not share a frame: %s", self.space.aligned)

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
        inputs: dict[str, PlayerInput] = {}
        for slot in self.players.values():
            slot.input.aligned = slot.player_id in self.space.aligned
            inputs[slot.player_id] = (
                self.match.restrict(slot.input)
                if self.match.can_cast(slot.player_id)
                else replace(slot.input, sign=p.Sign.NONE, snapped=False, domain_expanded=False)
            )
        if self.ai is not None:
            match = self.match
            fighting = match.phase == p.MatchPhase.PLAYING
            won = match.phase == p.MatchPhase.ENDED and match.winner == self.ai.player_id
            self.ai.sword_only = match.sword_only
            inputs[self.ai.player_id] = match.restrict(self.ai.input(self.game, match.owner, fighting, won))
        paused = self.match.paused
        events = [] if paused else self.game.step(inputs, self.dt)
        self._step_match()
        outgoing: list[p.Message] = []
        for slot in self.players.values():
            slot.input.snapped = False
            slot.input.domain_expanded = False
            if slot.pose_dirty and slot.input.pose is not None:
                outgoing.append(slot.input.pose)
                slot.pose_dirty = False
        if self.ai is not None and (ai_pose := inputs[self.ai.player_id].pose) is not None:
            outgoing.append(ai_pose)
        state = self.game.snapshot()
        if paused:
            for projectile in state.projectiles:
                projectile.vel = [0.0, 0.0, 0.0]
        state.match = self.match.snapshot()
        outgoing.append(state)
        outgoing.extend(events)
        for event in events:
            log.info("event: %s", p.encode(event))
            for player_id, duration_ms in haptics_for(event):
                self._send_haptic(player_id, duration_ms)
        self._broadcast(outgoing)

    def _step_match(self) -> None:
        headsets = [slot.player_id for slot in sorted(self.players.values(), key=lambda s: s.join_order) if slot.vr]
        before = self.match.phase
        self.match.step(self.game, headsets, self.dt, set(self.space.aligned))
        after = self.match.phase
        if after == before:
            return
        if after == p.MatchPhase.COUNTDOWN and self.ai is not None:
            self.ai.sword_only = self.match.sword_only
            self.ai.place_facing(self.game, self.match.owner)
        buzz = {p.MatchPhase.PLAYING: MATCH_START_MS, p.MatchPhase.ENDED: MATCH_END_MS}.get(after)
        if buzz is not None:
            for player_id in self.match.fighters:
                self._send_haptic(player_id, buzz)
        self._sync_ai()

    def _send_haptic(self, player_id: str, duration_ms: int) -> None:
        slot = self.players.get(player_id)
        if slot is not None and slot.classifier is not None:
            slot.classifier.send(p.Haptic(duration_ms=duration_ms))

    def _send_to_everyone(self, messages: list[p.Message]) -> None:
        """Every headset and every classifier, paired or not."""
        payload = b"".join(p.encode_line(message) for message in messages)
        for conn in self.connections:
            if conn.role is not None:
                conn.send_line(payload)

    def _broadcast(self, messages: list[p.Message]) -> None:
        payload = b"".join(p.encode_line(message) for message in messages)
        for slot in self.players.values():
            if slot.vr is not None:
                slot.vr.send_line(payload)


def _host(peer: object) -> object:
    return peer[0] if isinstance(peer, tuple) else peer


def _tension(value: float | None, calibrated: bool) -> float | None:
    return min(MAX_TENSION, max(0.0, value)) if calibrated and value is not None else None
