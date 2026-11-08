import numpy as np
import pytest

from spellgame import protocol as p
from spellgame.hitboxes import HitboxSizes, body_contact, body_hitboxes
from spellgame.sim import standing_pose

FIREBALL_RADIUS = 0.1


def boxes(drop=(), **moved):
    """Hitboxes of a player standing at the origin facing +z, with some joints moved or dropped."""
    joints = dict(standing_pose("P2", 0.0).joints)
    for name, pos in moved.items():
        joints[name] = p.Joint(pos=list(pos), rot=[1.0, 0.0, 0.0, 0.0])
    for name in drop:
        del joints[name]
    return body_hitboxes(joints, HitboxSizes())


def shot(hitboxes, x, y):
    """A fireball flying straight through the player's plane at lateral offset x and height y."""
    return body_contact(hitboxes, np.array([x, y, -2.0]), np.array([x, y, 2.0]), FIREBALL_RADIUS)


@pytest.mark.parametrize(
    ("x", "y", "zone"),
    [
        (0.0, 1.75, p.Zone.HEAD),
        (0.0, 1.2, p.Zone.TORSO),
        (0.3, 1.45, p.Zone.TORSO),
        (-0.25, 1.05, p.Zone.ARM),
        (0.1, 0.3, p.Zone.LEG),
    ],
)
def test_each_body_part_reports_its_zone(x, y, zone):
    contact = shot(boxes(), x, y)
    assert contact is not None and contact.zone == zone
    assert contact.pos[1] == pytest.approx(y)


@pytest.mark.parametrize(
    ("x", "y"),
    [
        (0.25, 1.75),  # beside the head, inside the old head-to-hips capsule
        (0.32, 0.9),  # beside the waist, under the hand
        (0.0, 1.95),  # over the head
    ],
)
def test_near_misses_that_the_old_body_capsule_counted(x, y):
    assert shot(boxes(), x, y) is None


def test_leaning_the_head_aside_dodges_a_head_shot():
    assert shot(boxes(), 0.0, 1.75).zone == p.Zone.HEAD
    assert shot(boxes(head=(0.3, 1.6, 0.0)), 0.0, 1.75) is None


def test_deepest_overlap_wins():
    contact = body_contact(boxes(), np.array([0.0, 1.45, -2.0]), np.array([0.0, 1.45, 2.0]), FIREBALL_RADIUS)
    assert contact.zone == p.Zone.TORSO


def test_head_only_pose_still_has_a_torso():
    hitboxes = boxes(drop=[name for name in standing_pose(None, 0.0).joints if name != "head"])
    assert {box.zone for box in hitboxes} == {p.Zone.HEAD, p.Zone.TORSO}
    assert shot(hitboxes, 0.0, 1.2).zone == p.Zone.TORSO
