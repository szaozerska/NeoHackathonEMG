"""V3 baselines from participant-confirmed clips, without invented snap timestamps.

Hand state is supervised on trimmed steady holds. Snap uses multiple-instance
learning: each positive clip contains a snap somewhere, not a snap at every frame.
Only clip-level snap accuracy is measurable with these labels.
"""
from collections import Counter
from pathlib import Path
import csv

import joblib
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logsumexp
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from .common import write_json
from .effort import effort_dataset, sensor_times, _hash, _ordered_prob, evaluate_effort, is_shield
from .shield_training import PROTOCOL
from .signals import SignalWindows

STATE_LEVELS = ('open', 'fist', 'none')
SNAP_COLUMNS = {
    'temporal_rms': [quarter*40+c for quarter in range(4) for c in range(8)],
    'temporal_amplitude': [quarter*40+c for quarter in range(4) for c in range(24)],
}


def trial_weights(rows, key='hand_state'):
    trials = {r['trial']:r[key] for r in rows}
    counts = Counter(r['trial'] for r in rows)
    classes = Counter(trials.values())
    weights = np.array([1/(counts[r['trial']]*classes[r[key]]) for r in rows])
    return weights/weights.sum()*len(weights)


def binary_metrics(truth, predicted):
    truth, predicted = np.asarray(truth, dtype=bool), np.asarray(predicted, dtype=bool)
    tn, fp, fn, tp = confusion_matrix(truth, predicted, labels=[False, True]).ravel()
    return {'count':len(truth), 'correct':int((truth==predicted).sum()),
            'accuracy':float(accuracy_score(truth, predicted)),
            'balanced_accuracy':float(balanced_accuracy_score(truth, predicted)),
            'tp':int(tp), 'fp':int(fp), 'fn':int(fn), 'tn':int(tn),
            'precision':float(tp/(tp+fp)) if tp+fp else None,
            'recall':float(tp/(tp+fn)) if tp+fn else None,
            'f1':float(2*tp/(2*tp+fp+fn)) if 2*tp+fp+fn else 0.}


def state_evaluation(model, rows, columns):
    scores = model.predict_proba(np.array([r['x'][:columns] for r in rows]))
    trials = []
    for trial in dict.fromkeys(r['trial'] for r in rows):
        ix = [i for i,r in enumerate(rows) if r['trial']==trial]
        p = scores[ix].mean(axis=0)
        trials.append({'trial':trial, 'actual':rows[ix[0]]['hand_state'],
                       'predicted':str(model.classes_[p.argmax()]),
                       'probabilities':dict(zip(model.classes_, p.tolist())), 'windows':len(ix)})
    truth, predicted = [r['actual'] for r in trials], [r['predicted'] for r in trials]
    return {'trial_count':len(trials), 'correct_trials':sum(a==b for a,b in zip(truth,predicted)),
            'trial_accuracy':float(accuracy_score(truth,predicted)),
            'trial_macro_f1':float(f1_score(truth,predicted,labels=STATE_LEVELS,average='macro',zero_division=0)),
            'label_order':STATE_LEVELS, 'confusion_matrix':confusion_matrix(truth,predicted,labels=STATE_LEVELS).tolist(),
            'window_accuracy':float(accuracy_score([r['hand_state'] for r in rows], model.classes_[scores.argmax(axis=1)])),
            'sword_fist':binary_metrics([a=='fist' for a in truth],[a=='fist' for a in predicted]),
            'shield_open_hand':binary_metrics([a=='open' for a in truth],[a=='open' for a in predicted]),
            'trials':trials}


class WeakSnapModel:
    """Smooth-max multiple-instance logistic model, trained on whole-clip labels.

    A window score is an unverified localization score, NOT a calibrated
    probability that an individual snap occurred at that instant.
    """
    def __init__(self, columns, regularization=.03, temperature=.5):
        self.columns = list(columns)
        self.regularization, self.temperature = regularization, temperature

    def transform(self, x):
        return self.scaler.transform(np.log1p(np.asarray(x)[:,self.columns]))

    def fit(self, bags):
        y = np.array([b['positive'] for b in bags], dtype=float)
        if set(y)!={0.,1.}:
            raise ValueError('Snap learning requires positive and non-snap training clips')
        x = np.concatenate([b['x'] for b in bags])
        weight = np.concatenate([np.full(len(b['x']),1/len(b['x'])) for b in bags])
        self.scaler = StandardScaler().fit(np.log1p(x[:,self.columns]), sample_weight=weight)
        xs = [self.transform(b['x']) for b in bags]
        bag_weights = np.array([.5/(sum(y==value)) for value in y])
        def objective(theta):
            w,bias = theta[:-1],theta[-1]
            loss = self.regularization*np.dot(w,w)/2
            grad = np.r_[self.regularization*w,0.]
            for matrix,target,weight_ in zip(xs,y,bag_weights):
                z = (matrix@w+bias)/self.temperature
                normalizer = logsumexp(z)
                pooled = self.temperature*(normalizer-np.log(len(matrix)))
                loss += weight_*(np.logaddexp(0,pooled)-target*pooled)
                derivative = weight_*(expit(pooled)-target)
                grad[:-1] += derivative*(np.exp(z-normalizer)@matrix)
                grad[-1] += derivative
            return float(loss),grad
        result = minimize(objective, np.zeros(len(self.columns)+1), jac=True,
                          method='L-BFGS-B', options={'maxiter':500, 'ftol':1e-10})
        if not result.success:
            raise ValueError('Snap optimization failed: '+str(result.message))
        self.coef_,self.intercept_ = result.x[:-1],float(result.x[-1])
        self.fit_diagnostics = {'converged':True, 'iterations':int(result.nit), 'objective':float(result.fun),
                                'positive_training_clips':int(y.sum()), 'negative_training_clips':int((1-y).sum())}
        return self

    def logits(self, x):
        return self.transform(x)@self.coef_+self.intercept_

    def clip_score(self, x):
        z = self.logits(x)/self.temperature
        return float(expit(self.temperature*(logsumexp(z)-np.log(len(z)))))

    def window_scores(self, x):
        return expit(self.logits(x))


def snap_bags(records):
    bags = []
    rows = [r for r in records if r['kind']=='snap']
    for trial in dict.fromkeys(r['trial'] for r in rows):
        block = [r for r in rows if r['trial']==trial]
        first = block[0]
        bags.append({'trial':trial, 'round':first['round'], 'condition':first['condition'],
                     'positive':first['condition']=='snap', 'x':np.array([r['x'] for r in block]),
                     'times':np.array([r['end'] for r in block])})
    return bags


def snap_evaluation(model, bags, threshold):
    trials = [{'trial':b['trial'], 'actual_contains_snap':bool(b['positive']),
               'score':model.clip_score(b['x'])} for b in bags]
    for trial in trials:
        trial['predicted_contains_snap'] = trial['score']>=threshold
    metrics = binary_metrics([r['actual_contains_snap'] for r in trials],
                             [r['predicted_contains_snap'] for r in trials])
    return {**metrics, 'threshold':float(threshold), 'positive_clips':sum(b['positive'] for b in bags),
            'negative_clips':sum(not b['positive'] for b in bags), 'unit':'whole trimmed clip, not individual snap',
            'event_precision':None, 'event_recall':None, 'event_timing_accuracy':None, 'trials':trials}


def candidate_indices(scores, times, threshold):
    """Same causal threshold/rearm/refractory rule used in GesturePredictor."""
    rearmed,last=True,-float('inf')
    indices=[]
    for i,(score,t) in enumerate(zip(scores,times)):
        if score<.4:rearmed=True
        if score>=threshold and rearmed and t-last>=.35:
            indices.append(i);last,rearmed=t,False
    return indices


def candidate_evaluation(model, bags, threshold):
    """Can measure false events in reported non-snap clips, not snap-event recall."""
    trials=[];negative_events=0;negative_seconds=0.
    for bag in bags:
        candidates=candidate_indices(model.window_scores(bag['x']),bag['times'],threshold)
        trials.append({'trial':bag['trial'],'actual_contains_snap':bool(bag['positive']),
                       'predicted_contains_snap':bool(candidates),'candidate_count':len(candidates)})
        if not bag['positive']:
            negative_events+=len(candidates)
            negative_seconds+=float(bag['times'][-1]-bag['times'][0])
    return {**binary_metrics([r['actual_contains_snap'] for r in trials],
                             [r['predicted_contains_snap'] for r in trials]),
            'unit':'whether at least one causal candidate occurs in the trimmed clip',
            'threshold':threshold,'threshold_selected_for':'whole-clip score, not event accuracy',
            'negative_candidate_events':negative_events,'negative_observation_seconds':negative_seconds,
            'negative_candidates_per_minute':negative_events/(negative_seconds/60) if negative_seconds else None,
            'snap_event_precision':None,'snap_event_recall':None,'snap_event_latency':None,
            'trials':trials}


def fit_baselines(records):
    """Train on round 1, select on round 2, score round 3 once per task."""
    states = {n:[r for r in records if r['kind']=='state' and r['hand_state'] in STATE_LEVELS and r['round']==i]
              for n,i in (('train',1),('validation',2),('test',3))}
    bags = snap_bags(records)
    snaps = {n:[b for b in bags if b['round']==i] for n,i in (('train',1),('validation',2),('test',3))}
    for name in states:
        if Counter({r['trial']:r['hand_state'] for r in states[name]}.values())!=Counter({'open':9,'fist':3,'none':1}):
            raise ValueError(name+' requires all thirteen confirmed steady-state trials')
        if len(snaps[name])!=16 or sum(b['positive'] for b in snaps[name])!=1:
            raise ValueError(name+' requires sixteen complete clips, including one snap clip')
    state_models, state_validation = {},{}
    for name,columns in (('log_rms',8),('log_amplitude',24)):
        training=states['train']
        model=make_pipeline(FunctionTransformer(np.log1p),StandardScaler(),
                            LogisticRegression(C=.1,max_iter=2000,random_state=7))
        model.fit(np.array([r['x'][:columns] for r in training]), [r['hand_state'] for r in training],
                  logisticregression__sample_weight=trial_weights(training))
        state_models[name]=(model,columns)
        state_validation[name]=state_evaluation(model,states['validation'],columns)
    selected_state=max(state_models,key=lambda n:state_validation[n]['trial_macro_f1'])
    state_model,columns=state_models[selected_state]
    # No guessed snap timestamps and no test-derived pseudo labels.
    snap_models,snap_validation={},{}
    for name,indices in SNAP_COLUMNS.items():
        model=WeakSnapModel(indices).fit(snaps['train'])
        choices=[snap_evaluation(model,snaps['validation'],t) for t in (.35,.5,.65,.8,.9,.95)]
        chosen=max(choices,key=lambda v:(v['balanced_accuracy'],v['f1'],-v['fp'],v['threshold']))
        snap_models[name]=model
        snap_validation[name]={'selected':chosen,'threshold_choices':choices,'fit':model.fit_diagnostics}
    selected_snap=max(snap_models,key=lambda n:(snap_validation[n]['selected']['balanced_accuracy'],
                                               snap_validation[n]['selected']['f1'],
                                               -snap_validation[n]['selected']['fp']))
    snap_model=snap_models[selected_snap]
    threshold=snap_validation[selected_snap]['selected']['threshold']
    report={'hand_state':{'selected':selected_state,'feature_columns':columns,'validation_candidates':state_validation,
                          'test':state_evaluation(state_model,states['test'],columns)},
            'fireball_snap':{'selected':selected_snap,'supervision':'multiple-instance learning from clip-level participant reports',
                             'validation_candidates':snap_validation,
                             'test':snap_evaluation(snap_model,snaps['test'],threshold),
                             'majority_negative_clip_baseline_accuracy':15/16,
                             'causal_candidate_test':candidate_evaluation(snap_model,snaps['test'],threshold)},
            'split':{name:{'round':i,'steady_trials':sorted({r['trial'] for r in states[name]}),
                           'snap_clips':sorted(b['trial'] for b in snaps[name])}
                     for name,i in (('train',1),('validation',2),('test',3))}}
    artifacts={'state_model':state_model,'state_columns':columns, 'state_threshold':.55,
               'snap_model':snap_model,'snap_threshold':threshold}
    return artifacts,report,bags


def train_gestures(directory, output, effort_path):
    output=Path(output)
    if output.exists():raise ValueError('Output exists; choose a new artifact version')
    records,quality,manifest,config=effort_dataset(directory,include_snap=True)
    effort_path=Path(effort_path)
    effort=joblib.load(effort_path)
    if effort.get('protocol')!=PROTOCOL or effort.get('task')!='shield_relative_emg_effort':
        raise ValueError('Expected trusted v3 shield effort artifact')
    if effort['signal']!=config:
        raise ValueError('Effort and hand/snap models must share the same causal signal configuration')
    source=effort['report']['source']
    if any(source.get(k)!=manifest[k] for k in ('streams_sha256','labels_sha256','metadata_sha256','subject','side')):
        raise ValueError('Effort artifact belongs to a different recording or changed labels')
    artifacts,report,bags=fit_baselines(records)
    report.update({'schema':1,'task':'v3_gesture_baselines','protocol':PROTOCOL,'subject':manifest['subject'],
                   'side':manifest['side'],'source':manifest,'signal':config,'quality':quality,
                   'shield_effort':{'artifact_sha256':_hash(effort_path),'reused_frozen_artifact':True,
                                    'test':effort['report']['test']},
                   'limitations':[
                       'One band-wearing session; these are trial/round-held-out results, not independent-session accuracy.',
                       'Shield and sword state scores use steady holds. Closing/opening transition latency and natural continuous play are unmeasured.',
                       'Shield open-hand detection does not verify fingers up, palm facing, arm extension or opponent direction; Quest is required.',
                       'Shield effort is relative reported tension, not measured force or a validated proportional protection curve.',
                       'Only one positive snap clip in training, one in validation and one in testing. The clips contain multiple snaps with unknown individual times/counts.',
                       'Fireball accuracy is clip-level only. Inferred event candidates are unverified; event precision, recall and latency are unknown.',
                       'No Quest throw model, tracking quality evaluation or headset gameplay accuracy is claimed.',
                       'Test results must not be used to tune or select another model while calling this same round an untouched test.'],
                   'label_provenance':'Confirmed participant reports with 0.75-second edge trims. Original annotations are unchanged.',
                   'versions':effort['report']['versions']})
    bundle={'schema':1,'task':'v3_gesture_bundle','protocol':PROTOCOL,'signal':config,
            **artifacts,'effort_artifact':effort,'report':report}
    output.mkdir(parents=True,exist_ok=False)
    joblib.dump(bundle,output/'model.joblib')
    joblib.dump({'protocol':PROTOCOL,'model':artifacts['state_model'],'columns':artifacts['state_columns'],
                 'task':'v3_hand_state','report':report['hand_state']},output/'hand-state-model.joblib')
    joblib.dump({'protocol':PROTOCOL,'model':artifacts['snap_model'],'threshold':artifacts['snap_threshold'],
                 'task':'weak_clip_snap','report':report['fireball_snap']},output/'snap-model.joblib')
    write_json(output/'training-report.json',report)
    write_json(output/'label-manifest.json',{'source':manifest,'split':report['split'],
        'snap_event_times_verified':False,'original_annotations_modified':False})
    candidates=[]
    for bag in bags:
        scores=artifacts['snap_model'].window_scores(bag['x'])
        peaks=candidate_indices(scores,bag['times'],artifacts['snap_threshold'])
        for i in peaks:
            candidates.append({'trial':bag['trial'],'round':bag['round'],'condition':bag['condition'],
                'approx_recorder_seconds':float(bag['times'][i]), 'window_score':float(scores[i]),
                'verified':False,'source':'model_candidate_only_not_ground_truth'})
    write_json(output/'snap-candidates-for-review.json',candidates)
    for name,rows in (('hand-state-test',report['hand_state']['test']['trials']),
                      ('snap-clip-test',report['fireball_snap']['test']['trials'])):
        simple=[{k:v for k,v in r.items() if not isinstance(v,dict)} for r in rows]
        with (output/(name+'.csv')).open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(simple[0]));writer.writeheader();writer.writerows(simple)
    h=report['hand_state']['test'];f=report['fireball_snap']['test'];e=report['shield_effort']['test']
    c=report['fireball_snap']['causal_candidate_test']
    lines=['# V3 gesture baselines','',
        'All fits use round 1; round 2 selects candidates/thresholds; round 3 is evaluated once. The existing shield effort artifact was reused unchanged.','',
        '| Task | Round-3 result | Meaning |','|---|---|---|',
        f"| Sword fist vs other steady holds | {h['sword_fist']['correct']}/{h['sword_fist']['count']} ({h['sword_fist']['accuracy']:.1%}) | {h['sword_fist']['tp']}/3 fists detected; {h['sword_fist']['fp']} false positives on ten other holds |",
        f"| Shield open hand vs other steady holds | {h['shield_open_hand']['correct']}/{h['shield_open_hand']['count']} ({h['shield_open_hand']['accuracy']:.1%}) | EMG hand shape only; does not verify shield pose |",
        f"| Shield light/medium/firm effort | {e['correct_trials']}/{e['trial_count']} ({e['trial_accuracy']:.1%}) | Participant-reported effort, not physical force |",
        f"| Fireball snap-containing clip vs non-snap clips | {f['correct']}/{f['count']} ({f['accuracy']:.1%}) | {f['tp']}/1 positive clip detected; {f['fp']}/15 negative clips flagged; balanced accuracy {f['balanced_accuracy']:.1%} |",
        f"| Fireball causal candidate on/off per clip | {c['correct']}/{c['count']} ({c['accuracy']:.1%}) | {c['tp']}/1 positive clip triggered; {c['fp']}/15 negative clips also triggered |",
        '| Individual snap-event accuracy | Unknown | No verified event times or exact counts |','',
        f"Three-class hand-state accuracy: {h['correct_trials']}/{h['trial_count']} ({h['trial_accuracy']:.1%}).",'',
        f"Causal snap candidates: {c['negative_candidate_events']} false activations across {c['negative_observation_seconds']:.1f} seconds of trimmed reported non-snap clips ({c['negative_candidates_per_minute']:.2f}/minute). This is not a continuous gameplay false-activation rate.", '',
        '## Limits','']+['- '+v for v in report['limitations']]
    lines+=['','## Next data to collect','',
        '- Independent wearing sessions for all gestures, including negative activities and closing/opening transitions.',
        '- Timestamped isolated middle-thumb snaps and matched non-snap movements; candidate times in this directory are review suggestions, not truth.',
        '- Simultaneous Quest/band sessions to test moving shield pose, orientation, hold/release and later fireball throws.']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return report


def evaluate_gestures(directories, artifact, output, allow_development=False):
    """Evaluate a frozen bundle on complete v3 sessions without refitting."""
    output=Path(output)
    if output.exists():raise ValueError('Evaluation output exists; choose a new path')
    source=artifact['report']['source'];reports=[]
    used_sources=artifact['report'].get('sources',[source])
    for directory in directories:
        records,quality,manifest,_=effort_dataset(directory,include_snap=True)
        if any(manifest[k]!=source[k] for k in ('subject','side')):
            raise ValueError('Evaluation subject/side differs from trained model')
        same=any(manifest['streams_sha256']==s['streams_sha256'] or manifest['directory']==s['directory']
                 for s in used_sources)
        if same and not allow_development:
            raise ValueError('This session was used for fitting and selection. Use a new session or explicitly --development')
        states=[r for r in records if r['kind']=='state' and r['hand_state'] in STATE_LEVELS]
        effort_rows=[r for r in states if is_shield(r)]
        if set(r['hand_state'] for r in states)!=set(STATE_LEVELS):
            raise ValueError('Evaluation needs confirmed open, fist and relaxed trials')
        bags=snap_bags(records)
        if not any(b['positive'] for b in bags) or all(b['positive'] for b in bags):
            raise ValueError('Evaluation needs confirmed snap and non-snap clips')
        effort=artifact['effort_artifact']
        reports.append({'source':manifest,'development_evaluation':bool(same),'quality':quality,
            'hand_state':state_evaluation(artifact['state_model'],states,artifact['state_columns']),
            'shield_effort':evaluate_effort(effort['model'],effort_rows,effort['feature_columns']),
            'snap_clips':snap_evaluation(artifact['snap_model'],bags,artifact['snap_threshold']),
            'snap_causal_candidates':candidate_evaluation(artifact['snap_model'],bags,artifact['snap_threshold'])})
    report={'protocol':PROTOCOL,'model_source':source,'sessions':reports,
            'limitations':artifact['report']['limitations'],
            'note':'Frozen parameters; no selection or refit. Event timing and Quest performance remain unmeasured.'}
    output.mkdir(parents=True,exist_ok=False)
    write_json(output/'evaluation.json',report)
    return report


class GesturePredictor:
    """One causal sensor-time filter for all three EMG components.

    Weak snap detections are emitted as candidates unless explicitly enabled.
    Their confidence is a model score, not established event probability.
    """
    def __init__(self, artifact, experimental_snaps=False, diagnostics=False):
        if artifact.get('task')!='v3_gesture_bundle' or artifact.get('protocol')!=PROTOCOL:
            raise ValueError('Expected v3 gesture bundle')
        self.artifact=artifact
        self.diagnostics=diagnostics
        self.windows=SignalWindows(artifact['signal'])
        self.experimental_snaps=experimental_snaps
        self.reference_reviewed_snaps=artifact.get('snap_event_supervision')=='reference_reviewed'
        self.last_seq=None
        self.label,self.candidate,self.votes='none','none',0
        self.last_snap=-float('inf');self.snap_rearmed=True;self.snap_id=0

    def feed(self,row):
        if row.get('kind')!='emg':return []
        if self.last_seq is not None and row['source_seq']!=self.last_seq+1:
            self.windows.reset()
            self.label,self.candidate,self.votes='none','none',0
            self.snap_rearmed=False
            self.last_snap=-float('inf')
        self.last_seq=row['source_seq']
        times=sensor_times(row,self.artifact['signal']['sample_rate'])
        offset=row.get('received',row.get('t',float(times[-1])))-times[-1]
        output=[]
        for feature in self.windows.feed(row['samples'],times):
            x=np.array([feature['x']]);source_t=feature['t'];t=source_t+offset
            if feature['kind']=='state':
                model=self.artifact['state_model']
                p=model.predict_proba(x[:,:self.artifact['state_columns']])[0]
                best=int(p.argmax());score=float(p[best])
                label=str(model.classes_[best]) if score>=self.artifact['state_threshold'] else 'none'
                self.votes=self.votes+1 if label==self.candidate else 1;self.candidate=label
                needed=1 if label=='open' and self.label=='fist' else 2
                if self.votes>=needed:self.label=label
                output.append({'kind':'state','t':float(t),'source_t':source_t,'label':self.label,'confidence':score,
                               'probabilities':dict(zip(map(str,model.classes_),p.tolist()))})
                effort=self.artifact['effort_artifact']
                ep=_ordered_prob(effort['model'],x[:,:effort['feature_columns']])[0]
                output.append({'kind':'effort','t':float(t),'source_t':source_t,
                               'effort_index':float(ep@np.array([0.,.5,1.])),
                               'probabilities':dict(zip(effort['levels'],ep.tolist()))})
            else:
                score=float(self.artifact['snap_model'].window_scores(x)[0])
                if self.diagnostics:
                    output.append({'kind':'snap_score','t':float(t),'source_t':source_t,
                                   'window_start':feature['start'],'confidence':score,
                                   'threshold':self.artifact['snap_threshold'],
                                   'rearmed':self.snap_rearmed,'refractory_elapsed':bool(source_t-self.last_snap>=.35)})
                if score<.4:self.snap_rearmed=True
                if score>=self.artifact['snap_threshold'] and self.snap_rearmed and source_t-self.last_snap>=.35:
                    self.last_snap,self.snap_rearmed=source_t,False;self.snap_id+=1
                    output.append({'kind':'snap' if self.experimental_snaps or self.reference_reviewed_snaps else 'snap_candidate',
                                   't':float(t),'source_t':source_t,'event_id':str(self.snap_id),
                                   'confidence':score,'verified_event_model':self.reference_reviewed_snaps})
        return output
