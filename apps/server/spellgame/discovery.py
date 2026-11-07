"""UDP discovery (architecture.md §4.1): the server broadcasts `SPELLGAME <tcp_port>` once per second."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from collections.abc import AsyncIterator, Callable

from .protocol import BEACON_PREFIX, DISCOVERY_PORT

log = logging.getLogger(__name__)


class _BeaconProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self._reported_error = False

    def error_received(self, exc: Exception) -> None:
        if not self._reported_error:
            log.warning("discovery beacon send failed (clients can still use a manual IP): %s", exc)
            self._reported_error = True


async def run_beacon(
    tcp_port: int,
    discovery_port: int = DISCOVERY_PORT,
    address: str = "255.255.255.255",
    interval_s: float = 1.0,
) -> None:
    """Broadcast the beacon until cancelled."""
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _BeaconProtocol, local_addr=("0.0.0.0", 0), allow_broadcast=True
    )
    payload = f"{BEACON_PREFIX}{tcp_port}".encode()
    log.info("discovery beacon: %r to %s:%d every %.1fs", payload.decode(), address, discovery_port, interval_s)
    try:
        while True:
            try:
                transport.sendto(payload, (address, discovery_port))
            except OSError as exc:
                protocol.error_received(exc)
            await asyncio.sleep(interval_s)
    finally:
        transport.close()


def parse_beacon(payload: bytes) -> int | None:
    text = payload.decode(errors="replace").strip()
    if not text.startswith(BEACON_PREFIX):
        return None
    try:
        return int(text[len(BEACON_PREFIX) :])
    except ValueError:
        return None


@contextlib.asynccontextmanager
async def _listen_for_beacons(discovery_port: int, on_beacon: Callable[[str, int], None]) -> AsyncIterator[None]:
    """Calls `on_beacon(server_ip, tcp_port)` for every beacon while the context is open."""
    loop = asyncio.get_running_loop()

    class _Listener(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            tcp_port = parse_beacon(data)
            if tcp_port is not None:
                on_beacon(addr[0], tcp_port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("", discovery_port))
    transport, _ = await loop.create_datagram_endpoint(_Listener, sock=sock)
    try:
        yield
    finally:
        transport.close()


async def find_server(discovery_port: int = DISCOVERY_PORT, timeout_s: float | None = None) -> tuple[str, int]:
    """Wait for a beacon and return (server_ip, tcp_port). The IP is the packet's sender address."""
    found: asyncio.Future[tuple[str, int]] = asyncio.get_running_loop().create_future()

    def on_beacon(server_ip: str, tcp_port: int) -> None:
        if not found.done():
            found.set_result((server_ip, tcp_port))

    async with _listen_for_beacons(discovery_port, on_beacon):
        return await asyncio.wait_for(found, timeout_s)


async def discover_servers(discovery_port: int = DISCOVERY_PORT, listen_s: float = 2.5) -> list[tuple[str, int]]:
    """Every distinct (server_ip, tcp_port) that beaconed within `listen_s`, in the order first heard."""
    servers: dict[tuple[str, int], None] = {}
    async with _listen_for_beacons(
        discovery_port, lambda server_ip, tcp_port: servers.setdefault((server_ip, tcp_port))
    ):
        await asyncio.sleep(listen_s)
    return list(servers)
