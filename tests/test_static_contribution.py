import json
import pytest
from test_live_test import setup,pump


@pytest.mark.parametrize('motion,effort',[(motion,effort) for motion in ('shield_hold','sword_hold') for effort in ('low','medium','high')])
def test_static_holds_are_separate_and_never_relabel_dynamic_data(tmp_path,motion,effort):
    tester,predictor,clock=setup(tmp_path);pump(tester,predictor,clock,'none')
    tester.static_root=tmp_path/'data/micah/static'
    tester.collection_action('start',{'profile':'micah_emg','test_condition':'static','wearing_session':'micah-01',
        'focus':'live_intent','initial_intent':'non_intended','capture_mode':'emg_only'})
    assert tester.capture.directory.parent==tester.static_root
    tester.collection_action('select-motion',{'motion':motion,'effort':effort})
    with pytest.raises(ValueError,match='holds only'):tester.collection_action('select-motion',{'motion':'snap'})
    clock[0]+=1;tester.collection.mark_intent('intended');clock[0]+=10;tester.collection.mark_intent('non_intended')
    directory=tester.capture.directory;tester.collection_action('finish',{})
    truth=json.loads((directory/'truth-values.json').read_text())
    assert truth['test_condition']=='static'
    assert all(row['test_condition']=='static' for row in truth['intervals'])
    intended=next(row for row in truth['intervals'] if row['intended'])
    assert intended['selected_motion']['motion']==motion and intended['selected_motion']['effort']==effort
    assert intended['end']-intended['start']==pytest.approx(10)
