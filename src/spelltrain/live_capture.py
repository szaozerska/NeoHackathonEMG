"""Reviewable live-test recordings. Predictions never become ground truth."""
from collections import Counter
from pathlib import Path
import json
import os
import time
import uuid
from .common import write_json


class LiveCapture:
    def __init__(self,root,clock,model_info):
        self.clock=clock;self.start=clock();self.end=None
        self.directory=Path(root)/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True,exist_ok=False)
        self.stream=(self.directory/'streams.jsonl').open('x',buffering=1)
        self.corrections=[];self.counts=Counter();self.closed=False
        self.last_seq=None;self.sequence_gaps=0;self.last_emg_t=None
        self.meta={'schema':1,'kind':'live_model_correction_session','id':self.directory.name,
          'started_host_uptime':self.start,'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
          'model':model_info,'recording_complete':False,'online_learning':False,'dataset_role':'development',
          'label_policy':'Predictions are observations, not training labels. Corrections are participant reports requiring review.',
          'time_basis':'capture_t is host monotonic seconds relative to Record; sensor timestamps/sequence remain original',
          'pre_roll_seconds':2.}
        write_json(self.directory/'metadata.json',self.meta)
        write_json(self.directory/'corrections.json',[])

    def append(self,kind,host_t,**data):
        if self.closed:return
        self.stream.write(json.dumps({'kind':kind,'capture_t':host_t-self.start,'host_uptime':host_t,
                                      **data},separators=(',',':'),allow_nan=False)+'\n')
        self.counts[kind]+=1
        if kind=='emg':
            seq=data.get('packet',{}).get('source_seq')
            if seq is not None and self.last_seq is not None and seq!=self.last_seq+1:self.sequence_gaps+=1
            self.last_seq=seq;self.last_emg_t=host_t-self.start

    def mark(self,gesture,observed,host_t,timing='after'):
        if self.closed:raise ValueError('Press Record before marking a correction')
        if gesture not in ('Nothing','Sword','Shield','Fireball','Shield release','Sword release','Fireball to Sword'):raise ValueError('Unknown gesture')
        if timing not in ('before','after','after_delayed'):raise ValueError('Unknown marker timing')
        point=host_t-self.start
        start,end=(point+.8,point+4.8) if timing=='before' else (max(-2.,point-(8. if timing=='after_delayed' else 2.)),point)
        correction={'id':uuid.uuid4().hex,'gesture':gesture,'reported_at':point,
            'review_window_start':start,'review_window_end':end,'timing':timing,
            'displayed_prediction':observed,'source':'participant_report','verified_event_time':False,
            'action_performed_verified':False,
            'instruction':'Prospective action cue; review the following action window.' if timing=='before' else
                          'Retrospective participant report. Review window is approximate, not an exact onset or a label for every sample.'}
        updated=self.corrections+[correction]
        write_json(self.directory/'corrections.json',updated);self.corrections=updated
        self.append('correction',host_t,correction=correction)
        return correction

    def finish(self,reason='user_stop'):
        if self.closed:return self.status()
        self.end=self.clock();self.stream.flush();os.fsync(self.stream.fileno());self.stream.close();self.closed=True
        self.meta.update(recording_complete=reason in ('user_stop','app_closed'),
                         stopped_host_uptime=self.end,duration_seconds=self.end-self.start,
                         stop_reason=reason,counts=dict(self.counts),correction_count=len(self.corrections),
                         sequence_discontinuities=self.sequence_gaps,last_emg_capture_t=self.last_emg_t)
        write_json(self.directory/'metadata.json',self.meta)
        return self.status()

    def status(self):
        return {'id':self.directory.name,'path':str(self.directory.resolve()),'active':not self.closed,
                'duration':(self.clock() if self.end is None else self.end)-self.start,
                'counts':dict(self.counts),'corrections':len(self.corrections),
                'last_correction':self.corrections[-1] if self.corrections else None,
                'complete':self.meta.get('recording_complete',False),'camera_reference':self.meta.get('camera_reference')}
