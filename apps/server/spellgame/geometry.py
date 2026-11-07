"""Vector helpers in Unity's frame: left-handed, +y up, +z forward, metres."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from .protocol import Joint

UP = np.array([0.0, 1.0, 0.0])
FORWARD = np.array([0.0, 0.0, 1.0])
_EPSILON = 1e-9


def vec(values: Sequence[float]) -> np.ndarray:
    return np.asarray(values, dtype=float)


def normalize(v: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(v))
    return v / length if length > _EPSILON else np.zeros(3)


def quat_rotate(rot_wxyz: Sequence[float], v: np.ndarray) -> np.ndarray:
    w, x, y, z = rot_wxyz
    q = np.array([x, y, z], dtype=float)
    t = 2.0 * np.cross(q, v)
    return v + w * t + np.cross(q, t)


def body_forward(joints: Mapping[str, Joint]) -> np.ndarray:
    """Horizontal facing direction, from the shoulder line (or the head if shoulders are missing)."""
    if "l_shoulder" in joints and "r_shoulder" in joints:
        right = vec(joints["r_shoulder"].pos) - vec(joints["l_shoulder"].pos)
        right[1] = 0.0
        forward = normalize(np.cross(right, UP))
        if forward.any():
            return forward
    if "head" in joints:
        forward = quat_rotate(joints["head"].rot, FORWARD)
        forward[1] = 0.0
        return normalize(forward)
    return FORWARD.copy()


def body_right(joints: Mapping[str, Joint]) -> np.ndarray:
    """Horizontal direction to the player's right."""
    return np.cross(UP, body_forward(joints))


def closest_point_on_segment(point: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    length_sq = float(ab @ ab)
    if length_sq <= _EPSILON:
        return a.copy()
    return a + ab * float(np.clip((point - a) @ ab / length_sq, 0.0, 1.0))


def segment_distance(p1: np.ndarray, q1: np.ndarray, p2: np.ndarray, q2: np.ndarray) -> float:
    """Shortest distance between segments p1-q1 and p2-q2 (Ericson, Real-Time Collision Detection §5.1.9)."""
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a, e, f = float(d1 @ d1), float(d2 @ d2), float(d2 @ r)
    if a <= _EPSILON and e <= _EPSILON:
        return float(np.linalg.norm(r))
    if a <= _EPSILON:
        s, t = 0.0, float(np.clip(f / e, 0.0, 1.0))
    else:
        c = float(d1 @ r)
        if e <= _EPSILON:
            s, t = float(np.clip(-c / a, 0.0, 1.0)), 0.0
        else:
            b = float(d1 @ d2)
            denom = a * e - b * b
            s = float(np.clip((b * f - c * e) / denom, 0.0, 1.0)) if denom > _EPSILON else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                s, t = float(np.clip(-c / a, 0.0, 1.0)), 0.0
            elif t > 1.0:
                s, t = float(np.clip((b - c) / a, 0.0, 1.0)), 1.0
    return float(np.linalg.norm((p1 + d1 * s) - (p2 + d2 * t)))
