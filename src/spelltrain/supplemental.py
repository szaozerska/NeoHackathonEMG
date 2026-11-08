"""Focused extra data with independent local audio/video references.

Visual cue times are targets, never verified physical action timestamps.
"""
import base64
import binascii
import hashlib
import math
import random
from .common import write_json
from .shield_training import ShieldTraining

PROTOCOL='spells-supplemental-reference-v4'
LABEL_FILE='supplemental-trials-v4.json'


def protocol(session_id):
    conditions=[]
    def add(condition,title,instruction,hand='unlabeled',effort='unspecified',spell='none',cues=None,**extra):
        conditions.append({'condition':condition,'title':title,'instruction':instruction,
            'hand_state':hand,'effort':effort,'spell':spell,'movement':extra.pop('movement','hold'),
            'cues':cues or [],'reference_required':True,**extra})
    add('rest-supported','Relax · arm resting','Before Record, rest your arm and let your fingers hang loose. Keep your right hand visible. Stay relaxed for 6 seconds.','none','relaxed')
    add('rest-raised','Relax · arm raised','Before Record, raise your forearm comfortably and let your fingers relax naturally. Do not make a fist or shield. Keep your hand visible for 6 seconds.','none','relaxed')
    for i,detail in enumerate(('hold your arm comfortably near your side',
                               'hold your forearm with your palm side facing upward',
                               'gently rotate your wrist while keeping the fist closed')):
        add(f'fist-{i+1}',f'Sword · keep a fist closed ({i+1}/3)',
            f'Before Record, close your right fist comfortably. Then {detail}. Keep the fist closed throughout all 6 seconds. We only label closed fist, not its angle. Keep your hand visible.',
            'fist','comfortable','sword',movement='rotate' if i==2 else 'hold')
    add('close-open','Sword · close, hold, open',
        'Start with your hand open and visible. Press Record. Follow the changing cue: close your fist at 2 seconds, open at 4 seconds, then stay open until Stop at 6 seconds.',
        spell='sword',cues=[{'at':0,'text':'Keep hand OPEN'},{'at':2,'text':'CLOSE your fist now'},
                            {'at':4,'text':'OPEN your hand now'},{'at':6,'text':'Finished · press Stop'}],movement='transition')
    add('open-close','Sword · open, hold, close',
        'Start with a closed fist and your hand visible. Press Record. Open at 2 seconds, close at 4 seconds, then keep the fist closed until Stop at 6 seconds.',
        spell='sword',cues=[{'at':0,'text':'Keep fist CLOSED'},{'at':2,'text':'OPEN your hand now'},
                            {'at':4,'text':'CLOSE your fist now'},{'at':6,'text':'Finished · press Stop'}],movement='transition')
    for effort in ('light','medium','firm'):
        add('shield-'+effort,'Shield · '+effort+' tension',
            f'Before Record, extend your right arm comfortably, fingers up and palm facing outward. Keep fingers open and use {effort} forearm tension for all 6 seconds. Move your arm gently a little left and right while keeping the shield hand shape. Keep the hand in view. Firm is comfortable effort, not maximum effort.',
            'open',effort,'shield',movement='gentle_motion')
    add('shield-ramp','Shield · change tension',
        'Keep your shield hand open and visible. Follow the cues: light tension, then medium at 2 seconds, then firm at 4 seconds. Do not close your fist. Stop at 6 seconds.',
        'open',spell='shield',cues=[{'at':0,'text':'LIGHT forearm tension'},{'at':2,'text':'MEDIUM forearm tension'},
                                   {'at':4,'text':'FIRM comfortable tension'},{'at':6,'text':'Finished · press Stop'}],movement='effort_transition')
    for i in range(5):
        at=(2.,2.5,3.,2.,3.5)[i]
        add(f'snap-{i+1}',f'Fireball · one snap ({i+1}/5)',
            'Keep your right hand visible and near enough for the microphone to hear. Press Record and wait. Make exactly ONE middle-finger/thumb snap when “SNAP NOW” appears, then relax. Do not snap again. Press Stop at 6 seconds.',
            spell='fireball',cues=[{'at':0,'text':'Wait · keep your hand relaxed'},
                {'at':at,'text':'SNAP NOW · once only'},{'at':at+1,'text':'Relax · no more snaps'},
                {'at':6,'text':'Finished · press Stop'}],movement='snap',expected_snap_count=1)
    for condition,title,text in (
        ('pinch','touch without snapping','touch your middle finger and thumb together and release 2–3 times, without snapping'),
        ('wrist','move your wrist','gently flex and rotate your wrist, without snapping or holding a fist'),
        ('fingers','move your fingers','wiggle and curl your fingers naturally, without snapping or holding a fist'),
        ('ordinary','ordinary movement','make natural reaching and hand movements, without snapping or deliberately holding a fist')):
        add(condition,'Comparison · '+title,
            f'Press Record, then {text}. Keep your right hand visible. Stop at 6 seconds.',movement=condition,
            expected_snap_count=0)
    assert len(conditions)==20
    rng=random.Random(int.from_bytes(hashlib.sha256(session_id.encode()).digest()[:8],'big'))
    trials=[]
    for repetition in (1,2):
        block=conditions.copy();rng.shuffle(block)
        block=[c for c in block if c['condition']=='rest-supported']+[c for c in block if c['condition']!='rest-supported']
        trials += [{**c,'id':f"r{repetition}-{c['condition']}",'repetition':repetition,
                    'target_seconds':6,'minimum_seconds':5.5,'rest_seconds':5} for c in block]
    return trials


class SupplementalTraining(ShieldTraining):
    def __init__(self,session):
        super().__init__(session,protocol(session.meta['id']),PROTOCOL,LABEL_FILE)

    def status(self):
        result=super().status()
        result.update(rounds=2,reference_required=True,profile='supplemental',
                      dataset_role=self.session.meta.get('dataset_role','development'))
        return result

    def decorate_result(self,result):
        result=super().decorate_result(result)
        trial=self.by_id[result['motion']]
        if result['end']-result['start']<trial['minimum_seconds'] and not result['received']:
            result['message']='Too short. Follow the full cue sequence and Stop after 6 seconds.'
        return {**result,'reference_required':True,'reference':None,'requires_event_review':bool(trial['cues']),
                'cues_are_verified_events':False,'expected_snap_count':trial.get('expected_snap_count'),
                'intended_cues':trial['cues'],'independent_reference_reviewed':False,
                'dataset_role':self.session.meta.get('dataset_role','development')}

    def attach_reference(self,result_id,mime,data,alignment):
        extensions={'video/webm':'.webm','video/mp4':'.mp4','video/x-matroska':'.mkv'}
        media=mime.split(';')[0].strip()
        if media not in extensions:raise ValueError('Unsupported reference recording format')
        try:payload=base64.b64decode(data,validate=True)
        except (binascii.Error,ValueError):raise ValueError('Invalid reference data') from None
        return self.attach_reference_bytes(result_id,mime,payload,alignment)

    def attach_reference_bytes(self,result_id,mime,payload,alignment):
        extensions={'video/webm':'.webm','video/mp4':'.mp4','video/x-matroska':'.mkv'}
        media=mime.split(';')[0].strip()
        if media not in extensions:raise ValueError('Unsupported reference recording format')
        if not isinstance(payload,bytes):raise ValueError('Expected binary reference recording')
        if not 100<=len(payload)<=8*1024*1024:raise ValueError('Reference must be between 100 bytes and 8 MB')
        required=('recorder_start_ms','stop_requested_ms','start_request_ms','start_ack_ms','server_trial_start')
        if not isinstance(alignment,dict) or any(type(alignment.get(k)) not in (int,float) or not math.isfinite(alignment[k]) for k in required):
            raise ValueError('Reference timing metadata is required')
        if not alignment['recorder_start_ms']<=alignment['start_request_ms']<=alignment['start_ack_ms']<=alignment['stop_requested_ms']:
            raise ValueError('Invalid reference timing order')
        with self.lock:
            row=next((r for r in self.results if r['id']==result_id),None)
            if row is None or not row['received'] or row.get('confirmed') is not None:
                raise ValueError('Attach reference only to a received, unconfirmed trial')
            if abs(alignment['server_trial_start']-row['start'])>.001:
                raise ValueError('Reference belongs to a different capture')
            # A receipt-side clock estimate, not independently calibrated acquisition timing.
            offset=row['start']-(alignment['start_request_ms']+alignment['start_ack_ms'])/2000
            ref={'file':f"references/{result_id}{extensions[media]}",'mime':mime,'bytes':len(payload),
                 'sha256':hashlib.sha256(payload).hexdigest(),'alignment':alignment,
                 'estimated_session_start':alignment['recorder_start_ms']/1000+offset,
                 'network_half_rtt_seconds':(alignment['start_ack_ms']-alignment['start_request_ms'])/2000,
                 'hardware_latency_calibrated':False,'event_times_verified':False}
            path=self.session.directory/ref['file'];path.parent.mkdir(exist_ok=True)
            if path.exists():
                if (row.get('reference') or {}).get('sha256')==ref['sha256']:return dict(row)
                raise ValueError('A different reference is already attached')
            temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_bytes(payload);temporary.replace(path)
            replacement={**row,'reference':ref}
            updated=[replacement if r['id']==result_id else r for r in self.results]
            write_json(self.result_path,updated);self.results=updated
            return replacement

    def confirm(self,result_id,accepted):
        with self.lock:
            row=next((r for r in self.results if r['id']==result_id),None)
            if accepted is True and row and not row.get('reference'):
                raise ValueError('Save the camera/microphone reference before confirming, or retry this trial')
            return super().confirm(result_id,accepted)
