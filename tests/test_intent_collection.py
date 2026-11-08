import hashlib
import json

import pytest

from spelltrain.intent_collection import EquipmentPreview,IntentCollection,protocol
from spelltrain.live_capture import LiveCapture


def make(tmp_path,focus='snaps',role='train'):
    clock=[100.]
    capture=LiveCapture(tmp_path,lambda:clock[0],{'signal':{}})
    collection=IntentCollection(capture,lambda:clock[0],'wearing-01',role,focus=focus)
    return collection,capture,clock


def fill(collection,capture,clock):
    trial=collection.current
    clock[0]=capture.start+trial['start']
    for i in range(round(trial['seconds']*128)+1):
        clock[0]=capture.start+trial['start']+i/128
        packet={'source_seq':i,'source_uptime':clock[0],'source_t':i*7812.5,'samples':[[32768]*8]*16}
        collection.packet(packet)
        capture.append('emg',clock[0],packet=packet)
    clock[0]=capture.start+trial['end']+.01


def test_protocol_has_continuous_angles_intensities_nonuse_and_no_open_cases():
    plan=protocol();snaps=[p for p in plan if p['kind']=='snap']
    assert len(snaps)==20 and len({p['intensity'] for p in snaps})==3
    assert all(p['motion']=='continuous_or_free_angle' for p in snaps)
    scenarios={p['scenario'] for p in plan}
    assert {'finger_fidget','wrist_sweep','walking','arm_swing','snap_without_open','steady_open'}<=scenarios
    assert any(p['kind']=='open_hold' and p['seconds']==10 for p in plan)


def test_no_automatic_truth_and_missing_data_cannot_be_confirmed_usable(tmp_path):
    collection,capture,clock=make(tmp_path)
    collection.start_trial(True)
    clock[0]+=9
    with pytest.raises(ValueError,match='actual snap count'):collection.confirm({'performed':True})
    result=collection.confirm({'performed':True,'actual_snaps':1,'intent':True,'hand_state':'mixed'})
    assert result['saved_trials']==1 and result['usable_trials']==0
    trial=collection.trials[0]
    assert trial['participant_confirmed'] and not trial['confirmed'] and not trial['signal_usable']
    assert not trial['exact_event_times_verified']
    collection.finish();capture.finish();collection.finalize()
    assert json.loads((capture.directory/'guided-trials.json').read_text())==[]


def test_success_failed_snap_and_hashes_preserve_weak_labels(tmp_path):
    collection,capture,clock=make(tmp_path)
    collection.start_trial(True);fill(collection,capture,clock)
    collection.confirm({'performed':True,'actual_snaps':1,'intent':True,'hand_state':'mixed'})
    collection.start_trial(True);fill(collection,capture,clock)
    collection.confirm({'performed':True,'actual_snaps':0,'intent':True,'hand_state':'mixed','note':'Failed snap'})
    collection.finish();capture.finish();report=collection.finalize()
    assert report['exported_training_clips']==2 and report['actual_event_precision'] is None
    trials=json.loads((capture.directory/'guided-trials.json').read_text())
    assert [t['reported_count'] for t in trials]==[1,0]
    assert all(t['exact_event_times_verified'] is False for t in trials)
    manifest=json.loads((capture.directory/'guided-manifest.json').read_text())
    assert all(hashlib.sha256((capture.directory/name).read_bytes()).hexdigest()==digest for name,digest in manifest['source_hashes'].items())


def test_stable_fireball_hold_not_relabeled_as_shield_and_evaluation_reserved(tmp_path):
    collection,capture,clock=make(tmp_path,focus='states',role='evaluation')
    collection.start_trial(True);fill(collection,capture,clock)
    collection.confirm({'performed':True,'actual_snaps':0,'hand_state':'open','intent':True})
    collection.finish();capture.finish();collection.finalize()
    assert collection.trials[0]['confirmed']
    assert json.loads((capture.directory/'guided-trials.json').read_text())==[]
    assert capture.meta['dataset_role']=='untouched_guided_count_check'


def test_retry_retains_discarded_attempt_and_zero_snap_failure_flag(tmp_path):
    collection,capture,clock=make(tmp_path)
    collection.start_trial(True);clock[0]+=9
    collection.flag('false_snap','I was rotating my wrist')
    result=collection.confirm({'discard':True,'retry':True})
    assert result['index']==0 and result['saved_trials']==1
    assert not collection.trials[0]['confirmed']
    assert collection.flags[0]['review_start']>=0 and not collection.flags[0]['exact_event_times_verified']


def test_preview_requires_snap_then_open_and_preserves_until_confirmed_grip():
    preview=EquipmentPreview()
    preview.state({'open':.99},1)
    assert preview.item=='none'
    preview.snap(2)
    assert preview.item=='pending_open'
    preview.state({'open':.99},2.05);preview.state({'open':.99},2.15)
    assert preview.item=='fireball'
    preview.state({'none':.99},3);preview.state({'open':.99},4)
    assert preview.item=='fireball'
    preview.state({'fist':.99},4.05)
    assert preview.item=='fireball'
    preview.state({'fist':.99},4.15);preview.state({'fist':.99},4.25)
    assert preview.item=='sword'


def test_preview_no_open_snap_expires_and_immediate_grip_never_equips_fireball():
    preview=EquipmentPreview();preview.snap(1)
    preview.state({'fist':.99},1.05);preview.state({'fist':.99},1.15);preview.state({'fist':.99},1.25)
    assert preview.item=='sword'
    preview.snap(2);preview.state({'none':.9},4.1)
    assert preview.item=='none'
    preview.state({'open':.99},4.2);preview.state({'open':.99},4.3)
    assert preview.item=='none'


def test_open_immediately_after_snap_has_no_minimum_transition_delay():
    preview=EquipmentPreview();preview.snap(1)
    preview.state({'open':.99},1.001)
    assert preview.item=='fireball'
    preview.snap(2);preview.state({'open':.99},4.001)
    assert preview.item=='none'


def test_intent_first_dataset_does_not_require_action_labels_or_counts(tmp_path):
    collection,capture,clock=make(tmp_path,focus='intent')
    collection.start_trial(True);fill(collection,capture,clock)
    with pytest.raises(ValueError,match='Explicitly report'):
        collection.confirm({'performed':True})
    collection.confirm({'performed':True,'intent_label':'non_intended'})
    trial=collection.trials[0]
    assert trial['confirmed'] and trial['binary_intent_label']=='non_intended'
    assert trial['reported_hand_state']=='unknown' and trial['reported_count'] is None
    collection.finish();capture.finish();report=collection.finalize()
    assert report['binary_intent_clips']==1 and report['exported_training_clips']==0
    assert json.loads((capture.directory/'intent-gate-trials.json').read_text())[0]['label']=='non_intended'


def test_gyro_and_quaternion_sign_flip_are_measurements_not_truth(tmp_path):
    collection,capture,clock=make(tmp_path);collection.start_trial(True);clock[0]+=3.2
    for q in ([1,0,0,0],[-1,0,0,0],[.70710678,0,.70710678,0]):
        collection.context('orientation',{'payload':{'values':q}},clock[0])
    collection.context('gyro',{'payload':{'values':[3,4,0]}},clock[0])
    assert collection.current['orientation_samples']==3
    assert collection.current['orientation_path_degrees']==pytest.approx(90)
    assert collection.current['gyro_peak_raw']==5
    assert not collection.current['confirmed']


def test_live_toggle_clips_both_sides_of_clicks_and_preserves_roles(tmp_path):
    collection,capture,clock=make(tmp_path,focus='live_intent',role='evaluation')
    assert collection.phase=='live' and collection.annotation_status()['label']=='non_intended'
    for i in range(14*128+1):
        t=i/128;clock[0]=capture.start+t
        if i==5*128:collection.mark_intent('intended',clock[0],.02)
        if i==8*128:collection.interaction(clock[0],.01,'keyboard')
        collection.packet({'source_seq':i,'source_uptime':clock[0],'samples':[[32768]*8]*16})
    collection.finish();capture.finish();report=collection.finalize()
    intervals=json.loads((capture.directory/'intent-gate-intervals.json').read_text())['intervals']
    assert [v['label'] for v in intervals]==['non_intended','intended','intended']
    assert intervals[0]['start']==1 and intervals[0]['end']==pytest.approx(3.98)
    assert intervals[1]['start']==pytest.approx(6.02) and intervals[1]['end']==pytest.approx(6.99)
    assert intervals[-1]['start']==pytest.approx(9.01) and intervals[-1]['end']==13
    assert all(v['dataset_role']=='untouched_guided_count_check' and v['gesture_label'] is None for v in intervals)
    assert report['toggle_labeled_seconds']>0


def test_toggle_export_never_bridges_signal_gap(tmp_path):
    collection,capture,clock=make(tmp_path,focus='live_intent')
    for start,end in ((0,4),(7,11)):
        for i in range(start*128,end*128):
            clock[0]=capture.start+i/128
            collection.packet({'source_seq':i,'source_uptime':clock[0],'samples':[[32768]*8]*16})
    clock[0]=capture.start+11;collection.finish();capture.finish();collection.finalize()
    intervals=json.loads((capture.directory/'intent-gate-intervals.json').read_text())['intervals']
    assert intervals and all(not (v['start']<4 and v['end']>7) for v in intervals)
    assert all(v['end']<=4 or v['start']>=7 for v in intervals)
