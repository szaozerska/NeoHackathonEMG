"""Terminal prompt listing the game servers beaconing on the LAN (architecture.md §4.1), so the user can pick one."""

from __future__ import annotations

import asyncio

from spellgame.discovery import discover_servers
from spellgame.protocol import GAME_PORT

Server = tuple[str, int]


def pick_server(discovery_port: int, listen_s: float) -> Server:
    while True:
        print(f"Looking for game servers for {listen_s:.0f} s…")
        servers = asyncio.run(discover_servers(discovery_port, listen_s))
        for number, (host, port) in enumerate(servers, start=1):
            print(f"  [{number}] {host}:{port}")
        if not servers:
            print("  none found")
        choice = parse_choice(input("Server number, an IP[:port], or Enter to rescan: "), servers)
        if choice is not None:
            return choice


def parse_choice(answer: str, servers: list[Server]) -> Server | None:
    """The chosen server, or None to rescan (empty or unusable answer)."""
    answer = answer.strip()
    if not answer:
        return None
    if answer.isdigit():
        if 1 <= int(answer) <= len(servers):
            return servers[int(answer) - 1]
        print(f"No server [{answer}].")
        return None
    host, _, port = answer.partition(":")
    if port and not port.isdigit():
        print(f"Bad port {port!r}.")
        return None
    return host, int(port) if port else GAME_PORT
