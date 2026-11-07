"""UDP discovery (architecture.md §4.1): the server broadcasts `SPELLGAME <tcp_port>` once per second."""

from __future__ import annotations

import asyncio
import logging
import socket

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


async def find_server(discovery_port: int = DISCOVERY_PORT, timeout_s: float | None = None) -> tuple[str, int]:
    """Wait for a beacon and return (server_ip, tcp_port). The IP is the packet's sender address."""
    loop = asyncio.get_running_loop()
    found: asyncio.Future[tuple[str, int]] = loop.create_future()

    class _Listener(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            tcp_port = parse_beacon(data)
            if tcp_port is not None and not found.done():
                found.set_result((addr[0], tcp_port))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("", discovery_port))
    transport, _ = await loop.create_datagram_endpoint(_Listener, sock=sock)
    try:
        return await asyncio.wait_for(found, timeout_s)
    finally:
        transport.close()
