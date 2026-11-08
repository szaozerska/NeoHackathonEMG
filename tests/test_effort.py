import json
import joblib
import numpy as np
import pytest
from spelltrain import effort
from spelltrain.session import Session


def fixture_records():
    rng=np.random.default_rng(7)
    rows=[]
    for round_ in (1,2,3):
        for level,amplitude in zip(effort.LEVELS,(5,25,100)):
            for movement in ('center','left','right'):
                for window in range(12):
                    rows.append({'trial':f'r{round_}-{level}-{movement}', 'round':round_,
                                 'condition':f'shield-{level}-{movement}', 'effort':level, 'movement':movement,
                                 'hand_state':'open','x':np.maximum(.01,rng.normal(amplitude,amplitude*.02,40))})
    return rows


def test_round_split_has_no_trial_or_test_leakage(tmp_path,monkeypatch):
    records=fixture_records()
    def dataset(*args):return records,[],{'subject':'test','side':'right','session_id':'fixture'},dict(effort.DEFAULT_SIGNAL)
    monkeypatch.setattr(effort,'effort_dataset',dataset)
    report=effort.fit_effort('unused',tmp_path/'one')
    artifact=joblib.load(tmp_path/'one/effort-model.joblib')
    original=artifact['model'].named_steps['logisticregression'].coef_.copy()
    scaler=artifact['model'].named_steps['standardscaler']
    training=[r for r in records if r['round']==1]
    expected=np.log1p(np.array([r['x'][:report['feature_columns']] for r in training])).mean(axis=0)
    np.testing.assert_allclose(scaler.mean_,expected)
    assert report['test']['trial_count']==9
    assert report['test']['correct_trials']==9
    assert report['test']['window_count']==108
    assert len(set(report['split']['train']['trials'])&set(report['split']['test']['trials']))==0
    # Changing test labels cannot alter model choice, preprocessing, or fitted weights.
    for row in records:
        if row['round']==3:
            row['effort']={'light':'firm','firm':'light','medium':'medium'}[row['effort']]
    other=effort.fit_effort('unused',tmp_path/'two')
    changed=joblib.load(tmp_path/'two/effort-model.joblib')
    assert other['selected_candidate']==report['selected_candidate']
    np.testing.assert_array_equal(original,changed['model'].named_steps['logisticregression'].coef_)
    assert other['test']['correct_trials']<9
    with pytest.raises(ValueError):effort.fit_effort('unused',tmp_path/'one')


def test_extraction_uses_sensor_clock_not_transport_gap_flags(tmp_path):
    session=Session(tmp_path/'recording','tester')
    trial={'id':'accepted','motion':'r1-light-hold','protocol':effort.PROTOCOL,'confirmed':True,'received':True,
           'start':1.,'end':5.,'repetition':1,'condition':'shield-light-center','intended_effort':'light',
           'intended_movement':'hold','hand_state':'open'}
    (session.directory/effort.LABEL_FILE).write_text(json.dumps([trial,{**trial,'id':'bad','confirmed':False}]))
    rng=np.random.default_rng(8)
    for seq in range(800):
        sensor_end=(seq+1)*16/2048
        # 20ms alternating delivery variation would break the old receive-time filter.
        received=(seq//4+1)*4/128+.1
        session.append({'kind':'emg','received':received,'t':received,'source_seq':seq,
                        'source_t':round(sensor_end*1e6),'gap':True,
                        'samples':np.clip(rng.normal(30000,40,(16,8)),0,65535).astype(int).tolist()})
    session.close()
    records,quality,_,_=effort.effort_dataset(session.directory)
    assert len(records)>30 and all(r['trial']==trial['motion'] for r in records)
    assert all(r['start']>=1.75 and r['end']<=4.25 for r in records)
    assert quality[0]['sequence_discontinuities']==0
    assert quality[0]['transport_gap_flags_ignored']>0
    assert quality[0]['timing_residual_abs_max_seconds']<.03


def test_live_effort_matches_offline_filter_and_resets_on_sequence_loss():
    # A small mock estimator exposes the feature input for equivalence checking.
    class Model:
        classes_=np.array(['firm','light','medium'])
        def predict_proba(self,x):
            scores=np.column_stack([x[:,0],x[:,1],x[:,2]])+1
            return scores/scores.sum(axis=1,keepdims=True)
    artifact={'task':'shield_relative_emg_effort','protocol':effort.PROTOCOL,'signal':dict(effort.DEFAULT_SIGNAL),
              'feature_columns':8,'model':Model()}
    predictor=effort.EffortPredictor(artifact)
    reference=effort.SignalWindows()
    rng=np.random.default_rng(4);observed=[];expected=[]
    for seq in range(96):
        row={'kind':'emg','source_seq':seq,'source_t':round((seq+1)*16/2048*1e6),
             'samples':rng.normal(30000,30,(16,8)).tolist(),'gap':True}
        observed+=predictor.feed(row)
        for window in reference.feed(row['samples'],effort.sensor_times(row)):
            if window['kind']=='state':
                expected.append(effort._ordered_prob(artifact['model'],np.array([window['x'][:8]]))[0])
    np.testing.assert_allclose([list(r['probabilities'].values()) for r in observed],expected)
    assert all(0<=r['effort_index']<=1 for r in observed)
    assert predictor.feed({**row,'source_seq':999})==[]
