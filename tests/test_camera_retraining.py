import copy
import numpy as np
import pytest
from spelltrain.camera_retraining import reviewed_records,train_camera_candidate


def fixture():
    features=[]
    for t in np.arange(.2,6,.05):
        features.extend([{'kind':kind,'start':float(t-.125),'t':float(t),'x':np.array([t])} for kind in ('state','snap')])
    review={'splits':[{'part':'train','start':0,'end':2},{'part':'validation','start':2.2,'end':4},{'part':'test','start':4.2,'end':6}],
      'state_intervals':[{'start':0,'end':6,'label':'none'}],
      'snap_events':[{'capture_t':1},{'capture_t':3},{'capture_t':5}],
      'negative_snap_intervals':[[0,6]]}
    return {'features':features},review


def test_reserved_features_and_labels_do_not_enter_training_records():
    capture,review=fixture();states,snaps=reviewed_records(capture,review)
    changed=copy.deepcopy(capture)
    for row in changed['features']:
        if row['start']>=4.2:row['x'][:]=999
    other_states,other_snaps=reviewed_records(changed,review)
    for a,b in ((states,other_states),(snaps,other_snaps)):
        np.testing.assert_array_equal([r['x'] for r in a if r['part']=='train'],[r['x'] for r in b if r['part']=='train'])
        assert all(r['end']<=2 for r in a if r['part']=='train')
        assert all(r['expected_events']==[5] for r in a if r['part']=='test' and 'expected_events' in r)
    review['splits'][1]['start']=1.5
    with pytest.raises(ValueError,match='overlap'):reviewed_records(capture,review)


def test_changed_review_source_fails_before_loading_model(tmp_path):
    import json
    source=tmp_path/'streams.jsonl';source.write_text('changed')
    review=tmp_path/'review.json';review.write_text(json.dumps({'source_directory':str(tmp_path),'source_hashes':{'streams.jsonl':'wrong'}}))
    with pytest.raises(ValueError,match='source changed'):train_camera_candidate(tmp_path/'missing-model',review,tmp_path/'output')
    assert not (tmp_path/'output').exists()
