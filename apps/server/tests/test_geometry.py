import numpy as np
import pytest

from spellgame.geometry import body_forward, quat_rotate, segment_distance
from spellgame.sim import standing_pose, yaw_rotation


def v(*values):
    return np.array(values, dtype=float)


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        ((v(0, 0, 0), v(1, 0, 0), v(0, 1, 0), v(1, 1, 0)), 1.0),
        ((v(0, 0, 0), v(2, 0, 0), v(1, -1, 1), v(1, 1, 1)), 1.0),
        ((v(0, 0, 0), v(1, 0, 0), v(3, 0, 0), v(4, 0, 0)), 2.0),
        ((v(0, 0, 0), v(0, 0, 0), v(0, 2, 0), v(0, 2, 0)), 2.0),
    ],
)
def test_segment_distance(segments, expected):
    assert segment_distance(*segments) == pytest.approx(expected)


def test_quat_rotate_matches_unity_yaw():
    assert quat_rotate(yaw_rotation(90), v(0, 0, 1)) == pytest.approx(v(1, 0, 0))


@pytest.mark.parametrize("facing", [0, 90, 180, -45])
def test_body_forward_from_shoulders(facing):
    expected = quat_rotate(yaw_rotation(facing), v(0, 0, 1))
    assert body_forward(standing_pose("P1", 0, facing_deg=facing).joints) == pytest.approx(expected, abs=1e-3)
