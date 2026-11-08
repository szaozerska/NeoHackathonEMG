"""Fit an isolated v4-based EMG candidate using independently reviewed media.
Classifier training and selection never consult reserved test blocks.
"""
import copy
from pathlib import Path
import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer,StandardScaler
from .common import read_json,write_json
from .effort import _hash
from .retraining import prepare_records,supervised_weights,SupervisedSnapModel,score_snap_events,fit_state
from .gestures import state_evaluation,SNAP_COLUMNS


def reviewed_records(capture,review):
    splits=review['splits'];states=[];snaps=[]
    for i,a in enumerate(splits):
        for b in splits[i+1:]:
            if max(a['start'],b['start'])<min(a['end'],b['end']):raise ValueError('Review split overlap')
    for f in capture['features']:
        part=next((p['part'] for p in splits if f['start']>=p['start'] and f['t']<=p['end']),None)
        if part is None:continue
        trial='camera-live:'+part
        if f['kind']=='state':
            for i,interval in enumerate(review['state_intervals']):
                if f['start']>=interval['start']+.15 and f['t']<=interval['end']-.15:
                    states.append({'x':f['x'],'start':f['start'],'end':f['t'],'part':part,'trial':trial+':state-'+str(i),'hand_state':interval['label']})
        else:
            events=[e['capture_t'] for e in review['snap_events'] if next((p['part'] for p in splits if p['start']<=e['capture_t']<=p['end']),None)==part]
            positive=any(t-.05<=f['t']<=t+.125 for t in events)
            ambiguous=any(f['start']-.3<=t<=f['t']+.3 for t in events)
            negative=any(f['start']>=a and f['t']<=b for a,b in review['negative_snap_intervals'])
            if not negative and not ambiguous:continue
            snaps.append({'x':f['x'],'start':f['start'],'end':f['t'],'part':part,'trial':trial,
                          'snap_label':'snap' if positive else None if ambiguous else 'negative','expected_events':events})
    return states,snaps


def train_camera_candidate(base_path,review_path,output):
    output=Path(output)
    if output.exists():raise ValueError('Choose a new candidate directory')
    review=read_json(review_path);source=Path(review['source_directory'])
    for name,digest in review['source_hashes'].items():
        if _hash(source/name)!=digest:raise ValueError('Review source changed: '+name)
    from .feedback_update import capture_features
    capture=capture_features(source);live_states,live_snaps=reviewed_records(capture,review)
    base=joblib.load(base_path);cache=joblib.load(Path(review_path).parent.parent/'reference-review-v4/features.joblib')
    old_review=read_json(Path(review_path).parent.parent/'reference-review-v4/reviewed-labels.json')
    states,_,snaps=prepare_records(cache,old_review)
    part=lambda rows,name:[r for r in rows if r['part']==name]
    old_train=part(snaps,'train');new_train=part(live_snaps,'train');old_val=part(snaps,'validation');new_val=part(live_snaps,'validation')
    labeled=[r for r in old_train+new_train if r['snap_label'] is not None]
    # Fix candidates before viewing the test results; baseline itself is a valid selection.
    candidates=[('unchanged_v4',base['snap_model'],base['snap_threshold'])]
    for name,columns in SNAP_COLUMNS.items():
        for c in (.03,.1,.3):
            model=make_pipeline(FunctionTransformer(np.log1p),StandardScaler(),LogisticRegression(C=c,max_iter=2000,random_state=7))
            model.fit(np.array([r['x'][columns] for r in labeled]),[r['snap_label'] for r in labeled],logisticregression__sample_weight=supervised_weights(labeled,'snap_label'))
            wrapper=SupervisedSnapModel(model,columns)
            for threshold in (.65,.75,.85,.9,.95,.98,.995,.999):candidates.append((name+':C='+str(c),wrapper,threshold))
    scored=[]
    for name,model,threshold in candidates:
        old_score=score_snap_events(model,old_val,threshold);new_score=score_snap_events(model,new_val,threshold)
        scored.append({'name':name,'model':model,'threshold':threshold,'old_validation':old_score,'live_validation':new_score,
                       'selection_f1':(old_score['f1']+new_score['f1'])/2})
    selected=max(scored,key=lambda c:(c['selection_f1'],-c['old_validation']['fp']-c['live_validation']['fp'],c['threshold']))
    state_model,columns,state_selection=fit_state(part(states,'train')+part(live_states,'train'),part(states,'validation')+part(live_states,'validation'))
    state_candidates=[('unchanged_v4',base['state_model'],base['state_columns']),('reviewed_camera_fit',state_model,columns)]
    state_scores=[]
    for name,model,cols in state_candidates:
        old_score=state_evaluation(model,part(states,'validation'),cols);new_score=state_evaluation(model,part(live_states,'validation'),cols)
        state_scores.append({'name':name,'model':model,'columns':cols,'old_validation':old_score,'live_validation':new_score,'selection':(old_score['trial_macro_f1']+new_score['trial_macro_f1'])/2})
    chosen=max(state_scores,key=lambda c:c['selection'])
    candidate=copy.deepcopy(base);candidate.update(state_model=chosen['model'],state_columns=chosen['columns'],snap_model=selected['model'],snap_threshold=selected['threshold'])
    output.mkdir(parents=True);joblib.dump(candidate,output/'frozen-before-test.joblib')
    evaluate=lambda artifact:{'snap':score_snap_events(artifact['snap_model'],part(live_snaps,'test'),artifact['snap_threshold']),
                              'state':state_evaluation(artifact['state_model'],part(live_states,'test'),artifact['state_columns'])}
    report={'task':'v4_camera_review_candidate','model_version':'v4-camera-candidate-01','base_model_sha256':_hash(base_path),'review_sha256':_hash(review_path),
        'frozen_before_test_sha256':_hash(output/'frozen-before-test.joblib'),'source':str(source),'splits':review['splits'],
        'selection_snap':{k:v for k,v in selected.items() if k!='model'},'selection_state':{k:v for k,v in chosen.items() if k!='model'},
        'validation_candidates':[ {k:v for k,v in c.items() if k!='model'} for c in scored],
        'test':{'base':evaluate(base),'candidate':evaluate(candidate)},
        'known_reference_regression':{'snap':score_snap_events(candidate['snap_model'],part(snaps,'test'),candidate['snap_threshold']),
                                      'state':state_evaluation(candidate['state_model'],part(states,'test'),candidate['state_columns'])},
        'effort_updated':False,'automatically_activated':False,
        'limitations':['Test blocks share one continuous wearing session with training. Not independent-session accuracy.',
          'Only seven new check snaps; two have visual-only approximate timing. Event matching tolerance 250ms; hardware latency uncalibrated.',
          'Media review labels actions, not physical forearm force. Effort weights unchanged.',
          'No v5/v6 feedback weights or pseudo-labels are used. Baseline v4 and its runtime remain unchanged.']}
    candidate['report']=report
    joblib.dump(candidate,output/'model.joblib');write_json(output/'training-report.json',report)
    joblib.dump({'model':candidate['state_model'],'columns':candidate['state_columns']},output/'hand-state-model.joblib')
    joblib.dump({'model':candidate['snap_model'],'threshold':candidate['snap_threshold']},output/'snap-model.joblib')
    joblib.dump(candidate['effort_artifact'],output/'effort-model.joblib')
    return report
