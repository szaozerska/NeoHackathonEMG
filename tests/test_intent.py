from spelltrain.intent import FireballOption


def test_snap_equips_without_open_confirmation_and_open_preserves_equipment():
    f=FireballOption()
    assert f.snap(0,'a')[0]['event']=='fireball_equipped'
    assert f.phase=='ready'
    assert not f.state('open',.1)
    assert not f.expire(20)
    assert f.phase=='ready'
    assert not f.commit(21)
    assert not f.commit(21,tracked_forward_throw=True,open_hand=False)
    assert f.commit(21,tracked_forward_throw=True,open_hand=True)[0]['event']=='fireball_commit'


def test_fist_cancels_immediately_or_after_long_open_hold_and_duplicate_cannot_rearm():
    for delay in (.1,20.):
        f=FireballOption();f.snap(0,'a')
        if delay>1:f.state('open',.1)
        assert f.state('fist',delay)[0]['event']=='fireball_cancel'
        assert f.phase=='idle'
        assert not f.snap(delay+.01,'a')
        assert not f.state('open',delay+.02)
        assert f.phase=='idle'


def test_snap_is_new_equipment_even_if_previous_window_was_fist():
    f=FireballOption();f.state('fist',0)
    assert f.snap(.1,'a',fist_confirmed=True)[0]['event']=='fireball_equipped'
    assert f.phase=='ready'
    # A stale or same-timestamp fist cannot cancel; a subsequent confirmed fist can.
    assert not f.state('fist',.1)
    assert f.state('fist',.2)[0]['event']=='fireball_cancel'


def test_shield_requires_explicit_confirmation_ordinary_open_keeps_fireball():
    f=FireballOption();f.snap(1,'a')
    assert not f.state('open',2)
    assert not f.shield(2)
    assert f.phase=='ready'
    assert f.shield(3,confirmed=True)[0]['reason']=='shield'
    assert f.phase=='idle'
    assert not f.snap(4,'a')
