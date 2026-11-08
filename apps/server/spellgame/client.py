"""Client-side connection helpers, shared by the fake clients and the hand-sign client."""

from __future__ import annotations

import asyncio
import logging
import platform
import socket
from collections.abc import AsyncIterator

from . import protocol as p
from .discovery import find_server

log = logging.getLogger(__name__)


class Connection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    @classmethod
    async def open(cls, host: str, port: int) -> Connection:
        reader, writer = await asyncio.open_connection(host, port)
        writer.get_extra_info("socket").setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return cls(reader, writer)

    def send(self, message: p.Message) -> None:
        self.writer.write(p.encode_line(message))

    async def receive(self) -> p.Message | None:
        line = await self.reader.readline()
        return p.decode(line) if line else None

    async def messages(self) -> AsyncIterator[p.Message]:
        while (message := await self.receive()) is not None:
            yield message

    async def handshake(self, role: str, player_id: str | None = None, device: p.DeviceInfo | None = None) -> p.Welcome:
        self.send(p.Hello(role=role, player_id=player_id, device=device))
        reply = await self.receive()
        if not isinstance(reply, p.Welcome):
            raise ConnectionError(f"expected welcome, got {reply!r}")
        return reply

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except OSError:
            pass


def this_machine(program: str) -> p.DeviceInfo:
    return p.DeviceInfo(name=f"{program}@{socket.gethostname()}", model=f"{platform.system()} {platform.machine()}")


async def resolve_server(host: str | None, port: int, discovery_port: int) -> tuple[str, int]:
    if host:
        return host, port
    log.info("waiting for discovery beacon on UDP %d…", discovery_port)
    return await find_server(discovery_port)
