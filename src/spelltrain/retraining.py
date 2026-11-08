"""Reference-reviewed supplemental retraining; test round never selects parameters."""
from collections import Counter
from pathlib import Path
import json
import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer,StandardScaler

from .common import write_json,read_json
from .effort import LEVELS,PROTOCOL,_hash,evaluate_effort,is_shield
from .gestures import (STATE_LEVELS,SNAP_COLUMNS,trial_weights,state_evaluation,GesturePredictor)
from .evaluation import event_metrics


class SupervisedSnapModel:
    def __init__(self,model,columns):self.model,self.columns=model,list(columns)
    def window_scores(self,x):
        p=self.model.predict_proba(np.asarray(x)[:,self.columns])
        return p[:,list(self.model.classes_).index('snap')]
    def clip_score(self,x):return float(np.max(self.window_scores(x)))


def supervised_weights(rows,key):
    pairs=Counter((r['trial'],r[key]) for r in rows)
    class_trials={label:{r['trial'] for r in rows if r[key]==label} for label in {r[key] for r in rows}}
    values=np.array([1/(pairs[r['trial'],r[key]]*len(class_trials[r[key]])) for r in rows])
    return values/values.sum()*len(values)


def prepare_records(cache,review):
    reviewed={r['trial']:r for r in review['trials']}
    states,efforts,snaps=[],[],[]
    for r in cache['records']:
        row=dict(r);local=r['local_trial'];condition=r['condition']
        if r['session']=='band-01':
            part='validation' if r['round']==2 else 'train'
            if r['kind']=='state' and r['hand_state'] in STATE_LEVELS:
                states.append({**row,'part':part})
                if is_shield(r):efforts.append({**row,'part':part})
            # Old positive snap clips have no independent event labels; don't invent them.
            if r['kind']=='snap' and condition!='snap':snaps.append({**row,'part':part,'snap_label':'negative'})
            continue
        annotation=reviewed[local]
        base_part='test' if r['round']==2 else 'train'
        if r['kind']=='state':
            for i,interval in enumerate(annotation['state_intervals']):
                if r['start']>=interval['start'] and r['end']<=interval['end']:
                    part=base_part
                    if r['round']==1 and condition=='open-close':part='validation'
                    states.append({**row,'part':part,'hand_state':interval['label'],
                        'trial':r['trial']+f'|segment-{i}' if condition in ('open-close','close-open') else r['trial'],
                        'parent_trial':r['trial']})
            if condition in ('shield-light','shield-medium','shield-firm'):
                efforts.append({**row,'part':base_part})
            # Ramps have participant effort-change instructions, not calibrated time-resolved force labels.
        else:
            part=base_part
            if r['round']==1 and condition in ('snap-4','snap-5','pinch','fingers','open-close'):
                part='validation'
            events=[e['session_seconds'] for e in annotation['snap_events']]
            positive=any(t-.05<=r['end']<=t+.125 for t in events)
            ambiguous=any(r['start']-.30<=t<=r['end']+.30 for t in events)
            label='snap' if positive else None if ambiguous else 'negative'
            snaps.append({**row,'part':part,'snap_label':label,'expected_events':events})
    # Every original clip is assigned as a unit for each task. No segment/window may straddle splits.
    for task in (states,efforts,snaps):
        assignment={}
        for r in task:
            key=(r['session'],r['local_trial'])
            if key in assignment and assignment[key]!=r['part']:
                raise ValueError('Clip crosses training/evaluation splits')
            assignment[key]=r['part']
    return states,efforts,snaps


def fit_state(training,validation):
    candidates={};scores={}
    for name,columns in (('log_rms',8),('log_amplitude',24)):
        model=make_pipeline(FunctionTransformer(np.log1p),StandardScaler(),
                            LogisticRegression(C=.1,max_iter=2000,random_state=7))
        model.fit(np.array([r['x'][:columns] for r in training]),[r['hand_state'] for r in training],
                  logisticregression__sample_weight=supervised_weights(training,'hand_state'))
        candidates[name]=(model,columns)
        scores[name]=state_evaluation(model,validation,columns)
    selected=max(candidates,key=lambda name:scores[name]['trial_macro_f1'])
    return *candidates[selected],{'selected':selected,'validation_candidates':scores}


def fit_effort(training,validation):
    candidates={};scores={}
    for name,columns in (('log_rms',8),('log_amplitude',24)):
        model=make_pipeline(FunctionTransformer(np.log1p),StandardScaler(),
                            LogisticRegression(C=.1,max_iter=2000,random_state=7))
        model.fit(np.array([r['x'][:columns] for r in training]),[r['effort'] for r in training],
                  logisticregression__sample_weight=supervised_weights(training,'effort'))
        candidates[name]=(model,columns)
        scores[name]=evaluate_effort(model,validation,columns)
    selected=max(candidates,key=lambda name:scores[name]['trial_macro_f1'])
    return *candidates[selected],{'selected':selected,'validation_candidates':scores}


def causal_snap_events(model,rows,threshold):
    # Same low-score rearm and 350ms refractory rule as GesturePredictor, reset at clip boundaries.
    scores=model.window_scores(np.array([r['x'] for r in rows]))
    rearmed=True;last=-float('inf');events=[]
    for score,row in zip(scores,rows):
        if score<.4:rearmed=True
        if score>=threshold and rearmed and row['end']-last>=.35:
            events.append(float(row['end']));last,rearmed=row['end'],False
    return events


def score_snap_events(model,rows,threshold,tolerance=.25):
    clips=[];total=Counter();errors=[];negative_seconds=0.;negative_false=0
    for trial in dict.fromkeys(r['trial'] for r in rows):
        block=[r for r in rows if r['trial']==trial]
        truth=block[0].get('expected_events',[])
        predicted=causal_snap_events(model,block,threshold)
        metric=event_metrics(truth,predicted,tolerance)
        for name in ('tp','fp','fn'):total[name]+=metric[name]
        errors+=metric['signed_timing_errors_seconds']
        if not truth:
            negative_seconds+=block[-1]['end']-block[0]['start'];negative_false+=len(predicted)
        clips.append({'trial':trial,'expected':truth,'predicted':predicted,**metric})
    tp,fp,fn=(total[k] for k in ('tp','fp','fn'))
    return {'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,
        'recall':tp/(tp+fn) if tp+fn else None,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,
        'event_count':tp+fn,'tolerance_seconds':tolerance,'threshold':threshold,
        'negative_false_events':negative_false,'negative_seconds':float(negative_seconds),
        'negative_false_events_per_minute':negative_false/(negative_seconds/60) if negative_seconds else None,
        'signed_timestamp_errors_seconds':errors,'physical_latency_measured':False,'clips':clips}


def fit_snap(training,validation):
    labeled=[r for r in training if r['snap_label'] is not None]
    if set(r['snap_label'] for r in labeled)!={'snap','negative'}:
        raise ValueError('Need independently reviewed snap events and negative windows')
    models={};validation_results={}
    for name,columns in SNAP_COLUMNS.items():
        model=make_pipeline(FunctionTransformer(np.log1p),StandardScaler(),
                            LogisticRegression(C=.1,max_iter=2000,random_state=7))
        model.fit(np.array([r['x'][columns] for r in labeled]),[r['snap_label'] for r in labeled],
                  logisticregression__sample_weight=supervised_weights(labeled,'snap_label'))
        wrapper=SupervisedSnapModel(model,columns)
        results=[score_snap_events(wrapper,validation,t) for t in (.55,.65,.75,.85,.9,.95,.98,.995,.999)]
        best=max(results,key=lambda v:(v['f1'],-v['fp'],v['threshold']))
        models[name]=wrapper;validation_results[name]={'selected':best,'thresholds':results}
    selected=max(models,key=lambda name:(validation_results[name]['selected']['f1'],
                                        -validation_results[name]['selected']['fp']))
    chosen=validation_results[selected]['selected']
    return models[selected],chosen['threshold'],{'selected':selected,'validation_candidates':validation_results,
        'supervision':'independent audio transient plus video action review',
        'training_positive_events':len({r['trial'] for r in labeled if r['snap_label']=='snap'}),
        'validation_positive_events':sum(len(v[0].get('expected_events',[])) for v in
            [[r for r in validation if r['trial']==trial] for trial in dict.fromkeys(r['trial'] for r in validation)])}


def transition_evaluation(model,columns,rows,review,threshold=.55):
    # Reference-derived events and stable intervals are separate from classifier predictions.
    clips=[]
    for annotation in review['trials']:
        if annotation['round']!=2 or not annotation['transition_events']:continue
        block=sorted([r for r in rows if r['local_trial']==annotation['trial'] and r['kind']=='state'],key=lambda r:r['end'])
        probabilities=model.predict_proba(np.array([r['x'][:columns] for r in block]))
        label,candidate,votes='none','none',0;last_bool=None;predicted=[]
        for row,p in zip(block,probabilities):
            best=int(p.argmax());next_=str(model.classes_[best]) if p[best]>=threshold else 'none'
            votes=votes+1 if candidate==next_ else 1;candidate=next_
            needed=1 if next_=='open' and label=='fist' else 2
            if votes>=needed:label=next_
            fist=label=='fist'
            # Ignore initial filter/debounce acquisition rather than counting it as a gesture transition.
            if row['end']<block[0]['end']+.15:last_bool=fist;continue
            if last_bool is not None and fist!=last_bool:predicted.append({'t':row['end'],'fist':fist})
            last_bool=fist
        expected=[{'t':e['session_seconds'],'fist':e['label']=='fist'} for e in annotation['transition_events']]
        used=set();matched=[]
        for target in expected:
            eligible=[i for i,p in enumerate(predicted) if i not in used and p['fist']==target['fist'] and abs(p['t']-target['t'])<=.75]
            if eligible:
                i=min(eligible,key=lambda i:abs(predicted[i]['t']-target['t']));used.add(i)
                matched.append({'target':target,'prediction':predicted[i],'approx_error_seconds':predicted[i]['t']-target['t']})
        clips.append({'trial':annotation['trial'],'expected':expected,'predicted':predicted,'matched':matched,
                      'tp':len(matched),'fn':len(expected)-len(matched),'fp':len(predicted)-len(matched)})
    tp=sum(c['tp'] for c in clips);fp=sum(c['fp'] for c in clips);fn=sum(c['fn'] for c in clips)
    return {'tp':tp,'fp':fp,'fn':fn,'tolerance_seconds':.75,'clips':clips,
            'note':'Approximate reference-aligned timing; uncalibrated hardware latency. Extra state toggles count as false transitions.'}


def retrain_reviewed(cache_path,review_path,old_path,output):
    output=Path(output)
    if output.exists():raise ValueError('Output exists; choose a new version')
    cache=joblib.load(cache_path);review=read_json(review_path);old=joblib.load(old_path)
    if _hash(Path(cache['sources'][1]['directory'])/'supplemental-trials-v4.json')!=review['source_labels_sha256']:
        raise ValueError('Reviewed reference labels no longer match source')
    for source in cache['sources']:
        directory=Path(source['directory'])
        meta=read_json(directory/'metadata.json')
        label_file='supplemental-trials-v4.json' if meta.get('training_profile')=='supplemental' else 'gesture-trials-v3.json'
        for filename,key in [('streams.jsonl','streams_sha256'),('metadata.json','metadata_sha256'),
                             (label_file,'labels_sha256')]:
            if _hash(directory/filename)!=source[key]:
                raise ValueError('Source changed after feature extraction: '+filename)
    for annotation in review['trials']:
        reference=Path(cache['sources'][1]['directory'])/annotation['reference_file']
        if _hash(reference)!=annotation['reference_sha256']:
            raise ValueError('Reference changed after review')
    states,efforts,snaps=prepare_records(cache,review)
    split=lambda rows,part:[r for r in rows if r['part']==part]
    state,columns,sr=fit_state(split(states,'train'),split(states,'validation'))
    effort,ecols,er=fit_effort(split(efforts,'train'),split(efforts,'validation'))
    snap,threshold,fr=fit_snap(split(snaps,'train'),split(snaps,'validation'))
    output.mkdir(parents=True,exist_ok=False)
    frozen=output/'frozen-before-test.joblib'
    joblib.dump({'state':state,'state_columns':columns,'effort':effort,'effort_columns':ecols,
                 'snap':snap,'snap_threshold':threshold,'signal':cache['signal']},frozen)
    # All selection is complete before either old or new model sees supplemental round 2.
    test_states=split(states,'test');test_effort=split(efforts,'test');test_snap=split(snaps,'test')
    steady=[r for r in test_states if r['condition'] not in ('close-open','open-close')]
    sr['test_steady']=state_evaluation(state,steady,columns)
    sr['test_reviewed_segments']=state_evaluation(state,test_states,columns)
    sr['test_transitions']=transition_evaluation(state,columns,[r for r in cache['records'] if r['session']=='band-02'],review)
    er['test']=evaluate_effort(effort,test_effort,ecols)
    fr['test']=score_snap_events(snap,test_snap,threshold)
    fr['test_tolerance_sensitivity']={str(t):score_snap_events(snap,test_snap,threshold,t) for t in (.1,.5)}
    baseline={'state_steady':state_evaluation(old['state_model'],steady,old['state_columns']),
        'state_segments':state_evaluation(old['state_model'],test_states,old['state_columns']),
        'shield_effort':evaluate_effort(old['effort_artifact']['model'],test_effort,old['effort_artifact']['feature_columns']),
        'snap_events':score_snap_events(old['snap_model'],test_snap,old['snap_threshold'])}
    report={'schema':1,'task':'reference_reviewed_gesture_update','subject':'player-a','side':'right','protocol':PROTOCOL,
      'source':cache['sources'][1],'sources':cache['sources'],'review_sha256':_hash(review_path),
      'old_model_sha256':_hash(old_path),'signal':cache['signal'],'quality':cache['quality'],
      'frozen_before_test_sha256':_hash(frozen),
      'hand_state':sr,'shield_effort':er,'fireball_snap':fr,'old_model_same_test':baseline,
      'split':{task:{part:sorted({r['trial'] for r in rows if r['part']==part}) for part in ('train','validation','test')}
               for task,rows in [('state',states),('effort',efforts),('snap',snaps)]},
      'limitations':[
       'Supplemental round 2 is held out by complete clips; round 1 from the same wearing session contributes training. Not independent-session gameplay accuracy.',
       'Only three steady fist test trials, three effort test trials, five individual snap test events and four intentional fist transitions.',
       'Reference video/audio and source-uptime alignment are approximate. Hardware latency is not calibrated. Snap event scores use a 250ms matching tolerance; physical latency is unmeasured.',
       'Reported forearm effort remains subjective. No contact force, continuous proportional shield-strength calibration or Quest pose/throw accuracy is established.',
       'The old band-01 round-3 test was previously inspected and is now development/training data, not an untouched test.',
       'No refit or threshold adjustment was made after scoring supplemental round 2. Old and updated rates on this same test are directly comparable; older report rates used different trials.']}
    effort_artifact={'schema':1,'task':'shield_relative_emg_effort','protocol':PROTOCOL,'model':effort,
         'feature_columns':ecols,'levels':LEVELS,'signal':cache['signal'],'report':report}
    artifact={'schema':1,'task':'v3_gesture_bundle','protocol':PROTOCOL,'signal':cache['signal'],
       'state_model':state,'state_columns':columns,'state_threshold':.55,'snap_model':snap,'snap_threshold':threshold,
       'snap_event_supervision':'reference_reviewed','effort_artifact':effort_artifact,'report':report}
    joblib.dump(artifact,output/'model.joblib')
    joblib.dump({'task':'v4_hand_state','model':state,'columns':columns,'report':sr},output/'hand-state-model.joblib')
    joblib.dump(effort_artifact,output/'effort-model.joblib')
    joblib.dump({'task':'reference_reviewed_snap','model':snap,'threshold':threshold,'report':fr},output/'snap-model.joblib')
    write_json(output/'training-report.json',report)
    write_json(output/'reviewed-labels.json',review)
    write_json(output/'test-predictions.json',{'state':sr['test_reviewed_segments'],'effort':er['test'],
                                             'snap':fr['test'],'transitions':sr['test_transitions']})
    return report
