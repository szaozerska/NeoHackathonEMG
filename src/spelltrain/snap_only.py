"""Standalone snap-vs-background EMG training and causal inference.

No hand-state model, camera, microphone or equipment rule enters inference.
"""
from pathlib import Path
import joblib
import numpy as np
from sklearn.base import BaseEstimator,TransformerMixin
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer,StandardScaler
from .signals import SignalWindows
from .effort import sensor_times,_hash
from .common import read_json,write_json
from .retraining import prepare_records,supervised_weights,SupervisedSnapModel,score_snap_events
from .camera_retraining import reviewed_records
from .gestures import SNAP_COLUMNS


class RelativeBurstFeatures(TransformerMixin,BaseEstimator):
    """Preserve burst order/channel shape while reducing absolute amplitude dependence."""
    def __init__(self,include_energy=False):self.include_energy=include_energy
    def fit(self,x,y=None):return self
    def transform(self,x):
        x=np.maximum(np.asarray(x,float),0).reshape(-1,4,8)
        level=np.maximum(x.mean(axis=(1,2),keepdims=True),1e-6)
        relative=np.log1p(x/level).reshape(len(x),-1)
        if self.include_energy:return np.column_stack([relative,np.log1p(level[:,0,0])])
        return relative


class SnapOnlyPredictor:
    def __init__(self,artifact):
        if artifact.get('task')!='snap_only_emg':raise ValueError('Expected standalone snap EMG artifact')
        self.artifact=artifact;self.windows=SignalWindows(artifact['signal']);self.seq=None
        self.rearmed=True;self.last=-float('inf');self.event_id=0
    def feed(self,packet):
        seq=packet['source_seq']
        if self.seq is not None and seq!=self.seq+1:
            self.windows.reset();self.rearmed=False;self.last=-float('inf')
        self.seq=seq;out=[]
        for feature in self.windows.feed(packet['samples'],sensor_times(packet,self.artifact['signal']['sample_rate'])):
            if feature['kind']!='snap':continue
            score=float(self.artifact['model'].window_scores(np.array([feature['x']]))[0]);t=feature['t']
            out.append({'kind':'snap_score','source_t':t,'score':score,'threshold':self.artifact['threshold']})
            if score<.4:self.rearmed=True
            if score>=self.artifact['threshold'] and self.rearmed and t-self.last>=.35:
                self.event_id+=1;self.rearmed=False;self.last=t
                out.append({'kind':'snap','event_id':str(self.event_id),'source_t':t,'score':score})
        return out


def train_snap_only(base_path,review_path,output):
    output=Path(output)
    if output.exists():raise ValueError('Output exists; choose a new candidate')
    review_path=Path(review_path);review=read_json(review_path);source=Path(review['source_directory'])
    for name,digest in review['source_hashes'].items():
        if _hash(source/name)!=digest:raise ValueError('Reviewed source changed: '+name)
    from .feedback_update import capture_features
    capture=capture_features(source);_,live=reviewed_records(capture,review)
    references=review_path.parent.parent/'reference-review-v4'
    cache=joblib.load(references/'features.joblib');_,_,old=prepare_records(cache,read_json(references/'reviewed-labels.json'))
    base=joblib.load(base_path);parts=lambda rows,p:[r for r in rows if r['part']==p]
    train=[r for r in parts(old,'train')+parts(live,'train') if r['snap_label'] is not None]
    x=np.array([r['x'] for r in train]);y=[r['snap_label'] for r in train];weight=supervised_weights(train,'snap_label')
    choices=[]
    for family in ('log_rms','relative_burst','relative_burst_with_energy'):
        columns=SNAP_COLUMNS['temporal_rms']
        for c in (.03,.1,.3,1.):
            transform=FunctionTransformer(np.log1p) if family=='log_rms' else RelativeBurstFeatures(family.endswith('with_energy'))
            model=make_pipeline(transform,StandardScaler(),LogisticRegression(C=c,max_iter=2000,random_state=7))
            model.fit(x[:,columns],y,logisticregression__sample_weight=weight)
            wrapper=SupervisedSnapModel(model,columns)
            for threshold in (.55,.65,.75,.85,.9,.95,.98,.995,.999):
                a=score_snap_events(wrapper,parts(old,'validation'),threshold)
                b=score_snap_events(wrapper,parts(live,'validation'),threshold)
                choices.append({'family':family,'C':c,'threshold':threshold,'model':wrapper,
                    'reference_validation':a,'live_validation':b,'selection':(a['f1']+b['f1'])/2})
    selected=max(choices,key=lambda c:(c['selection'],-c['reference_validation']['fp']-c['live_validation']['fp'],c['threshold']))
    artifact={'schema':1,'task':'snap_only_emg','model':selected['model'],'threshold':selected['threshold'],'signal':base['signal'],
              'input_modalities':['emg'],'uses_hand_state_model':False,'uses_camera':False,'uses_audio':False,'event_supervision':'reviewed_actions'}
    output.mkdir(parents=True);joblib.dump(artifact,output/'frozen-before-check.joblib')
    # This recording's check block was previously examined: explicitly development regression.
    old_check=parts(old,'test');new_check=parts(live,'test')
    report={'task':'standalone_snap_emg_candidate','version':'snap-only-01','base_bundle_sha256':_hash(base_path),
      'review_sha256':_hash(review_path),'frozen_before_check_sha256':_hash(output/'frozen-before-check.joblib'),
      'input_modalities':['emg'],'state_and_effort_models_changed':False,'selection':{k:v for k,v in selected.items() if k!='model'},
      'all_validation_candidates':[{k:v for k,v in c.items() if k!='model'} for c in choices],
      'development_check':{'candidate':score_snap_events(selected['model'],new_check,selected['threshold']),
                          'baseline':score_snap_events(base['snap_model'],new_check,base['snap_threshold'])},
      'known_reference_regression':score_snap_events(selected['model'],old_check,selected['threshold']),
      'splits':review['splits'],'trained_positive_windows':sum(label=='snap' for label in y),'trained_negative_windows':sum(label=='negative' for label in y),
      'limitations':['All features are EMG only; reviewed camera/audio supply labels, never input features.',
         'The seven later snap examples have already been examined. This is development regression, not a new untouched test.',
         'One new validation snap cannot establish coverage of lighter or unusual snaps. A separately recorded test session is required.',
         'Separate training alone does not guarantee higher accuracy. Equipment memory is a separate consumer of snap events.',
         'Two new check snap times are visual approximations with ambiguous audio; physical latency is uncalibrated.'],
      'activated':False}
    artifact['report']=report;joblib.dump(artifact,output/'snap-model.joblib');write_json(output/'training-report.json',report)
    return report
