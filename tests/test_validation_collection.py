import json

import pytest
from test_live_test import setup,pump
from spelltrain.dataset_policy import require_training_capture,require_usable_capture


def begin(tmp_path):
    tester,predictor,clock=setup(tmp_path);pump(tester,predictor,clock,'none')
    tester.validation_root=tmp_path/'validation'
    tester.collection_action('start',{'profile':'micah_emg','test_condition':'validation',
        'initial_test_condition':'static','wearing_session':'actual-wearing-01','role':'evaluation',
        'focus':'live_intent','initial_intent':'non_intended','capture_mode':'emg_only'})
    return tester,clock


def test_one_reserved_session_keeps_condition_and_effort_for_every_trial(tmp_path):
    tester,clock=begin(tmp_path);directory=tester.capture.directory
    tester.collection_action('select-motion',{'motion':'shield_hold','effort':'medium'})
    clock[0]+=1;tester.collection.mark_intent('intended')
    clock[0]+=3
    with pytest.raises(ValueError,match='Release Space'):tester.collection.select_condition('dynamic',clock[0])
    tester.collection.mark_intent('non_intended')
    clock[0]+=1;tester.collection.select_condition('dynamic',clock[0])
    tester.collection_action('select-motion',{'motion':'sword_hold','effort':'high'})
    clock[0]+=1;tester.collection.mark_intent('intended')
    clock[0]+=2;tester.collection.mark_intent('non_intended')
    clock[0]+=1;tester.collection_action('finish',{})
    meta=json.loads((directory/'metadata.json').read_text());truth=json.loads((directory/'truth-values.json').read_text())
    assert meta['do_not_train'] and meta['do_not_tune_thresholds']
    assert meta['dataset_role']=='untouched_guided_count_check' and meta['test_condition']=='mixed'
    intended=[v for v in truth['intervals'] if v['intended']]
    assert [v['test_condition'] for v in intended]==['static','dynamic']
    assert [v['selected_motion']['effort'] for v in intended]==['medium','high']
    assert [v['end']-v['start'] for v in intended]==pytest.approx([3,2])
    assert all(v['test_condition'] in ('static','dynamic') for v in truth['intervals'])
    assert 'condition-markers.json' in json.loads((directory/'guided-manifest.json').read_text())['source_hashes']
    require_usable_capture(directory)
    with pytest.raises(ValueError,match='Reserved evaluation'):require_training_capture(directory)


@pytest.mark.parametrize('motion,effort',[('snap',None),('animation_gesture',None),('shield_hold','low'),('shield_hold','medium'),('sword_hold','high')])
def test_validation_accepts_gesture_choices_without_extra_phase_reports(tmp_path,motion,effort):
    tester,_=begin(tmp_path)
    result=tester.collection_action('select-motion',{'motion':motion,'effort':effort})
    assert result['motion']==motion and result['effort']==effort


def test_validation_cannot_accidentally_start_in_training_role(tmp_path):
    tester,predictor,clock=setup(tmp_path);pump(tester,predictor,clock,'none')
    with pytest.raises(ValueError,match='reserved evaluation'):
        tester.collection_action('start',{'profile':'micah_emg','test_condition':'validation','role':'train',
            'wearing_session':'actual-wearing-01','focus':'live_intent','initial_intent':'non_intended','capture_mode':'emg_only'})
    assert tester.capture is None


def test_switch_condition_uses_event_time_even_if_request_is_delayed(tmp_path):
    tester,clock=begin(tmp_path);event_host=clock[0]+1;clock[0]+=1.3
    tester.collection_action('select-condition',{'test_condition':'dynamic','client_t':event_host-50,
        'alignment':{'host_offset_seconds':50,'uncertainty_seconds':.001}})
    marker=tester.collection.condition_markers[-1]
    assert marker['capture_t']==pytest.approx(event_host-tester.capture.start)
    assert tester.collection.intent_markers[-1]['source']=='participant_condition_switch'
