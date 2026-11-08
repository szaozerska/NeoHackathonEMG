#!/usr/bin/env python3
"""Development-only staged calibration for the reviewed delayed-mark recording.
Does not modify the active model; requires trusted local caches and a new output.
"""
import copy,json,joblib,numpy as np
from pathlib import Path
from scipy.optimize import minimize
from scipy.special import expit,logsumexp
from spelltrain.retraining import prepare_records,supervised_weights,score_snap_events,fit_state
from spelltrain.gestures import state_evaluation
from spelltrain.common import write_json
import argparse
from spelltrain.effort import _hash
parser=argparse.ArgumentParser(description='Stage an inactive weak-feedback calibration candidate')
parser.add_argument('--model',default='artifacts/player-a/gestures-v4/model.joblib')
parser.add_argument('--feedback-features',default='artifacts/player-a/live-correction-review-01/features.joblib')
parser.add_argument('--reference-features',default='artifacts/player-a/reference-review-v4/features.joblib')
parser.add_argument('--reference-labels',default='artifacts/player-a/reference-review-v4/reviewed-labels.json')
parser.add_argument('--output',required=True)
parser.add_argument('--confirm-delayed-fireball-marks',action='store_true')
args=parser.parse_args()
if not args.confirm_delayed_fireball_marks:
 parser.error('This retrospective analysis requires confirmed delayed Fireball marks; do not apply it to prospective cues.')
old=joblib.load(args.model)
live=joblib.load(args.feedback_features)
cache=joblib.load(args.reference_features)
review=json.load(open(args.reference_labels))
state,effort,snap=prepare_records(cache,review)
train_s=[r for r in state if r['part']=='train'];val_s=[r for r in state if r['part']=='validation']
train_p=[r for r in snap if r['part']=='train' and r['snap_label'] is not None];val_p=[r for r in snap if r['part']=='validation']
marks=live['marks'];features=live['features'];bags=[];state_new=[];manifest=[]
for i,m in enumerate(marks):
 part='calibration' if i<=6 else 'held_out_feedback'
 if m['gesture']=='Fireball':
  # User explicitly confirmed several-second delayed marking; use clip supervision only.
  lo=(marks[i-1]['reported_at']+.1) if i else 0.;hi=m['reported_at']-.1
 else:lo=m['reported_at']-1.5;hi=m['reported_at']-.25
 rows=[r for r in features if r['kind']=='snap' and lo<=r['start'] and r['t']<=hi]
 bags.append({'trial':m['id'],'part':part,'positive':m['gesture']=='Fireball','gesture':m['gesture'],
              'x':np.array([r['x'] for r in rows]),'start':lo,'end':hi})
 manifest.append({'marker_id':m['id'],'part':part,'gesture':m['gesture'],'start':lo,'end':hi,
                  'supervision':'contains snap somewhere in interval' if m['gesture']=='Fireball' else 'participant-reported posture; conservative tail of review window',
                  'verified_event_times':False})
 if m['gesture']!='Fireball':
  for r in features:
   if r['kind']=='state' and lo<=r['start'] and r['t']<=hi:
    state_new.append({'x':r['x'],'trial':'live:'+m['id'],'hand_state':{'Shield':'open','Sword':'fist','Nothing':'none'}[m['gesture']],
                      'part':part,'condition':'participant-report','start':r['start'],'end':r['t']})
training_bags=[b for b in bags if b['part']=='calibration'];held_bags=[b for b in bags if b['part']=='held_out_feedback']
# State model: retain all original fitting/validation examples; add only calibration reports.
state_model,cols,state_report=fit_state(train_s+[r for r in state_new if r['part']=='calibration'],val_s)
# Snap update: freeze feature scaling; regularize new coefficients toward the original model.
original=old['snap_model'];classifier=original.model.named_steps['logisticregression'];theta0=np.r_[classifier.coef_[0],classifier.intercept_[0]]
transform=lambda x:original.model[:-1].transform(x[:,original.columns])
x=transform(np.array([r['x'] for r in train_p]));y=np.array([r['snap_label']=='snap' for r in train_p],float)
w=supervised_weights(train_p,'snap_label');w=w/w.sum()
xb=[transform(b['x']) for b in training_bags];yb=np.array([b['positive'] for b in training_bags],float)
wb=np.array([.5/sum(yb==v) for v in yb]);temperature=.3
candidates=[]
for penalty in (.03,.1,.3):
 def objective(theta):
  logits=x@theta[:-1]+theta[-1];delta=theta-theta0
  loss=float(np.sum(w*(np.logaddexp(0,logits)-y*logits))+.5*penalty*np.dot(delta,delta))
  residual=w*(expit(logits)-y);grad=np.r_[x.T@residual,residual.sum()]+penalty*delta
  for matrix,target,weight in zip(xb,yb,wb):
   z=(matrix@theta[:-1]+theta[-1])/temperature;n=logsumexp(z)
   pooled=temperature*(n-np.log(len(matrix)))
   loss+=weight*(np.logaddexp(0,pooled)-target*pooled)
   derivative=weight*(expit(pooled)-target)
   grad[:-1]+=derivative*(np.exp(z-n)@matrix);grad[-1]+=derivative
  return loss,grad
 fit=minimize(objective,theta0,jac=True,method='L-BFGS-B',options={'maxiter':300,'ftol':1e-10})
 if not fit.success:raise RuntimeError(fit.message)
 model=copy.deepcopy(original);clf=model.model.named_steps['logisticregression'];clf.coef_=fit.x[:-1][None,:];clf.intercept_=fit.x[-1:]
 scores=np.array([max(model.window_scores(b['x'])) for b in training_bags]);options=[]
 for threshold in (.65,.75,.85,.9,.95,.98,.995,.999):
  val=score_snap_events(model,val_p,threshold)
  pred=scores>=threshold;correct=float(np.mean(pred==yb))
  logits=np.log(np.clip(scores,1e-9,1-1e-9)/(1-np.clip(scores,1e-9,1-1e-9)))
  t=np.log(threshold/(1-threshold));margin=float(min(min(logits[yb==1]-t),min(t-logits[yb==0])))
  options.append({'threshold':threshold,'validation_event_f1':val['f1'],'validation_fp':val['fp'],
                  'calibration_clip_accuracy':correct,'calibration_margin':margin})
 chosen=max(options,key=lambda o:(o['validation_event_f1'],o['calibration_clip_accuracy'],o['calibration_margin']))
 candidates.append({'penalty':penalty,'model':model,'selected':chosen,'parameter_change':float(np.linalg.norm(fit.x-theta0)),
                     'thresholds':options,'converged':True})
selected=max(candidates,key=lambda c:(c['selected']['validation_event_f1'],c['selected']['calibration_clip_accuracy'],
                                      -c['parameter_change']))
threshold=selected['selected']['threshold'];new=copy.deepcopy(old)
new['state_model']=state_model;new['state_columns']=cols;new['snap_model']=selected['model'];new['snap_threshold']=threshold
out=Path(args.output);out.mkdir(exist_ok=False)
joblib.dump(new,out/'frozen-before-feedback-validation.joblib')
# First evaluate the held-out final four reports only after fitting and selection.
score_bags=lambda model,th:[{'marker_id':b['trial'],'actual_contains_snap':b['positive'],
      'max_score':float(max(model.window_scores(b['x']))),'predicted_contains_snap':bool(max(model.window_scores(b['x']))>=th)} for b in held_bags]
report={'kind':'weak_feedback_calibration_candidate','status':'candidate_not_activated','source_capture':live['capture_path'],
 'timing_clarification':'User confirmed waiting several seconds before Fireball marks. Do not treat click times as snap events.',
 'supervision_manifest':manifest,'state_fit':state_report,
 'snap_selection':[{k:v for k,v in c.items() if k!='model'} for c in candidates],
 'selected_penalty':selected['penalty'],'selected_threshold':threshold,
 'feedback_holdout':{'snap_old':score_bags(original,old['snap_threshold']),
   'snap_candidate':score_bags(new['snap_model'],threshold),
   'state_old':state_evaluation(old['state_model'],[r for r in state_new if r['part']=='held_out_feedback'],old['state_columns']),
   'state_candidate':state_evaluation(state_model,[r for r in state_new if r['part']=='held_out_feedback'],cols)},
 'reference_regression':{'snap':score_snap_events(new['snap_model'],[r for r in snap if r['part']=='test'],threshold),
   'state':state_evaluation(state_model,[r for r in state if r['part']=='test'],cols)},
 'limitations':['Participant marks are weak reports, not verified frame labels or precise snap times.',
  'One minute from one wearing session; final four reports are an internal feedback holdout, not independent-session testing.',
  'Old reference test data were previously inspected; this is a regression check, not a new unbiased accuracy estimate.',
  'Effort model is unchanged because this recording contains no reported effort levels.']}
report.update(promotion_decision='not_promoted',model_version='feedback-candidate',subject='player-a',side='right',
 previous_model_sha256=_hash(args.model),
 frozen_before_test_sha256=_hash(out/'frozen-before-feedback-validation.joblib'),
 source_capture_streams_sha256=_hash(Path(live['capture_path'])/'streams.jsonl'),
 source_corrections_sha256=_hash(Path(live['capture_path'])/'corrections.json'))
new['report']={'task':'weak_feedback_calibration_candidate','model_version':'feedback-candidate',
 'subject':'player-a','side':'right','frozen_before_test_sha256':report['frozen_before_test_sha256'],
 'promotion_decision':'not_promoted','review':report}
joblib.dump(new,out/'model.joblib');write_json(out/'review-report.json',report)
print(json.dumps({'selected':selected['selected'],'penalty':selected['penalty'],
 'snap_old_holdout':report['feedback_holdout']['snap_old'],'snap_new_holdout':report['feedback_holdout']['snap_candidate'],
 'state_old':report['feedback_holdout']['state_old']['correct_trials'],'state_new':report['feedback_holdout']['state_candidate']['correct_trials'],
 'regression_snap':{k:report['reference_regression']['snap'][k] for k in ('tp','fp','fn')},
 'regression_state':report['reference_regression']['state']['correct_trials']},indent=2))
