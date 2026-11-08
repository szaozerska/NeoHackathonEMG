import numpy as np
from spelltrain.retraining import prepare_records,supervised_weights,fit_snap,score_snap_events


def test_weights_balance_labels_and_trials_without_window_pseudoreplication():
    rows=[{'trial':'a','y':'snap'}]*2+[{'trial':'a','y':'negative'}]*20+[{'trial':'b','y':'negative'}]*40
    weights=supervised_weights(rows,'y')
    assert abs(sum(w for w,r in zip(weights,rows) if r['y']=='snap')-len(rows)/2)<1e-9
    negative_a=sum(w for w,r in zip(weights,rows) if r['y']=='negative' and r['trial']=='a')
    negative_b=sum(w for w,r in zip(weights,rows) if r['trial']=='b')
    assert abs(negative_a-negative_b)<1e-9


def test_reviewed_windows_do_not_cross_posture_boundaries_or_label_unknown_snap_windows():
    base={'session':'band-02','local_trial':'r2-close-open','trial':'band-02:r2-close-open',
          'condition':'close-open','round':2,'hand_state':'unlabeled','kind':'state','effort':'unspecified'}
    cache={'records':[{**base,'start':0.,'end':.2},{**base,'start':.9,'end':1.1},
                      {**base,'start':1.2,'end':1.4},
                      {**base,'kind':'snap','start':.88,'end':1.0},
                      {**base,'kind':'snap','start':.7,'end':.82}]}
    review={'trials':[{'trial':'r2-close-open','state_intervals':[{'start':0.,'end':1.,'label':'none'},
        {'start':1.2,'end':2.,'label':'fist'}], 'snap_events':[{'session_seconds':1.0}]}]}
    states,_,snaps=prepare_records(cache,review)
    assert [r['hand_state'] for r in states]==['none','fist']
    assert all(r['part']=='test' for r in states+snaps)
    assert [r['snap_label'] for r in snaps]==['snap',None]


def test_supervised_snap_selection_and_one_to_one_event_scoring():
    def make(trial):
        rows=[]
        for i,t in enumerate(np.arange(0.,2.,.016)):
            positive=1.<=t<=1.125
            x=np.ones(160)
            if positive:x[:8]=40
            label='snap' if positive else None if .6<t<1.4 else 'negative'
            rows.append({'trial':trial,'start':t-.12,'end':float(t),'x':x,
                         'snap_label':label,'expected_events':[1.]})
        return rows
    model,threshold,report=fit_snap(make('fit'),make('validation'))
    result=score_snap_events(model,make('test'),threshold)
    assert result['tp']==1 and result['fp']==result['fn']==0
    assert result['physical_latency_measured'] is False
    assert report['training_positive_events']==1
