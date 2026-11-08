"""Guided intent collection. Cues, sensors, predictions and reports stay separate."""
from collections import Counter
import hashlib
import math
import re
import uuid

import numpy as np

from .common import write_json


def protocol():
    trials=[]
    def add(key,title,instruction,kind,seconds,**extra):
        trials.append(dict(id=key,title=title,instruction=instruction,kind=kind,seconds=seconds,**extra))
    # Count-confirmed event clips, with freely chosen continuously varying angles.
    for i in range(20):
        variant=('relaxed / soft','natural','comfortable firm')[i%3]
        context=('choose a new comfortable wrist/arm angle anywhere along its range',
                 'slowly sweep through a comfortable continuous wrist rotation',
                 'change arm height and tilt freely')[i%3]
        add(f'snap-{i+1:02}',f'Intentional snap {i+1}/20',
            f'Make ONE {variant} purposeful snap; {context}. Open your hand afterward. Do not force a joint.',
            'snap',5,scenario='purposeful_snap',motion='continuous_or_free_angle',intensity=variant,intended_count=1)
    for i,(name,text,seconds) in enumerate([
        ('rest','Rest naturally. No spell intent and no snaps.',30),
        ('finger_fidget','Keep the wrist roughly still; wiggle, curl and touch fingers without snapping or spell intent.',20),
        ('wrist_sweep','Continuously rotate and tilt your wrist through comfortable angles. No snaps or spell intent.',20),
        ('wave','Wave and reach naturally, varying hand shape. No snaps or spell intent.',20),
        ('arm_swing','Move the whole arm naturally at different heights and speeds. Let the fingers move too. No spell intent or snaps.',30),
        ('walking','Walk naturally in a clear space with ordinary arm swing. No spell intent or snaps. Stay within camera view where practical.',40),
        ('pinch','Touch thumb and middle/index fingers, then release WITHOUT snapping.',15),
        ('grip_transition','Close and release your hand slowly, then quickly. No snaps or spell intent.',20),
        ('failed_snap','Attempt a snap gently. Report how many snaps actually occurred, including zero; do not label an attempt as a success.',10),
    ]):
        add(f'control-{i}',name.replace('_',' ').title(),text,'negative',seconds,scenario=name,intended_count=0)
    for i in range(3):
        add(f'open-{i}','Open hand stability',
            'Hold a completely open, non-fist hand for 10 seconds. Choose a different comfortable arm/wrist angle; palm-up is NOT required.',
            'open_hold',10,scenario='steady_open',intended_count=0)
        add(f'grip-{i}','Deliberate sword grip',
            'Hold a definite clasp/closed grip for 10 seconds at a different comfortable angle. No snapping. Do not squeeze maximally.',
            'fist',10,scenario='steady_grip',intended_count=0)
    for i,speed in enumerate(('slow','natural','quick')):
        add(f'transition-{i}','Snap → open hold → grip',
            f'Snap ONCE, open and hold for a few seconds while rotating freely, then make a definite {speed} grip. Finish gripping. Report actual snaps.',
            'transition',14,scenario='snap_open_grip',transition_speed=speed,intended_count=1)
    add('snap-grip','Snap → immediate grip',
        'Snap ONCE, then immediately grip without opening. This must not become a held Fireball. Report actual snaps.',
        'transition',10,scenario='snap_without_open',intended_count=1)
    add('snap-open','Snap → open hold with continuous movement',
        'Snap ONCE, then open completely and keep it open while freely rotating your wrist and moving your arm. No grip.',
        'transition',15,scenario='snap_open_moving',intended_count=1)
    for name,description in [
        ('immediate','Snap ONCE and open your hand as quickly as you naturally can. Hold it open. No minimum delay is required.'),
        ('delayed','Snap ONCE and open after what you consider the longest acceptable delay. Hold it open. We will review actual timing, not use this cue as the onset.'),
        ('never_open','Snap ONCE, then leave the hand relaxed without deliberately opening or gripping. Pending Fireball should expire, not turn into Sword.')]:
        add('timing-'+name,'Opening deadline · '+name.replace('_',' '),description,'transition',20,scenario='snap_open_'+name,intended_count=1)
    for i in range(6):
        add(f'intended-{i}','Intended interaction · no gesture label',
            'Deliberately make an interaction of your choice. Vary arm position, continuously chosen angles and comfortable intensity. Do not label which gesture it was yet.',
            'intent',15,scenario='binary_intended',requested_intent=True)
    for i,(scenario,instruction) in enumerate([
        ('everyday_rest','Rest naturally with no interaction intent.'),
        ('everyday_fingers','Move and fidget your fingers with the wrist roughly still. No interaction intent.'),
        ('everyday_wrist','Rotate/tilt your wrist continuously with no interaction intent.'),
        ('everyday_arm','Reach and move the whole arm naturally with no interaction intent.'),
        ('everyday_grip','Pick up or grip something normally with no spell/interaction intent.'),
        ('everyday_walking','Walk with natural arm swing in a clear space. No interaction intent.')]):
        add(f'nonintended-{i}','Ordinary activity · no interaction',instruction,'intent',20,scenario=scenario,requested_intent=False)
    return trials


class IntentCollection:
    def __init__(self,capture,clock,wearing_session,role,hand='Right',focus='full',initial_intent='non_intended',interaction_guard=1.,defer_cleanup=False):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',wearing_session):
            raise ValueError('Use a wearing-session ID with letters, numbers, hyphens or underscores.')
        if role not in ('train','evaluation') or hand not in ('Right','Left'):
            raise ValueError('Invalid collection role or hand')
        self.capture,self.clock=capture,clock
        if focus not in ('full','live_intent','intent','snaps','controls','states','transitions'):raise ValueError('Invalid collection focus')
        if initial_intent not in ('intended','non_intended') or not math.isfinite(interaction_guard) or not (0 if defer_cleanup else .5)<=interaction_guard<=3:raise ValueError('Invalid initial intent or click guard')
        kinds={'intent':('intent',),'snaps':('snap',),'controls':('negative',),'states':('open_hold','fist'),'transitions':('transition',)}
        self.plan=[] if focus=='live_intent' else [t for t in protocol() if focus=='full' or t['kind'] in kinds[focus]]
        self.index=0;self.phase='live' if focus=='live_intent' else 'ready';self.current=None;self.trials=[];self.flags=[]
        self.wearing_session,self.role,self.hand=wearing_session,role,hand
        self.interaction_guard=interaction_guard
        self.defer_cleanup=defer_cleanup
        self.intent_markers=[{'capture_t':0.,'label':initial_intent,'source':'participant_toggle_at_record_start','uncertainty_seconds':0.}]
        self.interactions=[{'capture_t':0.,'guard_seconds':interaction_guard,'kind':'record_start'}]
        self.space_down=None
        self.selected_motion=None;self.motion_selections=[];self.focus_lost=None
        self.animation_phase_markers=[]
        self.active_test_condition=None;self.condition_markers=[]
        self.gyro_report={'samples':0,'min_xyz':None,'max_xyz':None,'first_capture_t':None,'last_capture_t':None,
            'last_native_timestamp_us':None,'positive_intervals':0,'native_positive_span_seconds':0.,'timestamp_discontinuities':0}
        self.signal_segments=[];self.global_last_seq=None;self.global_last_t=None;self.global_generation=None
        self.sensor_segments=[];self.last_sensor_seq=None;self.last_sensor_t=None;self.last_sensor_epoch=None
        self.capture.meta.update(kind='intent_collection_v1',wearing_session=wearing_session,target_hand=hand,
            dataset_role='training_only_weak_labels' if role=='train' else 'untouched_guided_count_check',
            collection_protocol='snap-open-grip-and-nonuse-v1',
            equipment_rule='purposeful snap starts pending; open confirms Fireball; confirmed grip selects Sword; unknown is not grip',
            camera_policy='independent review evidence, not automatic truth',
            orientation_policy='continuous measured wrist quaternion; no discrete angle requirement; no absolute palm-angle claim')
        self._save()

    def _save(self):
        write_json(self.capture.directory/'metadata.json',self.capture.meta)
        write_json(self.capture.directory/'intent-trials.json',self.trials)
        write_json(self.capture.directory/'failure-flags.json',self.flags)
        write_json(self.capture.directory/'collection-plan.json',self.plan)
        write_json(self.capture.directory/'intent-toggle-markers.json',self.intent_markers)
        write_json(self.capture.directory/'interaction-exclusions.json',self.interactions)
        write_json(self.capture.directory/'motion-selections.json',self.motion_selections)

    def select_motion(self,motion,effort=None):
        if self.intent_markers[-1]['label']=='intended':raise ValueError('Release Space before changing the selected motion.')
        animation=self.capture.meta.get('collection_variant')=='animation'
        steps=self.capture.meta.get('collection_variant')=='animation_steps'
        validation=self.capture.meta.get('collection_variant')=='validation'
        if validation and (motion not in ('snap','shield_hold','sword_hold','animation_gesture') or
            (motion in ('snap','animation_gesture') and effort is not None) or
            (motion in ('shield_hold','sword_hold') and effort not in ('low','medium','high'))):
            raise ValueError('Choose Snap, Animation Gesture, or Shield/Sword with low, medium or high effort.')
        if steps and (motion not in ('animation_cross_fingers','animation_curl_ring_pinky','animation_thumb_approach','animation_sequence') or effort is not None):
            raise ValueError('Select an Animation Gesture component or the combined sequence.')
        if animation and (motion!='animation_gesture' or effort is not None):
            raise ValueError('This session collects Animation Gesture only.')
        if not animation and not steps and not validation and (motion not in ('snap','shield_hold','sword_hold') or (motion=='snap' and effort is not None) or (motion!='snap' and effort not in ('low','medium','high'))):
            raise ValueError('Select Snap, or a Shield/Sword hold with low, medium or high effort.')
        if self.capture.meta.get('test_condition')=='static' and motion=='snap':raise ValueError('Static testing supports Shield and Sword holds only.')
        self.interaction(kind='motion_selection')
        self.selected_motion={'motion':motion,'effort':effort,'source':'participant_selection','performed_verified':False}
        self.motion_selections.append({'capture_t':self.clock()-self.capture.start,**self.selected_motion})
        self.capture.append('motion_selection',self.clock(),selection=self.selected_motion)
        write_json(self.capture.directory/'motion-selections.json',self.motion_selections)
        return self.selected_motion

    def interaction(self,host=None,uncertainty=0.,kind='button'):
        host=self.clock() if host is None else host
        if not math.isfinite(host) or abs(self.clock()-host)>5 or not math.isfinite(uncertainty) or not 0<=uncertainty<=.5:
            raise ValueError('Refresh clock alignment before marking intent.')
        row={'capture_t':host-self.capture.start,'guard_seconds':0 if self.defer_cleanup else self.interaction_guard+uncertainty,'kind':kind,
             'clock_uncertainty_seconds':uncertainty,'applied_to_export':not self.defer_cleanup}
        if kind=='space_keydown':self.space_down=host
        if kind=='space_keyup' and self.space_down is not None:
            # Exclude the full key hold, not just its two edges.
            row['capture_t']=(host+self.space_down)/2-self.capture.start
            row['guard_seconds']+=(host-self.space_down)/2
            self.space_down=None
        if kind=='focus_lost':self.focus_lost=host
        if kind=='focus_regained' and self.focus_lost is not None:
            row['capture_t']=(host+self.focus_lost)/2-self.capture.start
            row['guard_seconds']+=(host-self.focus_lost)/2
            self.focus_lost=None
        self.interactions.append(row)
        self.capture.append('participant_interaction',host,interaction=row)
        write_json(self.capture.directory/'interaction-exclusions.json',self.interactions)

    def configure_validation(self,condition):
        self.active_test_condition=condition
        self.intent_markers[0]['test_condition']=condition
        self.condition_markers=[{'capture_t':0.,'test_condition':condition,'source':'participant_selection_at_start'}]
        write_json(self.capture.directory/'condition-markers.json',{'markers':self.condition_markers})
        self._save()

    def select_condition(self,condition,host,uncertainty=0.,alignment=None):
        if self.capture.meta.get('collection_variant')!='validation':raise ValueError('Use the combined validation collector.')
        if condition not in ('static','dynamic'):raise ValueError('Choose static or dynamic.')
        if self.intent_markers[-1]['label']=='intended':raise ValueError('Release Space before switching Static/Dynamic.')
        # Validation and event ordering must succeed before changing the active condition.
        self.interaction(host,uncertainty,'condition_selection')
        if host-self.capture.start<self.intent_markers[-1]['capture_t']:raise ValueError('Condition event arrived out of order.')
        previous=self.active_test_condition;self.active_test_condition=condition
        try:self.mark_intent('non_intended',host,uncertainty,alignment,report_source='participant_condition_switch')
        except Exception:
            self.active_test_condition=previous;raise
        marker={'capture_t':host-self.capture.start,'test_condition':condition,'source':'participant_condition_switch','browser_clock_alignment':alignment}
        self.condition_markers.append(marker);self.capture.append('condition_selection',host,marker=marker)
        write_json(self.capture.directory/'condition-markers.json',{'markers':self.condition_markers})
        return {'test_condition':condition,'annotation':self.annotation_status()}

    def mark_intent(self,label,host=None,uncertainty=0.,alignment=None,report_source=None):
        if label not in ('intended','non_intended'):raise ValueError('Invalid intent label')
        if label=='intended' and self.capture.meta.get('recording_profile')=='micah_emg' and not self.selected_motion:
            raise ValueError('Select a motion and effort before holding Space.')
        host=self.clock() if host is None else host
        if host-self.capture.start<self.intent_markers[-1]['capture_t']:raise ValueError('Intent marker arrived out of order; retry.')
        self.interaction(host,uncertainty,'intent_toggle')
        marker={'capture_t':host-self.capture.start,'label':label,'source':'participant_toggle',
                'uncertainty_seconds':uncertainty,'exact_action_time_verified':False}
        if alignment is not None:marker['browser_clock_alignment']=alignment
        if self.capture.meta.get('recording_profile')=='micah_emg':
            marker['source']='participant_spacebar_press' if label=='intended' else 'participant_spacebar_release'
            marker['selected_motion']=dict(self.selected_motion) if label=='intended' and self.selected_motion else None
        if self.active_test_condition:marker['test_condition']=self.active_test_condition
        if report_source:marker['source']=report_source
        self.intent_markers.append(marker);self.capture.append('intent_toggle',host,marker=marker)
        write_json(self.capture.directory/'intent-toggle-markers.json',self.intent_markers)
        if self.capture.meta.get('collection_variant')=='animation_steps' and self.capture.meta.get('phase_reporting_enabled',True):
            if label=='intended':
                phase={'animation_cross_fingers':'cross_fingers','animation_curl_ring_pinky':'curl_ring_pinky',
                       'animation_thumb_approach':'thumb_approach','animation_sequence':'cross_fingers'}[self.selected_motion['motion']]
                self.mark_animation_phase(phase,host,uncertainty,alignment,source='participant_spacebar_start')
            else:
                self.animation_phase_markers.append({'capture_t':host-self.capture.start,'phase':'end',
                    'intent_marker_index':len(self.intent_markers)-1,'source':'participant_spacebar_release',
                    'exact_action_time_verified':False,'clock_uncertainty_seconds':uncertainty})
                self.save_animation_phases()
        return self.annotation_status()

    def mark_animation_phase(self,phase,host=None,uncertainty=0.,alignment=None,source='participant_phase_report'):
        if self.capture.meta.get('collection_variant')!='animation_steps':raise ValueError('Start the step-mapping collector first.')
        if self.capture.meta.get('phase_reporting_enabled') is False:raise ValueError('This collector uses action selection and Space only.')
        if self.intent_markers[-1]['label']!='intended':raise ValueError('Hold Space before marking a finger step.')
        combined=self.selected_motion['motion']=='animation_sequence'
        order=['cross_fingers','curl_ring_pinky','thumb_approach','combined_hold'] if combined else [
            {'animation_cross_fingers':'cross_fingers','animation_curl_ring_pinky':'curl_ring_pinky','animation_thumb_approach':'thumb_approach'}[self.selected_motion['motion']], 'component_hold']
        if phase not in order:raise ValueError('Choose a phase that belongs to the selected action.')
        host=self.clock() if host is None else host
        trial=len(self.intent_markers)-1
        previous=[m for m in self.animation_phase_markers if m['intent_marker_index']==trial]
        if previous and order.index(phase)<=order.index(previous[-1]['phase']):raise ValueError('Finger-step markers must progress forward; release Space to restart.')
        if host-self.capture.start<max(self.intent_markers[-1]['capture_t'],previous[-1]['capture_t'] if previous else 0):raise ValueError('Phase marker arrived out of order.')
        self.interaction(host,uncertainty,'animation_phase_report')
        marker={'capture_t':host-self.capture.start,'phase':phase,'selected_motion':dict(self.selected_motion),
                'intent_marker_index':trial,'source':source,'clock_uncertainty_seconds':uncertainty,
                'browser_clock_alignment':alignment,'exact_action_time_verified':False,
                'skipped_preceding_phases':order[(order.index(previous[-1]['phase'])+1 if previous else 0):order.index(phase)]}
        self.animation_phase_markers.append(marker)
        self.capture.append('animation_phase_report',host,marker=marker)
        self.save_animation_phases()
        return marker

    def save_animation_phases(self,final=False):
        phases=[]
        for i,marker in enumerate(self.animation_phase_markers):
            if marker['phase']=='end':continue
            next_marker=self.animation_phase_markers[i+1] if i+1<len(self.animation_phase_markers) else None
            end=next_marker['capture_t'] if next_marker else self.capture.meta.get('duration_seconds',self.clock()-self.capture.start)
            if end>marker['capture_t']:
                phases.append({'start':marker['capture_t'],'end':end,'phase':marker['phase'],
                    'selected_motion':marker['selected_motion'],'intended':True,'intent_marker_index':marker['intent_marker_index'],
                    'test_condition':self.capture.meta['test_condition'],'supervision':'weak_participant_phase_report',
                    'exact_action_times_verified':False,'end_reported':next_marker is not None})
        write_json(self.capture.directory/'animation-phase-markers.json',{'markers':self.animation_phase_markers,'participant_reports_only':True})
        write_json(self.capture.directory/'animation-phase-intervals.json',{'intervals':phases,'recording_complete':final,
            'note':'Reports map component/sequence steps to EMG time; they are not sensor-verified movement onset or completion. Unmarked internal transitions remain unknown.'})

    def annotation_status(self):
        return {'label':self.intent_markers[-1]['label'],'markers':len(self.intent_markers),
                'labeling_paused_seconds':0 if self.defer_cleanup else max(0,max(event['capture_t']+event['guard_seconds'] for event in self.interactions)-(self.clock()-self.capture.start)),
                'cleanup_deferred':self.defer_cleanup,
                'interaction_guard_seconds':self.interaction_guard,'policy':'Immediate reported intervals; no clipping; cleanup deferred.' if self.defer_cleanup else 'Exclude time before and after every reported interaction; button boundaries are weak labels, not exact action onset.'}

    def start_trial(self,connected):
        if not connected:raise ValueError('Wait for fresh EMG before starting a trial.')
        if self.phase not in ('ready','between'):raise ValueError('Confirm or discard the current trial first.')
        if self.index>=len(self.plan):raise ValueError('Plan is complete; finish and save the session.')
        now=self.clock()
        self.current={**self.plan[self.index],'trial_id':uuid.uuid4().hex,'cue_host_uptime':now,
            'start':now-self.capture.start+3,'end':now-self.capture.start+3+self.plan[self.index]['seconds'],
            'confirmed':False,'reported_count':None,'exact_event_times_verified':False,
            'packets':0,'samples':0,'gaps':0,'max_source_silence':0.,'predicted_snaps':0,
            'camera_labels':{},'orientation_samples':0,'gyro_samples':0,
            'orientation_path_degrees':0.,'orientation_max_from_start_degrees':0.,
            'gyro_peak_raw':0.,'emg_channel_sum':[0.]*8,'emg_channel_sumsq':[0.]*8}
        self.last_seq=None;self.last_emg=None;self.last_q=None;self.first_q=None
        self.phase='countdown';self.capture.append('trial_cue',now,trial=self.current.copy());self._save()
        return self.status()

    def tick(self):
        if not self.current:return
        t=self.clock()-self.capture.start
        if self.phase=='countdown' and t>=self.current['start']:self.phase='active'
        if self.phase=='active' and t>=self.current['end']:
            self.phase='review'
            self.capture.append('trial_window_ended',self.clock(),trial_id=self.current['trial_id'])

    def packet(self,packet):
        self.tick()
        native=packet.get('source_t');timing=packet.get('timing') or {};epoch=timing.get('clock_epoch',packet.get('input_generation'))
        if isinstance(native,(int,float)) and math.isfinite(native):
            expected=len(packet['samples'])*1e6/2048
            continuous=(self.last_sensor_seq is not None and packet['source_seq']==self.last_sensor_seq+1
                and epoch==self.last_sensor_epoch and abs(native-self.last_sensor_t-expected)<=2.5e6/2048)
            mapped=timing.get('mapped_band_host_uptime_estimate')
            mapped_t=mapped-self.capture.start if isinstance(mapped,(int,float)) else None
            if continuous and self.sensor_segments:
                segment=self.sensor_segments[-1];segment.update(band_end_us=native,last_sequence=packet['source_seq'],mapped_end_capture_t_estimate=mapped_t)
                segment['samples']+=len(packet['samples'])
            else:
                self.sensor_segments.append({'clock_epoch':epoch,'band_start_us':native,'band_end_us':native,
                    'first_sequence':packet['source_seq'],'last_sequence':packet['source_seq'],'samples':len(packet['samples']),
                    'mapped_start_capture_t_estimate':mapped_t,'mapped_end_capture_t_estimate':mapped_t})
            self.last_sensor_seq,self.last_sensor_t,self.last_sensor_epoch=packet['source_seq'],native,epoch
        t=packet.get('source_uptime',self.clock())-self.capture.start
        seq=packet['source_seq'];generation=packet.get('input_generation')
        contiguous=(self.global_last_seq is not None and seq==self.global_last_seq+1 and generation==self.global_generation
                    and 0<t-self.global_last_t<=.1)
        if t>=0:
            if contiguous and self.signal_segments:self.signal_segments[-1]['end']=t
            else:self.signal_segments.append({'start':t,'end':t})
        self.global_last_seq,self.global_last_t,self.global_generation=seq,t,generation
        if self.phase not in ('countdown','active','review') or not self.current:return
        if not self.current['start']<=t<=self.current['end']:return
        trial=self.current;seq=packet['source_seq']
        if self.last_seq is not None and seq!=self.last_seq+1:trial['gaps']+=1
        if self.last_emg is not None:trial['max_source_silence']=max(trial['max_source_silence'],t-self.last_emg)
        self.last_seq,self.last_emg=seq,t
        x=np.asarray(packet['samples'],float)
        trial['packets']+=1;trial['samples']+=len(x)
        trial.setdefault('first_emg_t',t);trial['last_emg_t']=t
        trial['emg_channel_sum']=(np.asarray(trial['emg_channel_sum'])+x.sum(0)).tolist()
        trial['emg_channel_sumsq']=(np.asarray(trial['emg_channel_sumsq'])+(x*x).sum(0)).tolist()

    def predicted_snap(self):
        self.tick()
        if self.phase=='active':self.current['predicted_snaps']+=1

    def context(self,kind,value,host):
        self.tick()
        if kind=='gyro' and host>=self.capture.start:
            xyz=np.asarray(value.get('payload',{}).get('values',[]),float)
            if xyz.shape==(3,) and np.isfinite(xyz).all():
                report=self.gyro_report;native=value.get('band_timestamp_us')
                if report['samples']==0:
                    report['min_xyz']=xyz.tolist();report['max_xyz']=xyz.tolist();report['first_capture_t']=host-self.capture.start
                else:
                    report['min_xyz']=np.minimum(report['min_xyz'],xyz).tolist();report['max_xyz']=np.maximum(report['max_xyz'],xyz).tolist()
                if isinstance(native,(int,float)) and math.isfinite(native):
                    previous=report['last_native_timestamp_us']
                    if previous is not None:
                        delta=(native-previous)/1e6
                        if 0<delta<1:report['positive_intervals']+=1;report['native_positive_span_seconds']+=delta
                        else:report['timestamp_discontinuities']+=1
                    report['last_native_timestamp_us']=native
                report['samples']+=1;report['last_capture_t']=host-self.capture.start
        if not self.current or not self.current['start']<=host-self.capture.start<=self.current['end']:return
        if kind=='camera':
            labels=self.current['camera_labels'];label=value['posture']['label'];labels[label]=labels.get(label,0)+1
            hands=[h for h in value.get('hands',[]) if h.get('handedness')==self.hand and h.get('score',0)>=.7]
            if len(hands)==1:
                points=np.asarray(hands[0].get('landmarks'),float)
                if points.shape==(21,3) and np.isfinite(points).all():
                    p=points[0,:2]
                    self.current['camera_wrist_count']=self.current.get('camera_wrist_count',0)+1
                    self.current['camera_wrist_sum']=(np.asarray(self.current.get('camera_wrist_sum',[0.,0.]))+p).tolist()
                    self.current['camera_wrist_sumsq']=(np.asarray(self.current.get('camera_wrist_sumsq',[0.,0.]))+p*p).tolist()
        elif kind=='orientation':
            q=np.asarray(value['payload']['values'],float)
            if q.shape!=(4,) or not np.isfinite(q).all() or np.linalg.norm(q)<.5:return
            q=q/np.linalg.norm(q);self.current['orientation_samples']+=1
            angle=lambda a,b:float(2*np.degrees(np.arccos(np.clip(abs(a@b),0,1))))
            if self.first_q is None:self.first_q=q
            if self.last_q is not None:self.current['orientation_path_degrees']+=angle(q,self.last_q)
            self.current['orientation_max_from_start_degrees']=max(self.current['orientation_max_from_start_degrees'],angle(q,self.first_q))
            self.last_q=q
        elif kind=='gyro':
            xyz=np.asarray(value['payload']['values'],float)
            if xyz.shape==(3,) and np.isfinite(xyz).all():
                self.current['gyro_samples']+=1;self.current['gyro_peak_raw']=max(self.current['gyro_peak_raw'],float(np.linalg.norm(xyz)))

    def flag(self,kind,note=''):
        if kind not in ('false_snap','missed_snap','false_grip','lost_fireball','other'):raise ValueError('Unknown failure flag')
        if not isinstance(note,str) or len(note)>1000:raise ValueError('Keep the note under 1000 characters.')
        t=self.clock()-self.capture.start
        flag={'id':uuid.uuid4().hex,'kind':kind,'reported_at':t,'review_start':max(0,t-8),'review_end':t+2,
              'note':note,'source':'participant_report','exact_event_times_verified':False}
        self.flags.append(flag);self.capture.append('failure_flag',self.clock(),flag=flag);self._save();return flag

    def confirm(self,value):
        self.tick()
        if self.phase!='review':raise ValueError('Wait for this trial to finish.')
        discard=value.get('discard') is True
        count=value.get('actual_snaps')
        binary=self.current['kind']=='intent'
        if not discard and binary and value.get('intent_label') not in ('intended','non_intended'):
            raise ValueError('Explicitly report intended or non-intended activity, or discard.')
        if not discard and not binary and (type(count) is not int or not 0<=count<=100):
            raise ValueError('Report the actual snap count, including zero; no default is assumed.')
        if not discard and value.get('performed') is not True:raise ValueError('Confirm what you actually performed, or discard.')
        trial=self.current.copy();trial.update(reported_count=None if discard else count,
            participant_confirmed=not discard,label_source='participant_confirmation',
            reported_hand_state=value.get('hand_state','unknown'),intent_confirmed=value.get('intent') is True,
            note=str(value.get('note',''))[:1000])
        trial['binary_intent_label']=None if discard else value.get('intent_label') if binary else ('intended' if value.get('intent') is True else 'non_intended')
        if binary:trial['reported_count']=None;trial['reported_hand_state']='unknown';trial['intent_confirmed']=value.get('intent_label')=='intended'
        if trial['reported_hand_state'] not in ('open','fist','relaxed','mixed','unknown'):raise ValueError('Invalid reported hand state')
        duration=trial['end']-trial['start']
        trial['signal_usable']=(trial['samples']>=duration*2048*.85 and trial['gaps']==0 and not trial.get('source_changes')
            and trial.get('first_emg_t',math.inf)<=trial['start']+.6
            and trial.get('last_emg_t',-math.inf)>=trial['end']-.6 and trial['max_source_silence']<.6)
        trial['confirmed']=not discard and trial['signal_usable']
        if trial['samples']:
            mean=np.asarray(trial['emg_channel_sum'])/trial['samples']
            trial['emg_channel_std_adc']=np.sqrt(np.maximum(0,np.asarray(trial['emg_channel_sumsq'])/trial['samples']-mean**2)).tolist()
        if trial.get('camera_wrist_count'):
            n=trial['camera_wrist_count'];mean=np.asarray(trial['camera_wrist_sum'])/n
            trial['camera_wrist_rms_image']=float(np.sqrt(np.maximum(0,np.asarray(trial['camera_wrist_sumsq'])/n-mean**2).sum()))
        trial['stability_verified']=False
        trial['false_snap_candidates']=trial['predicted_snaps'] if count==0 and not discard and not binary else None
        trial['count_difference']=trial['predicted_snaps']-count if not discard and not binary else None
        trial['event_precision']=None;trial['event_recall']=None
        self.trials.append(trial);self.capture.append('trial_confirmation',self.clock(),trial=trial)
        if value.get('retry') is not True:self.index+=1
        self.phase='between' if self.index<len(self.plan) else 'complete';self.current=None;self._save()
        return self.status()

    def finish(self):
        if self.space_down is not None:self.interaction(kind='space_keyup')
        if self.focus_lost is not None:self.interaction(kind='focus_regained')
        if self.phase!='finished':self.interaction(kind='record_finish')
        if self.current:
            trial={**self.current,'confirmed':False,'interrupted':True};self.trials.append(trial)
            self.current=None
        self.phase='finished';self._save()

    def finalize(self):
        # Export only compatible, participant-confirmed clips; transitions need interval review.
        exported=[]
        gate_trials=[]
        for trial in self.trials:
            if not trial.get('confirmed'):continue
            kind=trial['kind']
            if kind=='intent':
                gate_trials.append({**trial,'label':trial['binary_intent_label']})
                continue
            if kind=='transition':continue
            if kind=='open_hold':
                continue  # Distinct from the trained deliberate-shield open class.
            if kind=='fist' and trial['reported_hand_state']!='fist':continue
            if kind=='fist' and trial['reported_count']!=0:continue
            exported.append({**trial,'id':trial['trial_id']})
        write_json(self.capture.directory/'guided-trials.json',exported)
        write_json(self.capture.directory/'intent-gate-trials.json',gate_trials)
        # Split stable toggle spans around all interactions and actual signal gaps.
        intervals=[];duration=self.capture.meta.get('duration_seconds',0)
        for i,marker in enumerate(self.intent_markers):
            end=self.intent_markers[i+1]['capture_t'] if i+1<len(self.intent_markers) else duration
            spans=[(max(0,marker['capture_t']),min(duration,end))]
            for event in ([] if self.defer_cleanup else self.interactions):
                a,b=event['capture_t']-event['guard_seconds'],event['capture_t']+event['guard_seconds']
                spans=[part for lo,hi in spans for part in ((lo,min(hi,a)),(max(lo,b),hi)) if part[1]>part[0]]
            for lo,hi in spans:
                for signal in ([{'start':0,'end':duration}] if self.defer_cleanup else self.signal_segments):
                    a,b=max(lo,signal['start']),min(hi,signal['end'])
                    if (b>a if self.defer_cleanup else b-a>=.5):intervals.append({'start':a,'end':b,'label':marker['label'],
                        'wearing_session':self.wearing_session,'dataset_role':self.capture.meta['dataset_role'],
                        'source':'participant_spacebar_untrimmed' if self.defer_cleanup else 'participant_toggle_with_interaction_exclusion','supervision':'weak_interval_label',
                        'gesture_label':None,'selected_motion':marker.get('selected_motion'),'exact_action_times_verified':False,
                        'test_condition':marker.get('test_condition',self.capture.meta.get('test_condition','dynamic'))})
        write_json(self.capture.directory/'intent-gate-intervals.json',{'intervals':intervals,'gesture_labels_required':False,
            'interaction_guard_seconds':self.interaction_guard,'postprocessing_required':self.defer_cleanup,
            'policy':'Untrimmed participant windows; use raw EMG and baseline context for later cleanup. Missing samples are not imputed.' if self.defer_cleanup else 'Guarded participant reports intersected with continuous EMG; not inferred mental intent.'})
        names=('streams.jsonl','metadata.json','guided-trials.json','intent-gate-trials.json','intent-trials.json','failure-flags.json','collection-plan.json','intent-toggle-markers.json','interaction-exclusions.json','intent-gate-intervals.json','motion-selections.json')
        if self.capture.meta.get('recording_profile')=='micah_emg':
            for i,interval in enumerate(intervals):
                if interval['label']=='intended':
                    interval['baseline_before']={k:intervals[i-1][k] for k in ('start','end')} if i>0 and intervals[i-1]['label']=='non_intended' else None
                    interval['baseline_after']={k:intervals[i+1][k] for k in ('start','end')} if i+1<len(intervals) and intervals[i+1]['label']=='non_intended' else None
            write_json(self.capture.directory/'signal-coverage.json',{'segments':self.sensor_segments,
                'time_basis':'native_band_microseconds','host_receipt_segments':self.signal_segments,
                'note':'Continuity uses native batch timestamps and sequence, not bursty host arrivals. Mapped host bounds are estimates. Reported label windows remain untrimmed; missing samples are not imputed.'})
            truth={'contributor':'Micah','input_modalities':['emg'],'camera_used':False,
                'test_condition':self.capture.meta.get('test_condition','dynamic'),
                'label_source':'participant_spacebar_reports','exact_action_onsets_verified':False,
                'postprocessing_required':self.defer_cleanup,'cleanup_applied':not self.defer_cleanup,
                'interaction_guard_seconds':self.interaction_guard,
                'intervals':[{**v,'intended':v['label']=='intended'} for v in intervals],
                'note':'Untrimmed participant-reported intention windows. All raw data and adjacent non-intended baselines are retained. Review actual motion boundaries during postprocessing; consult signal-coverage.json for missing data.'}
            write_json(self.capture.directory/'truth-values.json',truth)
            names+=('truth-values.json','signal-coverage.json')
        hashes={name:hashlib.sha256((self.capture.directory/name).read_bytes()).hexdigest() for name in names}
        if self.capture.meta.get('collection_variant')=='validation':
            hashes['condition-markers.json']=hashlib.sha256((self.capture.directory/'condition-markers.json').read_bytes()).hexdigest()
        if self.capture.meta.get('collection_variant')=='animation_steps':
            self.save_animation_phases(final=True)
            hashes.update({name:hashlib.sha256((self.capture.directory/name).read_bytes()).hexdigest()
                for name in ('animation-phase-markers.json','animation-phase-intervals.json')})
        if self.capture.meta.get('recording_profile')=='micah_emg':
            gyro=self.gyro_report
            write_json(self.capture.directory/'gyro-report.json',{**gyro,'available':gyro['samples']>0,
                'measured_native_hz':gyro['positive_intervals']/gyro['native_positive_span_seconds'] if gyro['native_positive_span_seconds'] else None,
                'used_for_classification':False,'required_for_collection':False,
                'units':'raw gyro counts; physical calibration unverified',
                'note':'Optional context only. Original timestamped XYZ events remain in streams.jsonl when received. Zero samples means unavailable, not zero movement.'})
            hashes['gyro-report.json']=hashlib.sha256((self.capture.directory/'gyro-report.json').read_bytes()).hexdigest()
        write_json(self.capture.directory/'guided-manifest.json',{'schema':1,'wearing_session':self.wearing_session,
            'supervision':'untrimmed_participant_intervals_requires_postprocessing' if self.defer_cleanup else 'weak_clip_labels',
            'postprocessing_required':self.defer_cleanup,'source_hashes':hashes,'open_hold_and_transitions_require_review':True})
        controls=[t for t in self.trials if t.get('confirmed') and t.get('reported_count')==0]
        negative_seconds=sum(t['end']-t['start'] for t in controls)
        false_candidates=sum(t['predicted_snaps'] for t in controls)
        report={'trials':len(self.trials),'usable_confirmed':sum(t.get('confirmed',False) for t in self.trials),
            'postprocessing_required':self.defer_cleanup,'interval_policy':'untrimmed_participant_reports' if self.defer_cleanup else 'guarded_continuous_signal',
            'exported_training_clips':len(exported),'failure_flags':len(self.flags),'dataset_role':self.capture.meta['dataset_role'],
            'binary_intent_clips':len(gate_trials),
            'toggle_intervals':len(intervals),'toggle_labeled_seconds':sum(v['end']-v['start'] for v in intervals),
            'intended_seconds':sum(v['end']-v['start'] for v in intervals if v['label']=='intended'),
            'non_intended_seconds':sum(v['end']-v['start'] for v in intervals if v['label']=='non_intended'),
            'confirmed_zero_snap_seconds':negative_seconds,'false_snap_candidates':false_candidates,
            'false_snap_candidates_per_minute':60*false_candidates/negative_seconds if negative_seconds else None,
            'actual_event_precision':None,'actual_event_recall':None,'automatically_retrained':False,
            'note':'Count agreement is not event accuracy. False-candidate rate uses participant-confirmed zero-snap clips only. Camera estimates and model outputs are never truth. Open holds remain separate from deliberate shield labels.'}
        if self.capture.meta.get('collection_variant')=='validation':
            report['seconds_by_condition']={condition:{label:sum(v['end']-v['start'] for v in intervals
                if v['test_condition']==condition and v['label']==label) for label in ('intended','non_intended')}
                for condition in ('static','dynamic')}
            report['evaluation_status']='reserved_unscored'
            report['do_not_train']=True
        write_json(self.capture.directory/'collection-report.json',report)
        return report

    def status(self):
        self.tick();t=self.clock()-self.capture.start
        trial=self.current or (self.plan[self.index] if self.index<len(self.plan) else None)
        remaining=max(0,(self.current['start'] if self.phase=='countdown' else self.current['end'])-t) if self.current else None
        return {'phase':self.phase,'index':self.index,'total':len(self.plan),'trial':trial,'remaining':remaining,
                'saved_trials':len(self.trials),'usable_trials':sum(t.get('confirmed',False) for t in self.trials),
                'wearing_session':self.wearing_session,'role':self.role,'hand':self.hand,'failure_flags':len(self.flags),
                'annotation':self.annotation_status(),'selected_motion':self.selected_motion,
                'animation_phase':self.animation_phase_markers[-1] if self.animation_phase_markers else None,
                'animation_phase_reports':sum(v['phase']!='end' for v in self.animation_phase_markers)}


class EquipmentPreview:
    """Provisional EMG-only rule preview, never participant truth or deployed game logic."""
    def __init__(self):
        self.item='none';self.grip_since=None;self.open_since=None;self.last_state_t=None;self.snap_at=None
        self.grip_threshold=.85;self.grip_dwell=.15;self.open_dwell=0.
    def snap(self,t):
        self.item='pending_open';self.grip_since=None;self.open_since=None;self.last_state_t=t;self.snap_at=t
    def state(self,probabilities,t):
        if self.item=='pending_open' and self.snap_at is not None and t-self.snap_at>2:self.item='none'
        if self.last_state_t is not None and (t<self.last_state_t or t-self.last_state_t>.2):self.grip_since=None;self.open_since=None
        self.last_state_t=t
        if probabilities.get('fist',0)>=self.grip_threshold:
            if self.grip_since is None:self.grip_since=t
            if t-self.grip_since>=self.grip_dwell:self.item='sword'
        else:
            self.grip_since=None
            if probabilities.get('open',0)>=.85:
                if self.open_since is None:self.open_since=t
                if self.item=='pending_open' and t-self.open_since>=self.open_dwell:self.item='fireball'
            else:self.open_since=None
            if self.item=='sword' and probabilities.get('open',0)>=.85:self.item='none'
        return self.item
    def status(self,fresh):
        return {'item':self.item,'available':fresh,'grip_threshold':self.grip_threshold,
                'grip_dwell_seconds':self.grip_dwell,'provisional':True,
                'open_dwell_seconds':self.open_dwell,'pending_open_timeout_seconds':2,
                'note':'Provisional classifier evidence: snap then open equips Fireball; confirmed grip selects Sword. Unknown is not grip; open/uncertain readings preserve an equipped Fireball.'}
