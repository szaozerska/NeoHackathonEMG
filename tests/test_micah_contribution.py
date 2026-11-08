import json

import pytest

from test_live_test import setup,pump


def test_emg_only_capture_uses_own_folder_and_selected_motion_without_predictions(tmp_path):
    tester,predictor,clock=setup(tmp_path)
    tester.contribution_root=tmp_path/'Micah data contribution'
    pump(tester,predictor,clock,'none')
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
    assert all(v['start']>=3.5 and v['end']<=7.5 for v in intended)
    rows=[json.loads(line) for line in (directory/'streams.jsonl').read_text().splitlines()]
    assert any(v['kind']=='emg' for v in rows)
    assert not any(v['kind'] in ('prediction','decision','band_gyro','camera_observation') for v in rows)
    assert not (directory/'camera').exists()
    tester.close()


@pytest.mark.parametrize('motion,effort',[('snap','high'),('shield_hold',None),('sword_hold','max'),('unknown',None)])
def test_invalid_motion_selection_is_rejected(tmp_path,motion,effort):
    tester,predictor,clock=setup(tmp_path);pump(tester,predictor,clock,'none')
    tester.contribution_root=tmp_path/'Micah data contribution'
    tester.collection_action('start',{'profile':'micah_emg','wearing_session':'micah-01','focus':'live_intent','initial_intent':'non_intended'})
    with pytest.raises(ValueError,match='Select Snap'):tester.collection_action('select-motion',{'motion':motion,'effort':effort})
    tester.close()
