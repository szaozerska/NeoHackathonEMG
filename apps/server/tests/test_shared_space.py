from spellgame import protocol as p
from spellgame.shared_space import SharedSpace, floor_spot
from spellgame.tools.fake_vr import FakeAlignment


def test_floor_spots_face_each_other_across_the_origin():
    assert floor_spot(1, 3.0) == ([0.0, 0.0, -1.5], 0.0)
    assert floor_spot(2, 3.0) == ([0.0, 0.0, 1.5], 180.0)
    assert floor_spot(3, 3.0) == ([-1.5, 0.0, 0.0], 90.0)
    assert floor_spot(4, 3.0) == ([1.5, 0.0, 0.0], 270.0)


def test_host_stays_until_it_leaves_and_only_the_host_shares_the_anchor():
    space = SharedSpace()
    space.choose_host(["P1", "P2"])
    assert space.host_id == "P1"
    space.choose_host(["P2", "P1"])
    assert space.host_id == "P1"
    assert not space.share_anchor("P2", "a")
    assert space.share_anchor("P1", "a")
    space.choose_host(["P2"])
    assert space.host_id == "P2"
    assert space.anchor_uuid == "a"


def test_a_new_anchor_or_reset_unaligns_everyone():
    space = SharedSpace()
    space.choose_host(["P1", "P2"])
    space.share_anchor("P1", "a")
    assert not space.mark_aligned("P2", p.AlignMethod.ANCHOR, "stale")
    assert not space.mark_aligned("P2", "telepathy", "a")
    assert space.mark_aligned("P2", p.AlignMethod.ANCHOR, "a")
    assert space.share_anchor("P1", "a") and space.aligned == {"P2": p.AlignMethod.ANCHOR}
    space.share_anchor("P1", "b")
    assert space.aligned == {}

    group = space.group_uuid
    space.mark_aligned("P2", p.AlignMethod.FLOOR_SPOTS, None)
    space.reset()
    assert space.aligned == {} and space.anchor_uuid is None and space.host_id is None
    assert space.group_uuid != group


def test_mixing_anchor_and_floor_spots_is_flagged():
    space = SharedSpace()
    space.choose_host(["P1"])
    space.share_anchor("P1", "a")
    space.mark_aligned("P1", p.AlignMethod.ANCHOR, "a")
    assert not space.mixed_methods()
    space.mark_aligned("P2", p.AlignMethod.FLOOR_SPOTS, None)
    assert space.mixed_methods()


def test_fake_headset_shares_once_then_aligns_once_per_anchor():
    space = SharedSpace()
    space.choose_host(["P1"])
    host = FakeAlignment(p.AlignMethod.ANCHOR)
    [shared] = host.replies(space.message_for(1), "P1")
    assert isinstance(shared, p.AnchorShared)
    assert host.replies(space.message_for(1), "P1") == []
    space.share_anchor("P1", shared.anchor_uuid)
    assert host.replies(space.message_for(1), "P1") == [p.Aligned(p.AlignMethod.ANCHOR, shared.anchor_uuid)]
    assert host.replies(space.message_for(1), "P1") == []
    guest = FakeAlignment(p.AlignMethod.ANCHOR)
    assert guest.replies(space.message_for(2), "P2") == [p.Aligned(p.AlignMethod.ANCHOR, shared.anchor_uuid)]
