import numpy as np
import pytest
from spelltrain.models import unique_sessions,label_window
from spelltrain.evaluation import event_metrics
from spelltrain.session import Session
from spelltrain.common import annotation_valid


def test_events_match_one_to_one():
    m=event_metrics([1.,2.],[1.01,1.02,2.05],.1)
    assert (m['tp'],m['fp'],m['fn'])==(2,1,0)
    assert event_metrics([],[],.1)['recall'] is None


def test_annotation_unverified_excluded_and_crossing_boundaries_excluded():
    row={'id':'x','label':'fist','start':1.,'end':2.,'trial_id':'one','verified':False}
    assert label_window({'kind':'state','start':1.1,'t':1.3},[row]) is None
    row['verified']=True
    assert label_window({'kind':'state','start':.9,'t':1.3},[row]) is None
    assert label_window({'kind':'state','start':1.1,'t':1.3},[row])==('fist','one')


def test_session_split_rejects_duplicate(tmp_path):
    s=Session(tmp_path/'one','person');s.close()
    with pytest.raises(ValueError,match='disjoint'):
        unique_sessions([str(tmp_path/'one')],[str(tmp_path/'one')])


def test_interval_and_event_validation():
    with pytest.raises(ValueError):
        annotation_valid({'id':'x','label':'snap','start':1,'end':2,'trial_id':'t'})
    with pytest.raises(ValueError):
        annotation_valid({'id':'x','label':'fist','start':float('nan'),'end':2,'trial_id':'t'})
