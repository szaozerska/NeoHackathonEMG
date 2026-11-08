"""Shared room frame for co-located headsets (architecture.md §5.1).

The server never transforms poses: each headset aligns its own tracking space to the shared frame and then streams
poses in it. The server's job is the bookkeeping: which headset hosts the Shared Spatial Anchor, which anchor is
current, which Meta group UUID to share and load it through, and which headsets have reported they're aligned.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

from . import protocol as p

FLOOR_SPOT_DISTANCE_M = 3.0
"""How far apart the two marked floor spots are, for the `floor_spots` fallback."""


def floor_spot(join_order: int, distance: float = FLOOR_SPOT_DISTANCE_M) -> tuple[list[float], float]:
    """Where a player stands and which way they face (yaw in degrees, 0 = +z) at the start, in the shared frame.

    P1 and P2 face each other across the origin along z; players 3 and 4 stand on the x axis, facing the origin.
    """
    index = (join_order - 1) % 4
    angle = math.pi * index if index < 2 else math.pi / 2 + math.pi * (index - 2)
    radius = distance / 2
    pos = [round(-radius * math.sin(angle), 3) + 0.0, 0.0, round(-radius * math.cos(angle), 3) + 0.0]
    yaw = math.degrees(angle) % 360
    return pos, yaw


@dataclass
class SharedSpace:
    spot_distance: float = FLOOR_SPOT_DISTANCE_M
    group_uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    host_id: str | None = None
    """The headset that creates and shares the anchor: the first connected headset, kept until it leaves."""
    anchor_uuid: str | None = None
    aligned: dict[str, str] = field(default_factory=dict)
    """Player ID to the `AlignMethod` they aligned with, for headsets aligned to the current frame."""

    def choose_host(self, connected_ids: list[str]) -> None:
        """Keeps the host while it's connected; once the anchor is shared, it lives on without its host."""
        if self.host_id in connected_ids:
            return
        self.host_id = connected_ids[0] if connected_ids else None

    def share_anchor(self, player_id: str, anchor_uuid: str) -> bool:
        if player_id != self.host_id:
            return False
        if anchor_uuid != self.anchor_uuid:
            self.anchor_uuid = anchor_uuid
            self.aligned.clear()
        return True

    def mark_aligned(self, player_id: str, method: str, anchor_uuid: str | None) -> bool:
        if method == p.AlignMethod.ANCHOR and (anchor_uuid is None or anchor_uuid != self.anchor_uuid):
            return False
        if method not in (p.AlignMethod.ANCHOR, p.AlignMethod.FLOOR_SPOTS, p.AlignMethod.CENTER):
            return False
        self.aligned[player_id] = method
        return True

    def forget(self, player_id: str) -> None:
        self.aligned.pop(player_id, None)

    def reset(self) -> None:
        """Re-anchor from scratch, e.g. after a headset lost tracking: new group, no anchor, nobody aligned."""
        self.group_uuid = str(uuid.uuid4())
        self.host_id = None
        self.anchor_uuid = None
        self.aligned.clear()

    def mixed_methods(self) -> bool:
        """Anchor-aligned and floor-spot-aligned headsets don't share a frame."""
        return len(set(self.aligned.values())) > 1

    def message_for(self, join_order: int) -> p.Space:
        pos, yaw = floor_spot(join_order, self.spot_distance)
        return p.Space(
            group_uuid=self.group_uuid,
            host_id=self.host_id,
            anchor_uuid=self.anchor_uuid,
            spot_pos=pos,
            spot_yaw=yaw,
        )
