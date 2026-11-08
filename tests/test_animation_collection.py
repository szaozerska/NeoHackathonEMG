import json
import urllib.request

import pytest
from test_live_test import setup, pump


def test_animation_space_hold_preserves_full_thirty_seconds_and_baseline(tmp_path):
    tester, predictor, clock = setup(tmp_path)
    pump(tester, predictor, clock, 'none')
    tester.animation_root = tmp_path/'animation'
    tester.collection_action('start', {'profile':'micah_emg', 'test_condition':'animation',
        'wearing_session':'micah-01', 'focus':'live_intent',
        'initial_intent':'non_intended', 'capture_mode':'emg_only'})
    assert tester.capture.directory.parent == tester.animation_root
    assert tester.capture.meta['gesture_label'] == 'Animation Gesture'
    assert tester.collection.selected_motion['motion'] == 'animation_gesture'
    with pytest.raises(ValueError, match='Animation Gesture only'):
        tester.collection_action('select-motion', {'motion':'sword_hold', 'effort':'low'})
    clock[0] += 2
    tester.collection.mark_intent('intended')
    clock[0] += 30
    tester.collection.mark_intent('non_intended')
    clock[0] += 2
    directory = tester.capture.directory
    tester.collection_action('finish', {})
    truth = json.loads((directory/'truth-values.json').read_text())
    intended = [v for v in truth['intervals'] if v['intended']]
    assert len(intended) == 1
    assert intended[0]['end']-intended[0]['start'] == pytest.approx(30)
    assert intended[0]['selected_motion']['motion'] == 'animation_gesture'
    assert intended[0]['selected_motion']['effort'] is None
    assert truth['test_condition'] == 'static'
    assert truth['interaction_guard_seconds'] == 0
    assert len([v for v in truth['intervals'] if not v['intended']]) == 2


def test_animation_page_is_separate_and_does_not_expose_other_gesture_buttons(tmp_path):
    tester, _, _ = setup(tmp_path)
    port = tester.start(0, start_feed=False)
    try:
        html = urllib.request.urlopen(f'http://127.0.0.1:{port}/animation').read().decode()
        assert 'data-test-condition="animation"' in html
        assert 'data-motion="animation_gesture"' in html
        assert 'data-motion="snap"' not in html
        assert 'data-motion="shield_hold"' not in html
        assert 'id="holdElapsed"' in html
    finally:
        tester.close()
