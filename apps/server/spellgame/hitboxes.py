"""Per-body-part hitboxes built from a player's tracked joints (architecture.md §9.1).

Like ragdoll/physics-asset hitboxes: a sphere for the head and a capsule per body segment, each tagged with a
`protocol.Zone`, so leaning the head out of a fireball's path dodges it while the arms still take hits.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from . import protocol as p
from .geometry import UP, segment_closest_points, vec


@dataclass
class HitboxSizes:
    """Radii in metres; spells add their own radius on top."""

    head: float = 0.11
    head_center_up: float = 0.08
    """The head joint sits low in the skull; the head sphere is centred this far above it."""
    torso: float = 0.14
    """Capsule from chest to hips."""
    shoulders: float = 0.09
    """Capsule across the shoulders, so the upper body is wider than the waist."""
    upper_arm: float = 0.06
    forearm: float = 0.05
    hand: float = 0.06
    thigh: float = 0.08
    shin: float = 0.06
    head_to_chest: float = 0.3
    """Fallbacks for poses without a chest or hips joint."""
    chest_to_hips: float = 0.35


@dataclass(frozen=True)
class Hitbox:
    """A capsule from `a` to `b` (a sphere when they coincide)."""

    zone: str
    a: np.ndarray
    b: np.ndarray
    radius: float


@dataclass(frozen=True)
class Contact:
    zone: str
    pos: np.ndarray
    """Point on the attacking segment closest to the body part that was hit."""


_SEGMENTS: Sequence[tuple[str, str, str, str]] = (
    (p.Zone.TORSO, "l_shoulder", "r_shoulder", "shoulders"),
    *(
        segment
        for side in ("l", "r")
        for segment in (
            (p.Zone.ARM, f"{side}_shoulder", f"{side}_elbow", "upper_arm"),
            (p.Zone.ARM, f"{side}_elbow", f"{side}_wrist", "forearm"),
            (p.Zone.ARM, f"{side}_hand", f"{side}_hand", "hand"),
            (p.Zone.LEG, "hips", f"{side}_knee", "thigh"),
            (p.Zone.LEG, f"{side}_knee", f"{side}_ankle", "shin"),
        )
    ),
)


def body_hitboxes(joints: Mapping[str, p.Joint], sizes: HitboxSizes) -> list[Hitbox]:
    """Hitboxes for every body part whose joints are in the pose."""
    pos = {name: vec(joint.pos) for name, joint in joints.items()}
    boxes: list[Hitbox] = []
    if "head" in pos:
        center = pos["head"] + UP * sizes.head_center_up
        boxes.append(Hitbox(p.Zone.HEAD, center, center, sizes.head))
    chest = pos.get("chest")
    if chest is None and "head" in pos:
        chest = pos["head"] - UP * sizes.head_to_chest
    if chest is not None:
        hips = pos["hips"] if "hips" in pos else chest - UP * sizes.chest_to_hips
        boxes.append(Hitbox(p.Zone.TORSO, chest, hips, sizes.torso))
    for zone, a, b, size in _SEGMENTS:
        if a in pos and b in pos:
            boxes.append(Hitbox(zone, pos[a], pos[b], getattr(sizes, size)))
    return boxes


def body_contact(boxes: Sequence[Hitbox], a: np.ndarray, b: np.ndarray, radius: float) -> Contact | None:
    """The body part a capsule a-b of `radius` (a swept fireball, a blade) overlaps most deeply, or None."""
    best: tuple[float, Contact] | None = None
    for box in boxes:
        on_attack, on_box = segment_closest_points(a, b, box.a, box.b)
        depth = radius + box.radius - float(np.linalg.norm(on_attack - on_box))
        if depth >= 0.0 and (best is None or depth > best[0]):
            best = (depth, Contact(box.zone, on_attack))
    return best[1] if best else None
