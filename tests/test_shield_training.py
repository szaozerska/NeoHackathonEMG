import json
import numpy as np
import pytest
from spelltrain.session import Session
from spelltrain.shield_training import ShieldTraining, protocol


def setup_training(tmp_path):
    session = Session(tmp_path/'shield', 'player')
    clock = [0.]
    session.now = lambda: clock[0]
    return session, ShieldTraining(session), clock


def capture(training, session, clock, *, poses=False, invalid=False, synced=True, frame_change=False, stale_emg=False):
    start = clock[0]
    training.start(training.status()['current']['id'])
    for i in range(512):
        t = start+i/128
        training.observe({'received': t, 'samples': np.arange(128).reshape(16,8), 'source_seq': i,
                          'source_uptime':session.meta['origin_monotonic']+t-(10 if stale_emg else 0), 'gap':False})
    if poses:
        for i in range(240):
            t = start+i/60
            training.observe_pose({'received':t, 'timing':'clock_offset_estimate' if synced else 'receive_anchored',
                                   'pose':{'hand':{'valid':not invalid,'confidence':1},
                                           'chest':{'valid':True,'confidence':1},
                                           'frame_id':'second' if frame_change and i>120 else 'first'}})
    clock[0] = start+4
    return training.finish()


def test_protocol_covers_crossed_conditions_and_comparisons():
    trials = protocol('same-session')
    assert len(trials)==48 and len({t['id'] for t in trials})==48
    assert trials==protocol('same-session')
    assert all(t['hand_state']=='open' for t in trials if t['spell']=='shield')
    assert {t['orientation'] for t in trials if t['spell']=='sword'}=={'thumb_up','palm_down','palm_up'}
    assert sum(t['condition']=='snap' for t in trials)==3
    for repetition in (1,2,3):
        block=[t for t in trials if t['repetition']==repetition]
        assert len(block)==16 and block[0]['condition']=='rest'
        assert {(t['effort'],t['movement']) for t in block if t['spell']=='shield'}=={
            (effort,motion) for effort in ('light','medium','firm') for motion in ('center','left','right')}


def test_received_trial_needs_confirmation_and_retry_does_not_advance(tmp_path):
    s,t,clock=setup_training(tmp_path)
    first=t.status()['current']['id']
    result=capture(t,s,clock)
    assert result['received'] and result['capture_mode']=='emg_only' and result['needs_paired_quest']
    assert result['confirmed'] is None and t.status()['completed']==0
    with pytest.raises(ValueError):t.start(first)
    t.confirm(result['id'],False)
    assert t.status()['current']['id']==first
    result=capture(t,s,clock)
    t.confirm(result['id'],True)
    assert t.status()['completed']==1 and t.status()['current']['id']!=first
    assert t.confirm(result['id'],True)['confirmed']  # Idempotent confirmation.
    assert s.annotations==[]  # No fabricated event or hand-state labels.
    saved=json.loads((s.directory/'gesture-trials-v3.json').read_text())
    assert saved[-1]['confirmation_source']=='participant_report'
    assert ShieldTraining(s).status()['completed']==1
    s.close()


@pytest.mark.parametrize('option,expected', [({},'emg_only'),({'poses':True},'paired'),
    ({'poses':True,'invalid':True},'paired_incomplete'),({'poses':True,'synced':False},'paired_incomplete'),
    ({'poses':True,'frame_change':True},'paired_incomplete'),({'poses':True,'stale_emg':True},'paired_incomplete')])
def test_pairing_requires_valid_continuous_tracking_and_timing(tmp_path, option, expected):
    s,t,clock=setup_training(tmp_path)
    result=capture(t,s,clock,**option)
    assert result['capture_mode']==expected
    assert result['needs_paired_quest']==(expected!='paired')
    s.close()


def test_bad_signal_never_becomes_a_confirmed_effort_label(tmp_path):
    s,t,clock=setup_training(tmp_path)
    t.start(t.status()['current']['id']);clock[0]=5
    result=t.finish()
    assert not result['received'] and t.status()['completed']==0
    with pytest.raises(ValueError):t.confirm(result['id'],True)
    with pytest.raises(ValueError):t.confirm(result['id'],'true')
    s.close()


def test_live_api_rejects_stale_token_and_stale_band(tmp_path):
    import time
    import urllib.request
    import urllib.error
    from spelltrain.recorder import Recorder
    s=Session(tmp_path/'web','player');r=Recorder(s);port=r.start_web(0)
    base=f'http://127.0.0.1:{port}'
    try:
        html=urllib.request.urlopen(base).read().decode()
        assert 'Spell training' in html
        token=html.split("const token='")[1].split("'")[0]
        state=json.load(urllib.request.urlopen(base+'/api/shield'))
        value={'trial_id':state['current']['id']}
        def post(path,value,token=token):
            request=urllib.request.Request(base+'/api/'+path,data=json.dumps(value).encode(),headers={'X-Session-Token':token})
            return json.load(urllib.request.urlopen(request))
        with pytest.raises(urllib.error.HTTPError) as denied:post('shield/start',value,'stale')
        assert denied.value.code==403
        with pytest.raises(urllib.error.HTTPError):post('shield/start',value)
        r.last_emg=s.now();started=post('shield/start',value)
        assert started['motion']==value['trial_id']
        with pytest.raises(urllib.error.HTTPError):post('check/start',{'motion':'rest'})
        assert not post('shield/stop',{})['received']
        # Exercise the actual ingestion worker, raw persistence, and review endpoints together.
        clock=[0.];s.now=lambda:clock[0];r.last_emg=0.
        post('shield/start',value)
        r.spawn(r.worker)
        for seq in range(512):
            r.enqueue({'kind':'emg','t':seq/128,'received':seq/128,'source_seq':seq,
                       'source_uptime':s.meta['origin_monotonic']+seq/128,
                       'samples':np.arange(128).reshape(16,8).tolist(),'gap':False})
        r.messages.join();clock[0]=4.
        received=post('shield/stop',{})
        assert received['received'] and received['samples']==8192
        post('shield/confirm',{'id':received['id'],'accepted':True})
        assert json.load(urllib.request.urlopen(base+'/api/shield'))['completed']==1
        assert s.counts['emg']==512 and not r.errors
    finally:r.close()
