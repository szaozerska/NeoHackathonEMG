import numpy as np
from spelltrain.fusion import SpellEngine


def pose(local=(.2,-.1,.3),valid=True,palm=(0,0,1),frame='one'):
    return {'hand':{'pos':(np.asarray(local)+[0,1.4,0]).tolist(),'rot':[1,0,0,0],
                    'finger_direction':[0,1,0], 'palm_normal':list(palm),'valid':valid,'confidence':1},
            'chest':{'pos':[0,1.4,0],'rot':[1,0,0,0],'valid':True,'confidence':1},
            'opponent_direction':[0,0,1],'frame_id':frame}


def test_sword_is_immediate_at_any_angle_without_hip_or_draw():
    for rotation in ([1,0,0,0], [0,1,0,0], [.7071,0,0,.7071]):
        e=SpellEngine()
        packet=pose();packet['hand']['rot']=rotation
        e.pose_sample(packet,0)
        assert e.state('fist',.01)[0]['event']=='sword_cast'
        assert e.state('fist',.02)==[]
        assert e.state('open',.03)[0]['event']=='sword_dismiss'
    e=SpellEngine()
    assert e.state('fist',0)[0]['event']=='sword_cast'  # Recognition does not require Quest.


def test_snap_then_open_then_fresh_forward_throw_commits_once():
    e=SpellEngine()
    e.pose_sample(pose(),0)
    assert e.snap(.01,'a')[0]['event']=='fireball_equipped'
    assert e.option.phase=='ready'
    assert e.state('open',.025)==[]
    assert not e.snap(.02,'a')
    events=[]
    for t in np.arange(.03,.7,.016):
        events+=e.state('open',float(t))
        movement=max(0,t-.3)*3
        packet=pose((.2,-.1,.3+movement));packet['hand']['finger_direction']=[0,0,1]  # Throwing hand, rather than fingers-up shield.
        events+=e.pose_sample(packet,float(t))
    launches=[v for v in events if v['event']=='fireball_throw']
    assert len(launches)==1 and launches[0]['committed']
    assert launches[0]['direction'][2]>.9


def test_reacquisition_jump_is_not_a_throw():
    e=SpellEngine()
    e.pose_sample(pose(),0)
    e.snap(.01,'snap')
    e.pose_sample(pose(valid=False),.3)
    events=e.pose_sample(pose((4,2,6)),.4)
    assert not any(a['event']=='fireball_throw' for a in events)


def test_stationary_shield_strength_follows_effort_and_pose_moves():
    e=SpellEngine();e.state('open',0)
    e.effort(.2,.01)
    events=e.pose_sample(pose(),.02)
    assert events[-1]['event']=='shield_guard' and events[-1]['strength']==.2
    assert e.effort(.8,.03)[-1]['strength']==.8
    assert e.effort(.1,.04)[-1]['strength']==.1
    moved=e.pose_sample(pose((.4,-.1,.4)),.05)
    assert moved[-1]['event']=='shield_pose'
    np.testing.assert_allclose(moved[-1]['origin'],[.4,1.3,.4])
    assert not any(v['event']=='shield_boost' for v in events+moved)
    packet=pose();packet['hand']['finger_direction']=[1,0,0]
    assert e.pose_sample(packet,.06)[-1]['event']=='shield_dismiss'
    assert e.mode=='idle'


def test_shield_needs_valid_up_fingers_palm_facing_reach_and_open_hand():
    for update in ({'finger_direction':[0,0,0]}, {'finger_direction':[1,0,0]},
                   {'palm_normal':[0,0,-1]}, {'pos':[.2,1.3,.05]}):
        e=SpellEngine();e.state('open',0);packet=pose();packet['hand'].update(update)
        assert not e.pose_sample(packet,.01) and e.mode=='idle'
    e=SpellEngine();e.state('open',0);packet=pose();del packet['hand']['finger_direction']
    assert e.pose_sample(packet,.01)==[]
    e.pose_sample(pose(),.02)
    assert e.mode=='shield'
    assert e.state('fist',.03)[0]['event']=='shield_dismiss'
    assert e.mode=='sword'


def test_stale_emg_dismisses_sword():
    e=SpellEngine();e.mode='sword';e.sign='fist';e.sign_t=0
    events=e.expire(.4)
    assert events[0]['event']=='sword_dismiss'
    assert e.mode=='idle'


def test_coordinate_frame_change_clears_velocity_and_hip_history():
    e=SpellEngine()
    for t in np.arange(0,.2,.02):e.pose_sample(pose(),float(t))
    e.snap(.21,'snap')
    e.near_hip=.22
    events=e.pose_sample(pose((2,2,6),frame='recentered'),.5)
    assert not any(a['event']=='fireball_throw' for a in events)
    assert len(e.history)==1 and e.near_hip<0


def test_snap_equips_and_fist_cancels_even_after_long_open_hold():
    e=SpellEngine();e.state('fist',0)
    events=e.snap(.01,'real')
    assert [v['event'] for v in events]==['sword_dismiss','fireball_equipped','fireball_spawn']
    assert e.mode=='fireball'
    for t in np.arange(.1,2,.1):e.state('open',float(t))
    events=e.state('fist',2.)
    assert [v['event'] for v in events]==['fireball_cancel','sword_cast']
    assert e.mode=='sword' and e.option.phase=='idle'


def test_backward_motion_and_motion_without_post_snap_open_cannot_throw():
    for opened in (False,True):
        e=SpellEngine();e.snap(0,'a');events=[]
        if opened:e.state('open',.01)
        for t in np.arange(.02,.7,.016):
            if opened:events+=e.state('open',float(t))
            events+=e.pose_sample(pose((.2,-.1,.3-t*3)),float(t))
        assert not any(v['event']=='fireball_throw' for v in events)


def test_shield_stale_tracking_dismisses_and_effort_does_not_summon():
    e=SpellEngine();assert e.effort(1.,0)==[] and e.mode=='idle'
    e.state('open',.01);e.pose_sample(pose(),.02)
    e.state('open',.31)
    events=e.expire(.33)
    assert events[-1]['event']=='shield_dismiss' and e.mode=='idle'
    assert e.effort_index==0


def test_fireball_to_shield_needs_full_valid_pose_and_open_hand_alone_holds_fireball():
    e=SpellEngine();e.snap(0,'a');e.state('open',.05)
    assert e.mode=='fireball'
    assert not e.pose_sample(pose(palm=(0,0,-1)),.06)
    assert e.mode=='fireball'
    events=e.pose_sample(pose(),.07)
    assert [v['event'] for v in events]==['fireball_cancel','shield_guard']
    assert events[0]['reason']=='shield'
    assert e.mode=='shield' and e.option.phase=='idle'
