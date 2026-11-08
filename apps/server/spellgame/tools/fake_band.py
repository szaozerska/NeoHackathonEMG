"""Fake Neural Band client: sends already-recognized gestures as `sign` messages, like the hand-sign client will.

Type a gesture and press Enter: `s` = snap, `f` = fist, `p` = open palm, `n` = none, `i` = pinch (pairs it while the
server's pairing mode prompts a player). Or script it:

    python -m spellgame.tools.fake_band --pinch-on-prompt --snap-every 3
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import time

from .. import protocol as p
from ..client import Connection, resolve_server, this_machine

log = logging.getLogger("fake_band")

SNAP_HOLD_S = 0.15
HEARTBEAT_S = 0.1
KEYS = {"s": p.Sign.SNAP, "f": p.Sign.FIST, "p": p.Sign.OPEN_PALM, "n": p.Sign.NONE}
PINCH_KEY = "i"


class Band:
    def __init__(self, conn: Connection, hand: str) -> None:
        self.conn = conn
        self.hand = hand
        self.player_id: str | None = None
        self.held = p.Sign.NONE
        self._snap_until = 0.0

    @property
    def current(self) -> str:
        return p.Sign.SNAP if time.monotonic() < self._snap_until else self.held

    def gesture(self, sign: str) -> None:
        if sign == p.Sign.SNAP:
            self._snap_until = time.monotonic() + SNAP_HOLD_S
        else:
            self.held = sign
        self.send()

    def pinch(self) -> None:
        if self.player_id is None:
            self.conn.send(p.Pinch(t=time.monotonic(), hand=self.hand))

    def send(self) -> None:
        if self.player_id is None:
            return
        self.conn.send(p.SignMessage(player_id=self.player_id, t=time.monotonic(), hand=self.hand, sign=self.current))


async def run(args: argparse.Namespace) -> None:
    host, port = await resolve_server(args.host, args.port, args.discovery_port)
    conn = await Connection.open(host, port)
    await conn.handshake(p.Role.CLASSIFIER, args.player_id, this_machine("fake_band"))
    band = Band(conn, args.hand)
    log.info("connected to %s:%d, waiting to pair", host, port)

    async def receive() -> None:
        async for message in conn.messages():
            if isinstance(message, p.Paired):
                band.player_id = message.player_id
                log.info("paired with %s", message.player_id)
            elif isinstance(message, p.PairPrompt) and args.pinch_on_prompt and band.player_id is None:
                log.info("pinch (pairing prompts %s)", message.player_id)
                band.pinch()

    async def heartbeat() -> None:
        last = band.current
        while True:
            await asyncio.sleep(HEARTBEAT_S / 2)
            if band.current != last or int(time.monotonic() / HEARTBEAT_S) % 2 == 0:
                band.send()
                last = band.current
            await conn.writer.drain()

    async def scripted_snaps() -> None:
        while True:
            await asyncio.sleep(args.snap_every)
            log.info("snap")
            band.gesture(p.Sign.SNAP)

    async def keyboard() -> None:
        loop = asyncio.get_running_loop()
        while line := await loop.run_in_executor(None, sys.stdin.readline):
            key = line.strip().lower()[:1]
            if key == PINCH_KEY:
                log.info("pinch")
                band.pinch()
                continue
            sign = KEYS.get(key)
            if sign is not None:
                log.info("gesture: %s", sign)
                band.gesture(sign)

    tasks = [asyncio.create_task(receive()), asyncio.create_task(heartbeat())]
    tasks.append(asyncio.create_task(scripted_snaps() if args.snap_every > 0 else keyboard()))
    try:
        await tasks[0]
        log.info("server closed the connection")
    finally:
        for task in tasks:
            task.cancel()
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", help="server IP; omit to use the discovery beacon")
    parser.add_argument("--port", type=int, default=p.GAME_PORT)
    parser.add_argument("--discovery-port", type=int, default=p.DISCOVERY_PORT)
    parser.add_argument("--player-id", help="pair directly with this player instead of through pairing mode")
    parser.add_argument("--hand", choices=[p.Hand.LEFT, p.Hand.RIGHT], default=p.Hand.RIGHT)
    parser.add_argument("--pinch-on-prompt", action="store_true", help="pinch whenever pairing mode prompts a player")
    parser.add_argument("--snap-every", type=float, default=0.0, help="snap every N seconds instead of reading keys")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
