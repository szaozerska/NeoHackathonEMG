"""Runs the game server with its live monitor, or with plain logging (`--no-tui`)."""

from __future__ import annotations

import argparse
import asyncio
import atexit
import contextlib
import logging
import shutil
import subprocess
from pathlib import Path

from . import protocol as p
from .server import GameServer
from .shared_space import FLOOR_SPOT_DISTANCE_M
from .tui import ServerMonitor


async def _serve_headless(server: GameServer) -> None:
    await server.start()
    try:
        await asyncio.Event().wait()
    finally:
        await server.stop()


log = logging.getLogger(__name__)

HAND_CLIENT_DIR = Path(__file__).resolve().parents[2] / "hand-client"
HAND_CLIENT_LOG = HAND_CLIENT_DIR / "hand-client.log"


def _start_hand_client(port: int) -> None:
    """Runs the hand-client for this laptop's band in the background, connected straight to this server; it picks the
    Kinesis stream URL up from the clipboard. Its log goes to `apps/hand-client/hand-client.log`."""
    uv = shutil.which("uv")
    if uv is None or not HAND_CLIENT_DIR.is_dir():
        log.warning("not starting the hand-client: uv or %s is missing", HAND_CLIENT_DIR)
        return
    log_file = HAND_CLIENT_LOG.open("a")
    process = subprocess.Popen(
        [
            uv,
            "run",
            "--project",
            str(HAND_CLIENT_DIR),
            "python",
            "-m",
            "handclient",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=HAND_CLIENT_DIR,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    atexit.register(process.terminate)
    log.info("hand-client started (log: %s); click 'copy stream URL' in Kinesis's stream tab", HAND_CLIENT_LOG)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=p.GAME_PORT)
    parser.add_argument("--tick-hz", type=float, default=30.0)
    parser.add_argument("--discovery-port", type=int, default=p.DISCOVERY_PORT)
    parser.add_argument("--beacon-address", default="255.255.255.255")
    parser.add_argument("--no-beacon", action="store_true")
    parser.add_argument(
        "--spot-distance", type=float, default=FLOOR_SPOT_DISTANCE_M, help="metres between the marked floor spots"
    )
    parser.add_argument("--no-tui", action="store_true", help="log to stderr instead of showing the live monitor")
    parser.add_argument(
        "--no-hand-client",
        action="store_true",
        help="don't start the Neural Band hand-client (apps/hand-client) alongside the server",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    if not args.no_hand_client:
        _start_hand_client(args.port)
    server = GameServer(
        host=args.host,
        port=args.port,
        tick_hz=args.tick_hz,
        discovery_port=args.discovery_port,
        beacon_address=None if args.no_beacon else args.beacon_address,
        spot_distance=args.spot_distance,
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
