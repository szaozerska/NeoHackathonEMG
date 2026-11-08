"""The long-lived classifier connection to the game server (architecture.md §4.2, §5)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from spellgame import protocol as p
from spellgame.client import Connection, this_machine

from .band_gestures import CleanGesture
from .emg_classifier import SignPrediction
from .tension import CalibrationUpdate, TensionReading

log = logging.getLogger(__name__)

RECONNECT_DELAY_S = 1.0


class ServerLink:
    """Connects as a classifier, learns its player ID once paired, and reconnects (reclaiming that ID) if dropped.

    Input that arrives while disconnected is dropped: it is real-time and stale by the time a reconnect completes.
    """

    def __init__(
        self,
        host: str,
        port: int,
        on_haptic: Callable[[int], None],
        on_calibrate: Callable[[], None] = lambda: None,
    ) -> None:
        self._host = host
        self._port = port
        self._on_haptic = on_haptic
        self._on_calibrate = on_calibrate
        """Starts the grip calibration: on first pairing and whenever a headset asks (`Calibrate`)."""
        self._conn: Connection | None = None
        self.player_id: str | None = None

    async def run(self) -> None:
        while True:
            self._conn = await self._connect()
            try:
                async for message in self._conn.messages():
                    self._on_message(message)
                log.warning("game server closed the connection")
            except ConnectionError as exc:
                log.warning("lost the game server: %s", exc)
            finally:
                await self._conn.close()
                self._conn = None
            await asyncio.sleep(RECONNECT_DELAY_S)

    def send_gesture(self, gesture: CleanGesture, hand: str) -> None:
        if self.player_id is None:
            if gesture.is_pinch:
                self._send(p.Pinch(t=gesture.t, hand=hand))
            return
        self._send(
            p.Gesture(player_id=self.player_id, t=gesture.t, hand=hand, finger=gesture.finger, action=gesture.action)
        )

    def send_sign(self, prediction: SignPrediction, hand: str) -> None:
        if self.player_id is None:
            return
        self._send(
            p.SignMessage(
                player_id=self.player_id,
                t=prediction.t,
                hand=hand,
                sign=prediction.sign,
                confidence=prediction.confidence,
            )
        )

    def send_tension(self, reading: TensionReading, hand: str) -> None:
        if self.player_id is None:
            return
        self._send(
            p.Tension(
                player_id=self.player_id,
                t=reading.t,
                hand=hand,
                value=reading.value,
                calibrated=reading.calibrated,
            )
        )

    def send_calibration(self, update: CalibrationUpdate) -> None:
        if self.player_id is None:
            return
        self._send(p.CalibrationStatus(player_id=self.player_id, phase=update.phase, progress=update.progress))

    def _send(self, message: p.Message) -> None:
        if self._conn is not None:
            self._conn.send(message)

    async def _connect(self) -> Connection:
        while True:
            try:
                conn = await Connection.open(self._host, self._port)
                await conn.handshake(p.Role.CLASSIFIER, self.player_id, this_machine("hand-client"))
            except OSError as exc:
                log.warning("can't reach the game server at %s:%d (%s); retrying", self._host, self._port, exc)
                await asyncio.sleep(RECONNECT_DELAY_S)
                continue
            log.info("connected to the game server at %s:%d, waiting to pair", self._host, self._port)
            return conn

    def _on_message(self, message: p.Message) -> None:
        match message:
            case p.Paired(player_id=player_id):
                first = self.player_id is None
                self.player_id = player_id
                log.info("band paired with %s", player_id)
                if first:
                    self._on_calibrate()
            case p.Calibrate():
                self._on_calibrate()
            case p.Haptic(duration_ms=duration_ms):
                self._on_haptic(duration_ms)
            case p.Error(message=text):
                log.error("game server error: %s", text)
