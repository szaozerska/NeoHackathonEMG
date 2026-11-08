"""Conservative v5 calibration from logged intent windows and prior references.

Reported snap clips provide multiple-instance labels, never guessed point events.
"""
import copy
from pathlib import Path
import json
import joblib
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit,logsumexp
from .common import read_json,write_json,json_lines
from .signals import SignalWindows
from .effort import sensor_times,_hash
from .retraining import prepare_records,supervised_weights,fit_state,score_snap_events
from .gestures import state_evaluation


def capture_features(directory, include_waveforms=False):
    directory=Path(directory);meta=read_json(directory/'metadata.json')
    if not meta.get('recording_complete'):raise ValueError('Finish the feedback recording first')
    rows=[r for r in json_lines(directory/'streams.jsonl') if r['kind']=='emg']
    offset=float(np.median([r['packet']['source_uptime']-meta['started_host_uptime']-r['packet']['source_t']/1e6 for r in rows]))
    windows=SignalWindows(meta['model']['signal'], include_waveforms=include_waveforms);features=[];last=None;gaps=0
    for r in rows:
        packet=r['packet']
        if last is not None and packet['source_seq']!=last+1:windows.reset();gaps+=1
        last=packet['source_seq']
        for f in windows.feed(packet['samples'],sensor_times(packet)):
            features.append({**f,'start':f['start']+offset,'t':f['t']+offset})
    return {'features':features,'marks':read_json(directory/'corrections.json'),'metadata':meta,
            'path':str(directory.resolve()),'sequence_gaps':gaps,
            'hashes':{name:_hash(directory/name) for name in ('streams.jsonl','metadata.json','corrections.json')}}


def feedback_windows(capture,prospective,parts=None):
    bags=[];states=[];manifest=[];marks=capture['marks']
    for i,mark in enumerate(marks):
        if mark['gesture'] not in ('Nothing','Sword','Shield','Fireball'):continue  # Transition clips require event/interval review first.
        if prospective:
            if mark.get('timing')!='before':raise ValueError('Latest calibration expects prospective cues')
            part=parts[i] if parts is not None else ('fit' if i in (0,1,2,4) else 'validation' if i in (3,5) else 'feedback_holdout')
            start=mark['reported_at']+.05
            end=min(mark['review_window_end']-.1,marks[i+1]['reported_at']-.1 if i+1<len(marks) else capture['metadata']['duration_seconds']-.1)
            stable_start=mark['review_window_start']+.4
        else:
            part='fit' if i<=6 else 'feedback_holdout'
            if mark['gesture']=='Fireball':start=(marks[i-1]['reported_at']+.1 if i else 0.);end=mark['reported_at']-.1
            else:start=mark['reported_at']-1.5;end=mark['reported_at']-.25
            stable_start=start
        if end-start<.5:continue
        trial=Path(capture['path']).name+':'+mark['id']
        snap_rows=[r for r in capture['features'] if r['kind']=='snap' and r['start']>=start and r['t']<=end]
        if not snap_rows:continue
        bags.append({'trial':trial,'part':part,'gesture':mark['gesture'],'positive':mark['gesture']=='Fireball',
                     'x':np.array([r['x'] for r in snap_rows]),'rows':snap_rows,'start':start,'end':end})
        manifest.append({'trial':trial,'part':part,'gesture':mark['gesture'],'start':start,'end':end,
                         'exact_event_times_verified':False,'source':'participant_intent_cue' if prospective else 'participant_report_with_confirmed_delay'})
        if mark['gesture']!='Fireball':
            label={'Nothing':'none','Sword':'fist','Shield':'open'}[mark['gesture']]
            for r in capture['features']:
                if r['kind']=='state' and r['start']>=stable_start and r['t']<=end:
                    states.append({'trial':trial,'part':part,'hand_state':label,'x':r['x'],'start':r['start'],'end':r['t']})
    return bags,states,manifest


def bag_scores(model,bags,threshold):
    return [{'trial':b['trial'],'gesture':b['gesture'],'positive':b['positive'],
             'score':float(max(model.window_scores(b['x']))),
             'predicted':bool(max(model.window_scores(b['x']))>=threshold)} for b in bags]


def update_feedback(old_path,reference_cache,reference_labels,older_capture,latest_capture,output,extra_capture=None,model_version="v5"):
    output=Path(output)
    if output.exists():raise ValueError('Output already exists')
    old=joblib.load(old_path);cache=joblib.load(reference_cache);review=read_json(reference_labels)
    states,_,snap=prepare_records(cache,review)
    captures=[capture_features(older_capture),capture_features(latest_capture)]
    bags=[];new_states=[];manifest=[]
    for c,prospective in zip(captures,(False,True)):
        b,s,m=feedback_windows(c,prospective);bags+=b;new_states+=s;manifest+=m
    if extra_capture is not None:
        extra=capture_features(extra_capture);captures.append(extra)
        # Predetermined clip split: four snaps for fit, one validation, one check.
        parts=['fit','fit','fit','fit','fit','validation','fit','feedback_holdout','feedback_holdout','feedback_holdout']
        if len(extra['marks'])!=len(parts):raise ValueError('Expected ten reviewed intent cues for extra capture')
        b,s,m=feedback_windows(extra,True,parts=parts);bags+=b;new_states+=s;manifest+=m
    old_fit=[r for r in snap if r['part']=='train' and r['snap_label'] is not None]
    old_validation=[r for r in snap if r['part']=='validation']
    fitting=[b for b in bags if b['part']=='fit'];validation=[b for b in bags if b['part']=='validation']
    original=old['snap_model'];theta0=np.r_[original.model.named_steps['logisticregression'].coef_[0],original.model.named_steps['logisticregression'].intercept_[0]]
    transform=lambda x:original.model[:-1].transform(x[:,original.columns])
    x=transform(np.array([r['x'] for r in old_fit]));y=np.array([r['snap_label']=='snap' for r in old_fit],float)
    weights=supervised_weights(old_fit,'snap_label')
    # Rotating/closing fists are known hard negatives, not post-hoc gesture vetoes.
    weights*=np.array([3. if r['hand_state']=='fist' and r['snap_label']=='negative' else 1. for r in old_fit]);weights/=weights.sum()
    matrices=[transform(b['x']) for b in fitting];targets=np.array([b['positive'] for b in fitting],float)
    bag_weights=np.array([.5/sum(targets==target) for target in targets]);temperature=.3
    candidates=[]
    for penalty in (.03,.1,.3,1.):
        def objective(theta):
            z=x@theta[:-1]+theta[-1];delta=theta-theta0
            loss=float(np.sum(weights*(np.logaddexp(0,z)-y*z))+.5*penalty*(delta@delta))
            residual=weights*(expit(z)-y);grad=np.r_[x.T@residual,residual.sum()]+penalty*delta
            for matrix,target,weight in zip(matrices,targets,bag_weights):
                z=(matrix@theta[:-1]+theta[-1])/temperature;n=logsumexp(z)
                pooled=temperature*(n-np.log(len(matrix)))
                loss+=weight*(np.logaddexp(0,pooled)-target*pooled)
                d=weight*(expit(pooled)-target);grad[:-1]+=d*(np.exp(z-n)@matrix);grad[-1]+=d
            return loss,grad
        fit=minimize(objective,theta0,jac=True,method='L-BFGS-B',options={'maxiter':400,'ftol':1e-10})
        if not fit.success:raise ValueError(str(fit.message))
        model=copy.deepcopy(original);clf=model.model.named_steps['logisticregression'];clf.coef_=fit.x[:-1][None,:];clf.intercept_=fit.x[-1:]
        options=[]
        for threshold in (.65,.75,.85,.9,.95,.98,.995,.999):
            event=score_snap_events(model,old_validation,threshold)
            predicted=bag_scores(model,validation,threshold)
            correct=sum(p['positive']==p['predicted'] for p in predicted)
            options.append({'threshold':threshold,'prior_validation_event_f1':event['f1'],'prior_validation_fp':event['fp'],
                            'new_validation_correct':correct,'new_validation_count':len(predicted)})
        chosen=max(options,key=lambda v:(v['new_validation_correct'],v['prior_validation_event_f1'],-v['prior_validation_fp'],v['threshold']))
        candidates.append({'penalty':penalty,'model':model,'choice':chosen,'options':options,'change':float(np.linalg.norm(fit.x-theta0))})
    selected=max(candidates,key=lambda c:(c['choice']['new_validation_correct'],c['choice']['prior_validation_event_f1'],
                                        -c['choice']['prior_validation_fp'],-c['change']))
    state_fit=[r for r in states if r['part']=='train']+[r for r in new_states if r['part']=='fit']
    state_val=[r for r in states if r['part']=='validation']+[r for r in new_states if r['part']=='validation']
    state_model,columns,state_report=fit_state(state_fit,state_val)
    new=copy.deepcopy(old);new['state_model']=state_model;new['state_columns']=columns
    new['snap_model']=selected['model'];new['snap_threshold']=selected['choice']['threshold']
    output.mkdir(parents=True,exist_ok=False)
    joblib.dump(new,output/'frozen-before-feedback-check.joblib')
    holdout=[b for b in bags if b['part']=='feedback_holdout']
    new_holdout=bag_scores(new['snap_model'],holdout,new['snap_threshold']);old_holdout=bag_scores(old['snap_model'],holdout,old['snap_threshold'])
    regression=score_snap_events(new['snap_model'],[r for r in snap if r['part']=='test'],new['snap_threshold'])
    state_test=[r for r in new_states if r['part']=='feedback_holdout']
    report={'task':model_version+'_feedback_equipment_model','model_version':model_version,'subject':'player-a','side':'right',
      'base_model_sha256':_hash(old_path),'frozen_before_test_sha256':_hash(output/'frozen-before-feedback-check.joblib'),
      'captures':[{k:v for k,v in c.items() if k not in ('features','marks')} for c in captures],
      'label_manifest':manifest,'selected_snap':{k:v for k,v in selected.items() if k!='model'},
      'snap_candidates':[{k:v for k,v in c.items() if k!='model'} for c in candidates],
      'state_selection':state_report,
      'feedback_holdout':{'old':old_holdout,'new':new_holdout,
        'old_correct':sum(v['positive']==v['predicted'] for v in old_holdout),
        'new_correct':sum(v['positive']==v['predicted'] for v in new_holdout),'count':len(holdout),
        'state':state_evaluation(state_model,state_test,columns)},
      'reference_regression':{'snap_events':regression,'state':state_evaluation(state_model,[r for r in states if r['part']=='test'],columns)},
      'effort_updated':False,
      'limitations':['Intent cues and delayed marks are weak clip labels, not verified snap timestamps.',
        'Overlapping prospective windows were truncated before the next cue; two actual sequence gaps reset feature filtering.',
        'Final feedback windows were held out of fitting/selection, but share wearing sessions and include previously reviewed older feedback.',
        'Reference clips are known regression data, not a new independent test. No new general accuracy claim.',
        'Newest capture has no video: its prospective cues are reported intent, not independently verified actions.',
        'Effort unchanged: feedback did not label tension levels. Quest remains required for spatial shield pose and committed forward throws.']}
    new['report']=report
    joblib.dump(new,output/'model.joblib');write_json(output/'training-report.json',report)
    joblib.dump({'model':state_model,'columns':columns},output/'hand-state-model.joblib')
    joblib.dump({'model':new['snap_model'],'threshold':new['snap_threshold']},output/'snap-model.joblib')
    joblib.dump(new['effort_artifact'],output/'effort-model.joblib')
    return report
