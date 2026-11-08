"""Independent camera observations and durable local reference recording.

No EMG probabilities enter the camera posture estimate. Geometry is a review
assistant, not ground truth; occlusion/handedness errors remain possible.
"""
from pathlib import Path
import hashlib
import json
import math
import re
import numpy as np
from .common import write_json,json_lines


def camera_posture(observation,target_hand='Right'):
    hands=observation.get('hands',[])
    eligible=[h for h in hands if h.get('handedness')==target_hand and h.get('score',0)>=.7]
    unknown={'label':'unknown','reason':'right_hand_not_clear','independently_reviewed':False}
    if len(eligible)!=1:return unknown
    hand=eligible[0]
    try:
        p=np.array(hand['world'],float);image=np.array(hand['landmarks'],float)
        if p.shape!=(21,3) or image.shape!=(21,3) or not np.isfinite(p).all() or not np.isfinite(image).all():return unknown
        if np.ptp(image[:,0])*np.ptp(image[:,1])<.0025:return {**unknown,'reason':'hand_too_small'}
        angles=[];folded=[]
        for base,joint,distal,tip in ((5,6,7,8),(9,10,11,12),(13,14,15,16),(17,18,19,20)):
            a=p[base]-p[joint];b=p[tip]-p[joint];den=np.linalg.norm(a)*np.linalg.norm(b)
            if den<1e-9:return unknown
            angles.append(float(np.degrees(np.arccos(np.clip(a@b/den,-1,1)))))
            folded.append(bool(np.linalg.norm(p[tip]-p[0])<np.linalg.norm(p[joint]-p[0])*1.2))
        label='open' if min(angles)>150 else 'fist' if max(angles)<120 and all(folded) else 'unknown'
        return {'label':label,'reason':'geometry' if label!='unknown' else 'ambiguous_finger_shape',
                'pip_angles_degrees':angles,'independently_reviewed':False}
    except (ValueError,KeyError,TypeError):return unknown


class CameraReference:
    def __init__(self,capture,mime,alignment):
        if mime.split(';')[0] not in ('video/webm','video/mp4'):raise ValueError('Unsupported camera format')
        self.capture=capture;self.directory=capture.directory/'camera';self.directory.mkdir(exist_ok=False)
        self.mime=mime;self.alignment=alignment;self.chunks={};self.complete=False
        self._metadata()
    def _metadata(self):
        write_json(self.directory/'reference.json',{'mime':self.mime,'alignment':self.alignment,
            'chunks':len(self.chunks),'complete':self.complete,'reference_only':True,
            'independently_reviewed':False,'video_is_emg_input':False})
    def chunk(self,index,payload):
        if self.complete:raise ValueError('Camera reference already finalized')
        if not 0<=index<100000 or not payload or len(payload)>16*1024*1024:raise ValueError('Invalid camera chunk')
        digest=hashlib.sha256(payload).hexdigest()
        if index in self.chunks:
            if self.chunks[index]!=digest:raise ValueError('Conflicting camera chunk')
            return
        path=self.directory/f'part-{index:06d}'
        with path.open('xb') as stream:
            stream.write(payload);stream.flush()
            import os
            os.fsync(stream.fileno())
        self.chunks[index]=digest;self._metadata()
    def finish(self,count,ended_client_t):
        if self.complete:return self.capture.meta.get('camera_reference')
        if count<1 or set(self.chunks)!=set(range(count)):raise ValueError('Camera chunks missing; retry saving')
        extension='.webm' if self.mime.startswith('video/webm') else '.mp4'
        path=self.directory/('reference'+extension);temporary=path.with_suffix('.partial');digest=hashlib.sha256()
        with temporary.open('xb') as stream:
            for i in range(count):
                payload=(self.directory/f'part-{i:06d}').read_bytes();digest.update(payload);stream.write(payload)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        temporary.replace(path)
        self.complete=True;self._metadata()
        reference={'file':str(path.relative_to(self.capture.directory)),'mime':self.mime,'sha256':digest.hexdigest(),
            'bytes':path.stat().st_size,'chunk_count':count,'alignment':self.alignment,'ended_client_t':ended_client_t,
            'complete':True,'independently_reviewed':False,'reference_only':True}
        self.capture.meta['camera_reference']=reference
        write_json(self.capture.directory/'metadata.json',self.capture.meta)
        return reference


def review_capture(directory):
    """Make a disagreement queue; never turn observer estimates into true labels."""
    directory=Path(directory);meta=json.loads((directory/'metadata.json').read_text());observations=[];frames=0;displays=[];camera_rows=[]
    for row in json_lines(directory/'streams.jsonl'):
        if row['kind']=='browser_display':displays.append({'capture_t':row['capture_t'],**row['display']})
        if row['kind']=='camera_observation':
            frames+=1;observation=row['observation'];label=observation['posture']['label']
            camera_rows.append({'capture_t':row['capture_t'],'label':label})
            if label!='unknown':
                observations.append({'capture_t':row['capture_t'],'label':label,
                    'band_state_at_receipt':observation['band_state_at_receipt'],
                    'band_equipment_at_receipt':observation.get('band_equipment_at_receipt'),
                    'disagreement_at_receipt':label!=observation['band_state_at_receipt'],
                    'independently_reviewed':False})
    report={'kind':'independent_camera_review_queue','reference':meta.get('camera_reference'),
        'camera_observations':frames,'scorable_camera_observations':len(observations),'unknown_camera_observations':frames-len(observations),
        'disagreements_at_receipt':sum(x['disagreement_at_receipt'] for x in observations),
        'observations':observations,'browser_display_changes':displays,'accuracy':None,'snap_event_times_verified':False,
        'note':'Camera geometry is independent of EMG but fallible. Compare video/audio and sensor timestamps before editing labels; receipt-time disagreement includes latency. No automatic training labels.'}
    proposals=[];run=[]
    def flush():
        if len(run)>=3 and run[-1]['capture_t']-run[0]['capture_t']>=.15:
            proposals.append({'label':run[0]['label'],'first_observed_capture_t':run[0]['capture_t'],
                'last_observed_capture_t':run[-1]['capture_t'],'frames':len(run),
                'boundary_policy':'Observed-frame span only; true transition lies between frames and requires review.',
                'source':'independent_camera_geometry','independently_reviewed':False,'eligible_for_automatic_training':False})
    for row in sorted(camera_rows,key=lambda row:row['capture_t']):
        if row['label']=='unknown' or (run and (row['label']!=run[-1]['label'] or row['capture_t']-run[-1]['capture_t']>.35)):
            flush();run=[]
        if row['label']!='unknown':run.append(row)
    flush()
    write_json(directory/'camera-state-proposals.json',{'proposals':proposals,'automatic_ground_truth':False,
        'note':'Review these suggested open/grip intervals against the media; they do not establish intent or exact transition times.'})
    report['camera_state_proposals']=len(proposals)
    write_json(directory/'external-review.json',report);return report
