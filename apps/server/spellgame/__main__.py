"""Runs the game server with its live monitor, or with plain logging (`--no-tui`)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging

from . import protocol as p
from .server import GameServer
from .tui import ServerMonitor


async def _serve_headless(server: GameServer) -> None:
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
    parser.add_argument("--no-tui", action="store_true", help="log to stderr instead of showing the live monitor")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    server = GameServer(
        host=args.host,
        port=args.port,
        tick_hz=args.tick_hz,
        discovery_port=args.discovery_port,
        beacon_address=None if args.no_beacon else args.beacon_address,
    )
    level = logging.DEBUG if args.verbose else logging.INFO
    if not args.no_tui:
        logging.getLogger().setLevel(level)
        ServerMonitor(server).run()
        return
    logging.basicConfig(level=level, format="%(asctime)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve_headless(server))


main()
