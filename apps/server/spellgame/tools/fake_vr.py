"""Fake Quest client: streams a synthetic standing pose and, optionally, an overhand throw every few seconds.

python -m spellgame.tools.fake_vr --position 0,0 --facing 0 --throw-every 3
python -m spellgame.tools.fake_vr --position 0,3 --facing 180

It also plays its part in the shared room frame (architecture.md §5.1): as anchor host it "shares" a made-up anchor,
then reports itself aligned to whatever anchor the server announces. Its poses are already in the shared frame.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass

from .. import protocol as p
from ..client import Connection, resolve_server, this_machine
from ..sim import THROW_DURATION_S, standing_pose, throw_hand_offset

log = logging.getLogger("fake_vr")

_PRINTED_EVENTS = (p.Welcome, p.Paired, p.Spell, p.Damage, p.Impact, p.Error)


@dataclass
class FakeAlignment:
    method: str
    """An `AlignMethod`, or `none` to never report alignment."""
    shared_in_group: str | None = None
    aligned_to: str | None = None

    def replies(self, space: p.Space, player_id: str) -> list[p.Message]:
        if self.method == p.AlignMethod.FLOOR_SPOTS:
            if self.aligned_to == space.group_uuid:
                return []
            self.aligned_to = space.group_uuid
            return [p.Aligned(method=p.AlignMethod.FLOOR_SPOTS)]
        if self.method != p.AlignMethod.ANCHOR:
            return []
        if space.anchor_uuid is None:
            if space.host_id != player_id or self.shared_in_group == space.group_uuid:
                return []
            self.shared_in_group = space.group_uuid
            return [p.AnchorShared(anchor_uuid=str(uuid.uuid4()))]
        if self.aligned_to == space.anchor_uuid:
            return []
        self.aligned_to = space.anchor_uuid
        return [p.Aligned(method=p.AlignMethod.ANCHOR, anchor_uuid=space.anchor_uuid)]


async def run(args: argparse.Namespace) -> None:
    host, port = await resolve_server(args.host, args.port, args.discovery_port)
    conn = await Connection.open(host, port)
    welcome = await conn.handshake(p.Role.VR, args.player_id, this_machine("fake_vr"))
    player_id = welcome.player_id
    log.info("connected to %s:%d as %s", host, port, player_id)

    alignment = FakeAlignment(args.align)

    async def print_events() -> None:
        async for message in conn.messages():
            if isinstance(message, p.Space):
                for reply in alignment.replies(message, player_id):
                    log.info("-> %s", p.encode(reply))
                    conn.send(reply)
            if isinstance(message, _PRINTED_EVENTS):
                log.info("<- %s", p.encode(message))
        log.info("server closed the connection")

    reader = asyncio.create_task(print_events())
    position = tuple(float(v) for v in args.position.split(","))
    start = time.monotonic()
    next_throw = args.throw_every
    try:
        while not reader.done():
            now = time.monotonic() - start
            throw_elapsed = None
            if args.throw_every > 0 and now >= next_throw:
                throw_elapsed = now - next_throw
                if throw_elapsed >= THROW_DURATION_S:
                    next_throw += args.throw_every
                    throw_elapsed = None
            hand = throw_hand_offset(throw_elapsed) if throw_elapsed is not None else None
            conn.send(standing_pose(player_id, now, position, args.facing, hand))  # type: ignore[arg-type]
            await conn.writer.drain()
            await asyncio.sleep(1.0 / args.rate)
    finally:
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", help="server IP; omit to use the discovery beacon")
    parser.add_argument("--port", type=int, default=p.GAME_PORT)
    parser.add_argument("--discovery-port", type=int, default=p.DISCOVERY_PORT)
    parser.add_argument("--player-id", help="reclaim this player ID after a reconnect")
    parser.add_argument("--position", default="0,0", help="floor position x,z in metres")
    parser.add_argument("--facing", type=float, default=0.0, help="yaw in degrees, 0 = +z")
    parser.add_argument("--rate", type=float, default=60.0, help="pose send rate in Hz")
    parser.add_argument(
        "--align",
        choices=[p.AlignMethod.ANCHOR, p.AlignMethod.FLOOR_SPOTS, "none"],
        default=p.AlignMethod.ANCHOR,
        help="how to report joining the shared room frame",
    )
    parser.add_argument("--throw-every", type=float, default=0.0, help="seconds between throws; 0 = never")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
