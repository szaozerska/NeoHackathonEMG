import json

import pytest

from test_live_test import setup,pump


def motion_context(tester,clock):
    tester.band_event('status',{'schema_version':1,'type':'status','host_time_s':clock[0],
        'payload':{'hand':'right','band_connection_id':'test-band'}})
    for offset in (-.01,0):
        for kind,values in [('gyro',[0,0,0]),('orientation',[1,0,0,0])]:
            tester.band_event(kind,{'schema_version':1,'type':kind,'host_time_s':clock[0]+offset,
                'band_timestamp_us':(1+offset)*1e6,'payload':{'values':values}})


def test_emg_only_capture_uses_own_folder_and_selected_motion_without_predictions(tmp_path):
    tester,predictor,clock=setup(tmp_path)
    tester.contribution_root=tmp_path/'Micah data contribution'
    pump(tester,predictor,clock,'none')
    motion_context(tester,clock)
    start=tester.collection_action('start',{'profile':'micah_emg','wearing_session':'micah-01',
        'focus':'live_intent','initial_intent':'non_intended','interaction_guard':.5})
    assert tester.capture.directory.parent==tester.contribution_root
    assert tester.capture.meta['camera_policy']=='disabled' and tester.capture.meta['input_modalities']==['emg']
    with pytest.raises(ValueError,match='Select a motion'):tester.collection.mark_intent('intended')
    tester.collection_action('select-motion',{'motion':'sword_hold','effort':'medium'})
    predictor.called.clear();begin=tester.capture.start;seq=tester.previous_seq or 0
    for i in range(13*128+1):
        clock[0]=begin+i/128
        if i==3*128:tester.collection.mark_intent('intended',clock[0])
        if i==8*128:tester.collection.mark_intent('non_intended',clock[0])
        tester.packet({'source_seq':seq+i+1,'source_t':i*7812.5,'source_uptime':clock[0],'samples':[[32768]*8]*16})
    assert not predictor.called.is_set()
    with pytest.raises(ValueError,match='Camera is disabled'):tester.camera_observation({})
    tester.band_event('gyro',{'schema_version':1,'type':'gyro','host_time_s':clock[0],'payload':{'values':[0,0,0]}})
    directory=tester.capture.directory
    result=tester.collection_action('finish',{})
    assert result['report']['intended_seconds']>0 and result['report']['non_intended_seconds']>0
    truth=json.loads((directory/'truth-values.json').read_text())
    assert truth['camera_used'] is False and truth['input_modalities']==['emg']
    intended=[v for v in truth['intervals'] if v['intended']]
    assert intended and all(v['selected_motion']['motion']=='sword_hold' and v['selected_motion']['effort']=='medium' for v in intended)
    assert intended[0]['start']==3 and intended[0]['end']==8
    assert intended[0]['baseline_before']=={'start':0.,'end':3.}
    assert intended[0]['baseline_after']=={'start':8.,'end':13.}
    assert truth['postprocessing_required'] and not truth['cleanup_applied']
    rows=[json.loads(line) for line in (directory/'streams.jsonl').read_text().splitlines()]
    assert any(v['kind']=='emg' for v in rows)
    assert not any(v['kind'] in ('prediction','decision','camera_observation') for v in rows)
    assert any(v['kind']=='band_gyro' for v in rows)
    assert not (directory/'camera').exists()
    tester.close()


@pytest.mark.parametrize('motion,effort',[('snap','high'),('shield_hold',None),('sword_hold','max'),('unknown',None)])
def test_invalid_motion_selection_is_rejected(tmp_path,motion,effort):
    tester,predictor,clock=setup(tmp_path);pump(tester,predictor,clock,'none')
    motion_context(tester,clock)
    tester.contribution_root=tmp_path/'Micah data contribution'
    tester.collection_action('start',{'profile':'micah_emg','wearing_session':'micah-01','focus':'live_intent','initial_intent':'non_intended'})
    with pytest.raises(ValueError,match='Select Snap'):tester.collection_action('select-motion',{'motion':motion,'effort':effort})
    tester.close()


def test_short_immediate_interval_keeps_baseline_and_separates_missing_signal(tmp_path):
    tester,predictor,clock=setup(tmp_path);pump(tester,predictor,clock,'none')
    motion_context(tester,clock)
    tester.contribution_root=tmp_path/'Micah data contribution'
    tester.collection_action('start',{'profile':'micah_emg','wearing_session':'micah-01','focus':'live_intent','initial_intent':'non_intended'})
    tester.collection_action('select-motion',{'motion':'snap'})
    begin=tester.capture.start
    clock[0]=begin+1
    tester.collection.mark_intent('intended',clock[0],.02)
    assert tester.collection.annotation_status()['labeling_paused_seconds']==0
    clock[0]=begin+1.05;tester.collection.mark_intent('non_intended',clock[0],.02)
    clock[0]=begin+2
    directory=tester.capture.directory;tester.collection_action('finish',{})
    truth=json.loads((directory/'truth-values.json').read_text())
    interval=next(v for v in truth['intervals'] if v['intended'])
    assert interval['start']==pytest.approx(1) and interval['end']==pytest.approx(1.05)
    assert interval['baseline_before']=={'start':0.,'end':1.}
    assert interval['baseline_after']==pytest.approx({'start':1.05,'end':2.})
    assert json.loads((directory/'signal-coverage.json').read_text())['segments']==[]
    assert truth['postprocessing_required'] and not truth['cleanup_applied']
    tester.close()


def test_emg_only_file_cannot_claim_full_synchronized_motion_capture(tmp_path):
    tester,predictor,clock=setup(tmp_path);pump(tester,predictor,clock,'none')
    tester.contribution_root=tmp_path/'Micah data contribution'
    with pytest.raises(ValueError,match='gyro/orientation are required'):
        tester.collection_action('start',{'profile':'micah_emg','wearing_session':'micah-01','focus':'live_intent','initial_intent':'non_intended'})
    assert tester.capture is None and not tester.contribution_root.exists()


def test_native_time_coverage_does_not_mistake_delivery_bursts_for_sensor_gaps(tmp_path):
    tester,predictor,clock=setup(tmp_path);pump(tester,predictor,clock,'none');motion_context(tester,clock)
    tester.contribution_root=tmp_path/'Micah data contribution'
    tester.collection_action('start',{'profile':'micah_emg','wearing_session':'micah-01','focus':'live_intent','initial_intent':'non_intended'})
    for i in range(64):
        tester.collection.packet({'source_seq':i,'source_t':i*7812.5,'source_uptime':clock[0],
            'samples':[[32768]*8]*16,'timing':{'clock_epoch':1}})
    assert len(tester.collection.sensor_segments)==1
    assert tester.collection.sensor_segments[0]['samples']==64*16
    tester.collection.packet({'source_seq':66,'source_t':66*7812.5,'source_uptime':clock[0],
        'samples':[[32768]*8]*16,'timing':{'clock_epoch':1}})
    assert len(tester.collection.sensor_segments)==2
    tester.close()
