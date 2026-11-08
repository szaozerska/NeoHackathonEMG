import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest

scripts=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('step_comparison',scripts/'compare_animation_steps.py')
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)


def test_comparison_matches_channel_shape_without_treating_gain_as_another_action(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir()
    (source/'metadata.json').write_text(json.dumps({'id':'synthetic-fixture','synthetic':True,
        'recording_complete':True,'collection_variant':'animation_steps','test_condition':'static'}))
    labels={'intervals':[{'start':0,'end':1,'phase':'cross_fingers','selected_motion':{'motion':'animation_cross_fingers'}},
                          {'start':1,'end':2,'phase':'cross_fingers','selected_motion':{'motion':'animation_sequence'}}]}
    path=source/'animation-phase-intervals.json';path.write_text(json.dumps(labels));original=path.read_bytes()
    (source/'animation-phase-markers.json').write_text('{"markers":[]}')
    t=np.arange(.01,2,.015625);r=np.tile(np.arange(1,9,dtype=float),(len(t),1));r[t>=1]*=3
    monkeypatch.setattr(review,'load_envelopes',lambda _:(t,r,np.zeros(len(t),int),{'fixture':True}))
    output=tmp_path/'report';review.compare(source,output)
    result=json.loads((output/'step-comparison.json').read_text())
    match=result['comparisons'][0]
    assert match['channel_pattern_cosine']==pytest.approx(1)
    assert match['combined_median_rms_adc']/match['isolated_median_rms_adc']==pytest.approx(3)
    assert result['labels_modified'] is False and path.read_bytes()==original
    assert 'unavailable' in result['comparisons'][1]
