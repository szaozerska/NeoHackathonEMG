"""Live server monitor: the connected headsets and hand clients, their device info and their most recent packets."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, RichLog, Static

from . import protocol as p
from .server import ClientConnection, GameServer
from .shared_space import SharedSpace

PACKETS_SHOWN = 8
REFRESH_S = 0.2


def _clock(unix_time: float) -> str:
    return datetime.fromtimestamp(unix_time).strftime("%H:%M:%S.%f")[:-3]


def _metadata(conn: ClientConnection, space: SharedSpace | None = None) -> Table:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("player", conn.player_id or Text("unpaired", style="yellow"))
    if space is not None and conn.role == p.Role.VR:
        grid.add_row("space", _space_status(conn.player_id, space))
    grid.add_row("peer", f"{conn.peer[0]}:{conn.peer[1]}")
    if conn.device is None:
        grid.add_row("device", Text("not reported", style="dim italic"))
    else:
        grid.add_row("device", conn.device.name)
        for label, value in (("model", conn.device.model), ("id", conn.device.id)):
            if value is not None:
                grid.add_row(label, value)
    grid.add_row("since", _clock(conn.connected_at))
    grid.add_row("received", f"{conn.packets_received} packets")
    return grid


def _space_status(player_id: str | None, space: SharedSpace) -> Text:
    host = " · anchor host" if player_id is not None and player_id == space.host_id else ""
    method = space.aligned.get(player_id) if player_id else None
    if method is None:
        return Text(f"not aligned{host}", style="yellow")
    return Text(f"aligned ({method}){host}", style="green")


def _recent_packets(conn: ClientConnection) -> Table:
    table = Table(show_edge=False, box=None, padding=(0, 1), expand=True, header_style="bold dim")
    table.add_column("time", no_wrap=True)
    table.add_column("type", no_wrap=True, style="bold cyan")
    table.add_column("fields", no_wrap=True, overflow="ellipsis", ratio=1)
    for packet in list(conn.recent_packets)[-PACKETS_SHOWN:]:
        fields = {name: value for name, value in packet.message.to_dict().items() if name != "type"}
        table.add_row(_clock(packet.received_at), packet.message.TYPE, json.dumps(fields, separators=(",", ":")))
    return table


def render_client(conn: ClientConnection, prompted: bool, space: SharedSpace | None = None) -> Panel:
    body = Group(_metadata(conn, space), _recent_packets(conn))
    title = conn.player_id or "unpaired"
    if not prompted:
        return Panel(body, title=title, title_align="left")
    return Panel(body, title=f"{title} · pinch now", title_align="left", border_style="bold yellow")


def render_clients(
    connections: list[ClientConnection], prompted_player_id: str | None, space: SharedSpace | None = None
) -> RenderableType:
    if not connections:
        return Text("none connected", style="dim italic")
    return Group(*(render_client(conn, _is_prompted(conn, prompted_player_id), space) for conn in connections))


def _is_prompted(conn: ClientConnection, prompted_player_id: str | None) -> bool:
    return prompted_player_id is not None and conn.player_id == prompted_player_id


class ClientList(Static):
    def __init__(self, server: GameServer, role: str) -> None:
        super().__init__()
        self._server = server
        self._role = role

    def show_latest(self) -> None:
        connections = sorted(
            (conn for conn in self._server.connections if conn.role == self._role), key=lambda c: c.connected_at
        )
        self.update(render_clients(connections, self._server.prompted_player_id, self._server.space))


class PairingBanner(Static):
    def __init__(self, server: GameServer) -> None:
        super().__init__(id="pairing")
        self._server = server

    def show_latest(self) -> None:
        self.display = self._server.prompted_player_id is not None
        self.update(f"PAIRING MODE · {self._server.prompted_player_id}, pinch your fingers")


class LogPaneHandler(logging.Handler):
    def __init__(self, pane: RichLog) -> None:
        super().__init__()
        self._pane = pane

    def emit(self, record: logging.LogRecord) -> None:
        self._pane.write(self.format(record))


class ServerMonitor(App[None]):
    """Owns the server's lifetime so every log line from startup on lands in the log pane."""

    TITLE = "spellgame server"
    CSS = """
    #pairing { background: $warning; color: $background; text-style: bold; padding: 0 1; display: none; }
    #clients { height: 3fr; }
    .column { width: 1fr; border: round $primary; }
    #log { height: 1fr; border: round $secondary; }
    """
    BINDINGS = [("p", "start_pairing", "Pairing mode"), ("a", "reset_space", "Re-anchor"), ("q", "quit", "Quit")]

    def __init__(self, server: GameServer) -> None:
        super().__init__()
        self._server = server
        self._lists = [ClientList(server, p.Role.VR), ClientList(server, p.Role.CLASSIFIER)]
        self._pairing_banner = PairingBanner(server)
        self._log_pane = RichLog(id="log", max_lines=2000)
        self._log_handler = LogPaneHandler(self._log_pane)
        self._log_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))

    def compose(self) -> ComposeResult:
        yield Header()
        yield self._pairing_banner
        with Horizontal(id="clients"):
            for client_list, title in zip(self._lists, ("Headsets (VR)", "Hand clients"), strict=True):
                column = VerticalScroll(client_list, classes="column")
                column.border_title = title
                yield column
        yield self._log_pane
        yield Footer()

    async def on_mount(self) -> None:
        self._log_pane.border_title = "Log"
        logging.getLogger().addHandler(self._log_handler)
        await self._server.start()
        self.sub_title = f"TCP {self._server.host}:{self._server.port}"
        self.set_interval(REFRESH_S, self._show_latest)

    async def on_unmount(self) -> None:
        await self._server.stop()
        logging.getLogger().removeHandler(self._log_handler)

    def action_start_pairing(self) -> None:
        self._server.start_pairing()
        self._show_latest()

    def action_reset_space(self) -> None:
        self._server.reset_space()
        self._show_latest()

    def _show_latest(self) -> None:
        self._pairing_banner.show_latest()
        for client_list in self._lists:
            client_list.show_latest()
