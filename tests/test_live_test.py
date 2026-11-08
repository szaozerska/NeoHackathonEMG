import json
import threading
import time
import urllib.request
from spelltrain.live_test import LiveTester


class FakePredictor:
    def __init__(self):self.outputs=[];self.called=threading.Event()
    def feed(self,row):self.called.set();return self.outputs


def setup(tmp_path):
    clock=[100.];predictor=FakePredictor()
    tester=LiveTester({'report':{'subject':'player-a','task':'v6_feedback_equipment_model','model_version':'v6'}},
                      tmp_path/'raw.jsonl',clock=lambda:clock[0],predictor=predictor,capture_root=tmp_path/'captures')
    return tester,predictor,clock


def packet(clock,seq=1):return {'source_seq':seq,'source_uptime':clock[0],'samples':[[0]*8]*16}


def pump(tester,predictor,clock,label,seconds=.5,effort=None):
    for _ in range(round(seconds/.05)):
        clock[0]+=.05
        predictor.outputs=[{'kind':'state','label':label,'confidence':.95,'source_t':clock[0]-100}]
        if effort:predictor.outputs.append({'kind':'effort','effort_index':.7,'probabilities':effort,'source_t':clock[0]-100})
        tester.packet(packet(clock,(tester.previous_seq or 0)+1))


def test_snap_equips_immediately_and_subsequent_confirmed_fist_cancels(tmp_path):
    tester,predictor,clock=setup(tmp_path)
    assert tester.status()['gesture']=='Nothing' and not tester.status()['connected']
    pump(tester,predictor,clock,'open',effort={'light':.1,'medium':.7,'firm':.2})
    state=tester.status();assert state['gesture']=='Shield' and state['effort']['label']=='medium'
    assert state['shield_pose_verified'] is False
    pump(tester,predictor,clock,'fist');assert tester.status()['gesture']=='Sword equipped'
    predictor.outputs=[{'kind':'snap','event_id':'1'}]
    clock[0]+=.02;tester.packet(packet(clock,tester.previous_seq+1))
    assert tester.status()['gesture']=='Fireball equipped'
    pump(tester,predictor,clock,'fist')
    assert tester.status()['gesture']=='Sword equipped'
    assert tester.status()['snap_candidates']==1
    assert tester.status()['fireball_phase']=='idle'
    assert tester.status()['fireballs_committed']==0
    pump(tester,predictor,clock,'none',seconds=1.3)
    assert tester.status()['gesture']=='Nothing'


def test_half_second_file_bursts_do_not_expire_state_but_real_loss_clears_display(tmp_path):
    tester,predictor,clock=setup(tmp_path)
    pump(tester,predictor,clock,'fist');assert tester.status()['gesture']=='Sword equipped'
    clock[0]+=.6
    assert tester.status()['gesture']=='Sword equipped' and tester.status()['connected']
    clock[0]+=.7;assert tester.status()['gesture']=='Nothing' and not tester.status()['connected']
    predictor.outputs=[]
    tester.packet(packet(clock,99));assert tester.status()['gesture']=='Nothing'
    assert tester.status()['warming_up']
    count=tester.status()['packets']
    tester.packet({**packet(clock,100),'source_uptime':clock[0]-20})
    assert tester.status()['packets']==count and tester.status()['errors']
    tester.close();assert not tester.status()['connected']


def test_source_change_without_new_packets_keeps_status_json_valid(tmp_path):
    tester,predictor,clock=setup(tmp_path)
    pump(tester,predictor,clock,'fist')
    tester.source_changed('file',str(tmp_path/'next.jsonl'))
    status=tester.status()
    assert not status['connected'] and status['packet_age_seconds'] is None
    json.dumps(status,allow_nan=False)


def test_tester_http_and_feed_tail_do_not_replay_or_modify_old_recording(tmp_path):
    from spelltrain.live_test import LiveTester
    path=tmp_path/'raw.jsonl';original=b'previous data must not be replayed\n';path.write_bytes(original)
    predictor=FakePredictor();predictor.outputs=[{'kind':'state','label':'fist','confidence':.9,'source_t':i*.05} for i in range(4)]
    tester=LiveTester({'report':{'subject':'player-a'}},path,predictor=predictor)
    port=tester.start(0)
    try:
        time.sleep(.08)
        assert not predictor.called.is_set()
        # Raw Kinesis protobuf: sequence 7, time 100, 256 sample bytes.
        payload=b'\x08\x07\x10\x64\x1a\x80\x02'+b'\x01\x80'*128
        row=json.dumps({'kind':'0x0200020a','payload':payload.hex(),'uptime':time.monotonic()})+'\n'
        with path.open('a') as stream:stream.write(row)
        assert predictor.called.wait(2)
        status=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status'))
        assert status['gesture']=='Sword equipped' and status['connected']
        html=urllib.request.urlopen(f'http://127.0.0.1:{port}/').read().decode()
        assert 'Live spell test' in html and 'getUserMedia' not in html
        assert path.read_bytes()==original+row.encode()
    finally:tester.close()



def test_snap_event_takes_priority_even_when_hand_classifier_remains_open(tmp_path):
    tester,predictor,clock=setup(tmp_path)
    pump(tester,predictor,clock,'open')
    assert tester.status()['gesture']=='Shield'
    predictor.outputs=[{'kind':'snap','event_id':'real-snap','source_t':clock[0]-100}]
    tester.packet(packet(clock,tester.previous_seq+1))
    assert tester.status()['gesture']=='Fireball equipped' and tester.status()['fireballs']==1
    pump(tester,predictor,clock,'open',seconds=4.)
    assert tester.status()['gesture']=='Fireball equipped'
    assert tester.status()['fireballs_committed']==0
    pump(tester,predictor,clock,'fist')
    assert tester.status()['gesture']=='Sword equipped'
    assert tester.status()['fireball_phase']=='idle'


def test_recording_saves_original_emg_predictions_and_separate_human_corrections(tmp_path):
    tester,predictor,clock=setup(tmp_path)
    pump(tester,predictor,clock,'none')
    first=tester.start_capture();assert first['active']
    assert tester.start_capture()['id']==first['id']  # Idempotent duplicate start.
    pump(tester,predictor,clock,'open')
    predictor.outputs=[{'kind':'snap','event_id':'false-positive','confidence':.9999}]
    tester.packet(packet(clock,tester.previous_seq+1))
    assert tester.status()['gesture']=='Fireball equipped'
    marker=tester.mark_correction('Shield')
    assert marker['displayed_prediction']=='Fireball equipped' and marker['gesture']=='Shield'
    assert marker['source']=='participant_report' and not marker['verified_event_time']
    stopped=tester.stop_capture();assert stopped['complete'] and not stopped['active']
    assert tester.stop_capture()['id']==first['id']
    from pathlib import Path
    path=Path(stopped['path'])
    rows=[json.loads(line) for line in (path/'streams.jsonl').read_text().splitlines()]
    assert any(r['kind']=='emg' and r.get('pre_roll') for r in rows)
    assert any(r['kind']=='prediction' and r['prediction']['kind']=='snap' for r in rows)
    assert any(r['kind']=='decision' and r['decision']['gesture']=='Fireball equipped' for r in rows)
    assert any(r['kind']=='spell_state' for r in rows)
    assert all(not r['decision']['committed'] for r in rows if r['kind']=='decision')
    assert json.loads((path/'corrections.json').read_text())[0]['gesture']=='Shield'
    assert json.loads((path/'metadata.json').read_text())['online_learning'] is False
    assert tester.status()['online_learning'] is False
    tester.close()


def test_record_api_token_controls_and_observer_endpoint(tmp_path):
    import urllib.error
    tester,predictor,clock=setup(tmp_path);port=tester.start(0,start_feed=False)
    base=f'http://127.0.0.1:{port}'
    def post(action,body={},token=None):
        request=urllib.request.Request(base+'/api/record/'+action,data=json.dumps(body).encode(),
             headers={'X-Session-Token':token or tester.csrf})
        return json.load(urllib.request.urlopen(request))
    try:
        try:post('start',token='invalid')
        except urllib.error.HTTPError as error:assert error.code==403
        else:raise AssertionError('Missing CSRF rejection')
        pump(tester,predictor,clock,'fist');post('start')
        pump(tester,predictor,clock,'none');post('mark',{'gesture':'Nothing'})
        observed=json.load(urllib.request.urlopen(base+'/api/observe'))
        assert observed['status']['recording']['active']
        assert observed['status']['recording']['corrections']==1
        assert any(r.get('event')=='correction' for r in observed['recent'])
        post('stop');assert not tester.status()['recording']['active']
    finally:tester.close()


def test_prospective_and_delayed_markers_are_weak_labels_with_explicit_action_windows(tmp_path):
    tester,predictor,clock=setup(tmp_path)
    pump(tester,predictor,clock,'none');tester.start_capture()
    marker=tester.mark_correction('Fireball','before')
    assert marker['review_window_start']>marker['reported_at']
    assert marker['review_window_end']-marker['review_window_start']==4.
    assert marker['action_performed_verified'] is False and marker['verified_event_time'] is False
    clock[0]+=10
    previous=tester.mark_correction('Fireball','after_delayed')
    assert previous['reported_at']-previous['review_window_start']==8.
    tester.close()


def test_manual_shield_switch_preserves_open_memory_until_explicit_command(tmp_path):
    tester,predictor,clock=setup(tmp_path);pump(tester,predictor,clock,'open')
    predictor.outputs=[{'kind':'snap','event_id':'a','source_t':clock[0]-100}]
    tester.packet(packet(clock,tester.previous_seq+1))
    pump(tester,predictor,clock,'open')
    assert tester.status()['gesture']=='Fireball equipped'
    tester.start_capture()
    assert tester.switch_to_shield()['gesture']=='Shield'
    assert tester.option.phase=='idle'
    result=tester.stop_capture()
    from pathlib import Path
    rows=[json.loads(line) for line in (Path(result['path'])/'streams.jsonl').read_text().splitlines()]
    assert any(r['kind']=='equipment_command' and r['command']['verified_gesture'] is False for r in rows)
    assert any(r['kind']=='spell_state' and r['transition']['intent'].get('reason')=='shield' for r in rows)


def test_v4_baseline_restores_brief_snap_feedback_without_equipment_latching(tmp_path):
    clock=[100.];predictor=FakePredictor()
    tester=LiveTester({'report':{'task':'reference_reviewed_gesture_update'}},tmp_path/'raw.jsonl',clock=lambda:clock[0],predictor=predictor)
    assert tester.status()['model_version']=='v4'
    assert tester.status()['display_policy']=='v4_feedback'
    assert not tester.status()['camera_required_for_recording']
    pump(tester,predictor,clock,'fist')
    assert tester.status()['gesture']=='Sword'
    predictor.outputs=[{'kind':'snap','event_id':'1','source_t':clock[0]-100}]
    tester.packet(packet(clock,tester.previous_seq+1))
    assert tester.status()['gesture']=='Fireball'
    pump(tester,predictor,clock,'open',seconds=.8)
    assert tester.status()['gesture']=='Fireball'
    pump(tester,predictor,clock,'open',seconds=.5)
    assert tester.status()['gesture']=='Shield'
    assert tester.option.phase=='idle' and tester.status()['fireballs_committed']==0
    tester.start_capture();saved=tester.stop_capture()
    from pathlib import Path
    meta=json.loads((Path(saved['path'])/'metadata.json').read_text())
    assert meta['model']['version']=='v4' and meta['model']['display_policy']=='v4_feedback'
