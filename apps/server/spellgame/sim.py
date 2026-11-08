"""Synthetic body poses and gesture motion for fake clients and tests (no headset needed)."""

from __future__ import annotations

import math

import numpy as np

from . import protocol as p

_STANDING = {
    "head": (0.0, 1.65, 0.0),
    "chest": (0.0, 1.35, 0.0),
    "hips": (0.0, 1.0, 0.0),
    "l_shoulder": (-0.18, 1.45, 0.0),
    "r_shoulder": (0.18, 1.45, 0.0),
    "l_elbow": (-0.25, 1.15, 0.05),
    "r_elbow": (0.25, 1.15, 0.1),
    "l_wrist": (-0.25, 0.97, 0.2),
    "r_wrist": (0.25, 1.1, 0.25),
    "l_hand": (-0.25, 0.95, 0.25),
    "r_hand": (0.25, 1.1, 0.3),
    "l_knee": (-0.1, 0.5, 0.02),
    "r_knee": (0.1, 0.5, 0.02),
    "l_ankle": (-0.1, 0.08, 0.0),
    "r_ankle": (0.1, 0.08, 0.0),
    "l_foot": (-0.1, 0.02, 0.14),
    "r_foot": (0.1, 0.02, 0.14),
}

HAND_IDLE = np.array(_STANDING["r_hand"])
_WINDUP = np.array([0.3, 1.6, -0.15])
_FOLLOW_THROUGH = np.array([0.2, 1.5, 0.6])

THROW_DURATION_S = 0.8
"""Backswing 0-0.4, throw 0.4-0.52, return 0.52-0.8 (fractions of the duration)."""


def yaw_rotation(facing_deg: float) -> list[float]:
    half = math.radians(facing_deg) / 2.0
    return [math.cos(half), 0.0, math.sin(half), 0.0]


def rotate_yaw(offset: np.ndarray, facing_deg: float) -> np.ndarray:
    """Rotate about +y the way Unity does: +90 deg turns +z (forward) into +x (right)."""
    angle = math.radians(facing_deg)
    x, y, z = offset
    return np.array([x * math.cos(angle) + z * math.sin(angle), y, -x * math.sin(angle) + z * math.cos(angle)])


def standing_pose(
    player_id: str | None,
    t: float,
    position: tuple[float, float] = (0.0, 0.0),
    facing_deg: float = 0.0,
    right_hand: np.ndarray | None = None,
) -> p.Pose:
    """A player standing at floor position (x, z), facing `facing_deg` (0 = +z), right hand at a local offset."""
    origin = np.array([position[0], 0.0, position[1]])
    rot = yaw_rotation(facing_deg)
    joints = {}
    for name, local in _STANDING.items():
        offset = np.array(local)
        if right_hand is not None and name == "r_hand":
            offset = right_hand
        elif right_hand is not None and name == "r_wrist":
            offset = right_hand - np.array([0.0, 0.0, 0.05])
        world = origin + rotate_yaw(offset, facing_deg)
        joints[name] = p.Joint(pos=[round(float(v), 4) for v in world], rot=list(rot))
    return p.Pose(player_id=player_id, t=t, joints=joints)


def _smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def throw_hand_offset(elapsed_s: float) -> np.ndarray:
    """Local right-hand offset `elapsed_s` into an overhand throw (backswing, fast forward throw, return)."""
    phase = elapsed_s / THROW_DURATION_S
    if phase <= 0.0 or phase >= 1.0:
        return HAND_IDLE.copy()
    if phase < 0.4:
        return HAND_IDLE + (_WINDUP - HAND_IDLE) * _smoothstep(phase / 0.4)
    if phase < 0.52:
        return _WINDUP + (_FOLLOW_THROUGH - _WINDUP) * _smoothstep((phase - 0.4) / 0.12)
    return _FOLLOW_THROUGH + (HAND_IDLE - _FOLLOW_THROUGH) * _smoothstep((phase - 0.52) / 0.48)


SWORD_POCKET_HAND = np.array([-0.12, 0.98, 0.1])
"""Right hand at the left pocket (the hips are at (0, 1.0, 0))."""
SWORD_DRAWN_HAND = np.array([0.3, 1.3, 0.3])
SWORD_DRAW_DURATION_S = 0.3
SWORD_SWING_FROM = np.array([0.55, 1.25, 0.4])
SWORD_SWING_TO = np.array([-0.45, 1.25, 0.4])


def sword_draw_hand_offset(elapsed_s: float) -> np.ndarray:
    """Local right-hand offset `elapsed_s` into a draw: up and across from the left pocket."""
    x = _smoothstep(elapsed_s / SWORD_DRAW_DURATION_S)
    return SWORD_POCKET_HAND + (SWORD_DRAWN_HAND - SWORD_POCKET_HAND) * x


def sword_swing_hand_offset(elapsed_s: float, duration_s: float = 0.25) -> np.ndarray:
    """Local right-hand offset `elapsed_s` into a horizontal right-to-left slash at chest height."""
    x = min(max(elapsed_s / duration_s, 0.0), 1.0)
    return SWORD_SWING_FROM + (SWORD_SWING_TO - SWORD_SWING_FROM) * x
