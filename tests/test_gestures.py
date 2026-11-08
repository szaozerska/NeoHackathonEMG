import copy
import numpy as np
import pytest
from spelltrain import gestures
from spelltrain.signals import DEFAULT_SIGNAL,SignalWindows
from spelltrain.effort import sensor_times
from spelltrain.shield_training import protocol,PROTOCOL


def records_fixture():
    rng=np.random.default_rng(42)
    rows=[]
    for trial in protocol('test'):
        label=trial['hand_state']
        template=np.full(40,2.)
        if label=='open':template[:4]=30
        if label=='fist':template[4:8]=30
        for i in range(12):
            rows.append({'kind':'state','trial':trial['id'],'round':trial['repetition'],
                'condition':trial['condition'],'hand_state':label,
                'x':np.maximum(.01,template+rng.normal(0,.1,40)), 'end':i*.05})
        for i in range(32):
            template=np.ones(160)
            if trial['condition']=='snap' and i in (8,9,22,23):
                template[:8]=30  # Intermittent temporal bursts; other positive-clip windows are background.
            rows.append({'kind':'snap','trial':trial['id'],'round':trial['repetition'],
                'condition':trial['condition'],'hand_state':label,
                'x':np.maximum(.01,template+rng.normal(0,.03,160)),'end':i*.016})
    return rows


def test_trial_splits_and_test_features_never_change_fit_or_selection():
    rows=records_fixture()
    bundle,report,_=gestures.fit_baselines(rows)
    assert report['hand_state']['test']['correct_trials']==13
    snap=report['fireball_snap']['test']
    assert snap['tp']==1 and snap['fp']==0
    assert snap['event_precision'] is None and snap['event_recall'] is None
    assert snap['positive_clips']==1
    changed=copy.deepcopy(rows)
    for r in changed:
        if r['round']==3:r['x'][:]=1.
    other,other_report,_=gestures.fit_baselines(changed)
    assert report['hand_state']['selected']==other_report['hand_state']['selected']
    assert report['fireball_snap']['selected']==other_report['fireball_snap']['selected']
    np.testing.assert_array_equal(bundle['state_model'].named_steps['logisticregression'].coef_,
                                  other['state_model'].named_steps['logisticregression'].coef_)
    np.testing.assert_array_equal(bundle['snap_model'].coef_,other['snap_model'].coef_)
    np.testing.assert_array_equal(bundle['snap_model'].scaler.mean_,other['snap_model'].scaler.mean_)
    assert other['snap_threshold']==bundle['snap_threshold']
    splits=[set(report['split'][part]['snap_clips']) for part in ('train','validation','test')]
    assert not splits[0]&splits[1] and not splits[0]&splits[2] and not splits[1]&splits[2]


def test_weak_supervision_is_clip_level_and_training_scaler_has_no_validation_data():
    rows=records_fixture();bags=gestures.snap_bags(rows)
    training=[b for b in bags if b['round']==1]
    model=gestures.WeakSnapModel(gestures.SNAP_COLUMNS['temporal_rms']).fit(training)
    positive=next(b for b in training if b['positive'])
    assert model.clip_score(positive['x'])>.5
    scores=model.window_scores(positive['x'])
    assert scores[8]>scores[0]  # Does not assign positive targets to every window in this clip.
    expected=np.mean([np.log1p(b['x'][:,model.columns]).mean(axis=0) for b in training],axis=0)
    np.testing.assert_allclose(model.scaler.mean_,expected)
    assert model.fit_diagnostics['positive_training_clips']==1
    with pytest.raises(ValueError):model.fit([b for b in training if not b['positive']])


class AlwaysState:
    classes_=np.array(['fist','none','open'])
    def predict_proba(self,x):return np.tile([.01,.01,.98],(len(x),1))

class AlwaysEffort:
    classes_=np.array(['firm','light','medium'])
    def predict_proba(self,x):return np.tile([.6,.1,.3],(len(x),1))

class CandidateSnap:
    def window_scores(self,x):return np.full(len(x),.99)


def test_causal_bundle_ignores_host_jitter_resets_actual_sequence_loss_and_gates_weak_snaps():
    artifact={'task':'v3_gesture_bundle','protocol':PROTOCOL,'signal':dict(DEFAULT_SIGNAL),
              'state_model':AlwaysState(),'state_columns':8,'state_threshold':.55,
              'snap_model':CandidateSnap(),'snap_threshold':.8,
              'effort_artifact':{'model':AlwaysEffort(),'feature_columns':8,'levels':('light','medium','firm')}}
    normal=gestures.GesturePredictor(artifact)
    experimental=gestures.GesturePredictor(artifact,experimental_snaps=True)
    reference=SignalWindows();output=[];enabled=[];expected=[]
    rng=np.random.default_rng(5)
    for seq in range(100):
        row={'kind':'emg','source_seq':seq,'source_t':round((seq+1)*16/2048*1e6),
             'received':(seq//4+1)*4/128,'samples':rng.normal(30000,30,(16,8)).tolist(),'gap':True}
        output+=normal.feed(row);enabled+=experimental.feed(row)
        expected+=reference.feed(row['samples'],sensor_times(row))
    assert len([r for r in output if r['kind']=='state'])==sum(f['kind']=='state' for f in expected)
    assert any(r['kind']=='snap_candidate' for r in output)
    assert not any(r['kind']=='snap' for r in output)
    assert any(r['kind']=='snap' and r['verified_event_model'] is False for r in enabled)
    assert all(abs(r['effort_index']-.75)<1e-9 for r in output if r['kind']=='effort')
    assert normal.feed({**row,'source_seq':999})==[]
    assert normal.label=='none'


def test_candidate_rearming_refractory_and_missing_event_metrics():
    scores=[.9,.95,.2,.9,.2,.95]
    times=[0.,.05,.1,.2,.3,.4]
    assert gestures.candidate_indices(scores,times,.8)==[0,5]
    # Threshold crossings are not passed off as verified snap timestamps.
    class Scores:
        def window_scores(self,x):return x[:,0]
    bags=[{'trial':'positive','positive':True,'x':np.array([[.2],[.9],[.1]]),'times':np.array([0.,.2,.4])},
          {'trial':'negative','positive':False,'x':np.array([[.1],[.9],[.1]]),'times':np.array([0.,.2,.4])}]
    result=gestures.candidate_evaluation(Scores(),bags,.8)
    assert result['tp']==1 and result['fp']==1
    assert result['negative_candidate_events']==1
    assert result['snap_event_precision'] is None
    assert result['snap_event_latency'] is None


def test_frozen_evaluation_rejects_reusing_training_session(tmp_path,monkeypatch):
    source={'subject':'a','side':'right','streams_sha256':'identical','directory':'/original'}
    def data(*args,**kwargs):return [],[],dict(source),dict(DEFAULT_SIGNAL)
    monkeypatch.setattr(gestures,'effort_dataset',data)
    with pytest.raises(ValueError,match='used for fitting'):
        gestures.evaluate_gestures(['copied-session'],{'report':{'source':source}},tmp_path/'evaluation')
    assert not (tmp_path/'evaluation').exists()


def test_reference_reviewed_bundle_emits_supervised_snap_events_without_weak_model_opt_in():
    artifact={'task':'v3_gesture_bundle','protocol':PROTOCOL,'signal':dict(DEFAULT_SIGNAL),
              'state_model':AlwaysState(),'state_columns':8,'state_threshold':.55,
              'snap_model':CandidateSnap(),'snap_threshold':.8,
              'snap_event_supervision':'reference_reviewed',
              'effort_artifact':{'model':AlwaysEffort(),'feature_columns':8,'levels':('light','medium','firm')}}
    predictor=gestures.GesturePredictor(artifact)
    rng=np.random.default_rng(123);events=[]
    for seq in range(100):
        events+=predictor.feed({'kind':'emg','source_seq':seq,'source_t':round((seq+1)*16/2048*1e6),
          'received':seq/128,'samples':rng.normal(30000,30,(16,8)).tolist(),'gap':True})
    snaps=[e for e in events if e['kind']=='snap']
    assert snaps and all(e['verified_event_model'] for e in snaps)
    assert not any(e['kind']=='snap_candidate' for e in events)


def test_optional_snap_diagnostics_preserve_every_window_without_changing_events():
    artifact={'task':'v3_gesture_bundle','protocol':PROTOCOL,'signal':dict(DEFAULT_SIGNAL),
              'state_model':AlwaysState(),'state_columns':8,'state_threshold':.55,
              'snap_model':CandidateSnap(),'snap_threshold':.8,'snap_event_supervision':'reference_reviewed',
              'effort_artifact':{'model':AlwaysEffort(),'feature_columns':8,'levels':('light','medium','firm')}}
    normal=gestures.GesturePredictor(artifact);diagnostic=gestures.GesturePredictor(artifact,diagnostics=True)
    rng=np.random.default_rng(54);a=[];b=[]
    for seq in range(100):
        packet={'kind':'emg','source_seq':seq,'source_t':round((seq+1)*16/2048*1e6),
                'samples':rng.normal(30000,30,(16,8)).tolist()}
        a+=normal.feed(packet);b+=diagnostic.feed(packet)
    scores=[v for v in b if v['kind']=='snap_score']
    assert len(scores)>10
    assert a==[v for v in b if v['kind']!='snap_score']
    assert all(v['window_start']<v['source_t'] and v['threshold']==.8 for v in scores)
