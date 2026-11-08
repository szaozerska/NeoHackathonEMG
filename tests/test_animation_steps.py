import json

import pytest
from test_live_test import setup, pump


def start_steps(tmp_path):
    tester, predictor, clock = setup(tmp_path)
    pump(tester, predictor, clock, 'none')
    tester.animation_root = tmp_path/'animation'
    tester.collection_action('start', {'profile':'micah_emg','test_condition':'animation_steps',
        'animation_condition':'static','wearing_session':'micah-steps-01','focus':'live_intent',
        'initial_intent':'non_intended','capture_mode':'emg_only'})
    return tester, clock


def test_step_mapping_keeps_components_and_complete_ordered_sequence(tmp_path):
    tester, clock = start_steps(tmp_path)
    directory = tester.capture.directory
    assert directory.parent == tmp_path/'animation/steps'
    assert tester.collection.selected_motion is None
    for motion in ['animation_cross_fingers','animation_curl_ring_pinky','animation_thumb_approach']:
        tester.collection_action('select-motion', {'motion':motion})
        clock[0] += 1; tester.collection.mark_intent('intended')
        clock[0] += .2; tester.collection.mark_animation_phase('component_hold')
        clock[0] += .5; tester.collection.mark_intent('non_intended')
    tester.collection_action('select-motion', {'motion':'animation_sequence'})
    clock[0] += 1; tester.collection.mark_intent('intended')
    for phase in ['curl_ring_pinky','thumb_approach','combined_hold']:
        clock[0] += .25; tester.collection.mark_animation_phase(phase)
    clock[0] += 1; tester.collection.mark_intent('non_intended')
    tester.collection_action('finish', {})
    truth = json.loads((directory/'truth-values.json').read_text())
    assert len([v for v in truth['intervals'] if v['intended']]) == 4
    phases = json.loads((directory/'animation-phase-intervals.json').read_text())
    sequence = [v for v in phases['intervals'] if v['selected_motion']['motion']=='animation_sequence']
    assert [v['phase'] for v in sequence] == ['cross_fingers','curl_ring_pinky','thumb_approach','combined_hold']
    assert sequence[0]['end']-sequence[0]['start'] == pytest.approx(.25)
    assert all(v['exact_action_times_verified'] is False for v in sequence)
    manifest = json.loads((directory/'guided-manifest.json').read_text())
    assert 'animation-phase-markers.json' in manifest['source_hashes']
    assert 'animation-phase-intervals.json' in manifest['source_hashes']


def test_missed_step_stays_unknown_and_backward_markers_are_rejected(tmp_path):
    tester, clock = start_steps(tmp_path)
    tester.collection_action('select-motion', {'motion':'animation_sequence'})
    with pytest.raises(ValueError, match='Hold Space'):
        tester.collection.mark_animation_phase('curl_ring_pinky')
    clock[0] += 1; tester.collection.mark_intent('intended')
    clock[0] += .5; marker = tester.collection.mark_animation_phase('thumb_approach')
    assert marker['skipped_preceding_phases'] == ['curl_ring_pinky']
    with pytest.raises(ValueError, match='forward'):
        tester.collection.mark_animation_phase('curl_ring_pinky')
    assert all(m['phase']!='curl_ring_pinky' for m in tester.collection.animation_phase_markers)


def test_phase_report_uses_browser_event_time_instead_of_http_receipt(tmp_path):
    tester, clock = start_steps(tmp_path)
    tester.collection_action('select-motion', {'motion':'animation_sequence'})
    clock[0] += 1; tester.collection.mark_intent('intended')
    event_host = clock[0]+.25; clock[0] += .55
    marker = tester.collection_action('animation-phase', {'phase':'curl_ring_pinky',
        'client_t':event_host-50,'alignment':{'host_offset_seconds':50,'uncertainty_seconds':.001}})
    assert marker['capture_t'] == pytest.approx(event_host-tester.capture.start)
    assert marker['browser_clock_alignment']['server_received_host_uptime'] == clock[0]
