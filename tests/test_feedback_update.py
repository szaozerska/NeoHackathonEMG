import pytest
from spelltrain.feedback_update import feedback_windows


def test_prospective_feedback_windows_do_not_overlap_and_holdout_is_separate():
    marks=[{'id':str(i),'gesture':('Nothing','Sword','Shield','Fireball')[i%4],
            'reported_at':i*3.,'review_window_start':i*3.+.8,'review_window_end':i*3.+4.8,'timing':'before'} for i in range(10)]
    features=[]
    for i in range(600):
        for kind in ('snap','state'):
            t=i*.05
            features.append({'kind':kind,'start':t-.2,'t':t,'x':[1,2]})
    capture={'path':'/capture','marks':marks,'features':features,'metadata':{'duration_seconds':31}}
    bags,states,manifest=feedback_windows(capture,True)
    assert len(manifest)==10
    assert all(m['end']<marks[i+1]['reported_at'] for i,m in enumerate(manifest[:-1]))
    assert all(not m['exact_event_times_verified'] for m in manifest)
    parts={part:{b['trial'] for b in bags if b['part']==part} for part in ('fit','validation','feedback_holdout')}
    assert not parts['fit']&parts['validation'] and not parts['fit']&parts['feedback_holdout']
    assert all(s['hand_state'] in ('none','fist','open') for s in states)
    marks[0]['timing']='after'
    with pytest.raises(ValueError,match='prospective'):feedback_windows(capture,True)
