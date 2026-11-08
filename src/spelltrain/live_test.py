"""Read-only EMG model tester. Does not create or modify training sessions."""
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
import json
import math
import threading
import time
import secrets
import re
from urllib.parse import urlparse,parse_qs
from .camera_reference import CameraReference,camera_posture,review_capture

from .feeds import tail_kinesis
from .gestures import GesturePredictor
from .decisions import DecisionMemory,EffortMemory
from .live_capture import LiveCapture
from .intent import FireballOption
from .intent_collection import IntentCollection,EquipmentPreview
from .sensor_timing import SensorTiming


class LiveTester:
    def __init__(self,artifact,band_file,clock=time.monotonic,predictor=None,capture_root=None,display_policy=None,auto_source=False):
        self.artifact=artifact
        self.model_version=artifact.get('report',{}).get('model_version') or ('v4' if artifact.get('report',{}).get('task')=='reference_reviewed_gesture_update' else 'unversioned')
        self.display_policy=display_policy or ('v4_feedback' if self.model_version=='v4' else 'equipment')
        if self.display_policy not in ('v4_feedback','equipment'):raise ValueError('Unknown display policy')
        self.snap_policy='brief_snap_feedback_1.25_seconds' if self.display_policy=='v4_feedback' else 'snap_equips_fist_or_shield_cancels_quest_commits'
        self.camera_required=self.display_policy!='v4_feedback'
        self.band_file=str(Path(band_file).resolve())
        self.clock=clock;self.origin=clock()
        self.predictor=GesturePredictor(artifact,diagnostics=True) if predictor is None else predictor
        self.stop=threading.Event();self.lock=threading.RLock()
        self.threads=[];self.server=None
        self.last_packet=self.last_state=self.last_effort=self.last_snap=-float('inf')
        self.label='none';self.effort=None;self.confidence=0.
        self.fireballs=0;self.packets=0;self.previous_seq=None
        self.errors=deque(maxlen=3)
        self.decisions=DecisionMemory();self.effort_memory=EffortMemory()
        self.state_updates=0
        self.capture_root=Path(capture_root) if capture_root else Path(self.band_file).parent.parent/'live-corrections'
        self.capture=None;self.last_capture=None
        self.pre_roll=deque(maxlen=512);self.recent=deque(maxlen=400)
        self.csrf=secrets.token_urlsafe(24)
        self.option=FireballOption();self.ready_count=0;self.last_raw_probabilities={}
        self.camera=None;self.camera_status=None
        self.vision_assets=Path(__file__).resolve().parents[2]/'data/support/vision'
        self.input_generation=None
        self.input_kind='file'
        self.live_input=None
        self.collection=None;self.last_collection_report=None
        self.contribution_root=Path(__file__).resolve().parents[2]/'Micah data contribution'
        self.equipment_preview=EquipmentPreview()
        self.band_context={};self.band_event_counts={};self.target_hand='Right'
        self.sensor_timing=SensorTiming()
        if auto_source:
            from .live_source import LiveInput
            state=Path(__file__).resolve().parents[2]/'.local/kinesis-stream-url'
            self.live_input=LiveInput(self.band_file,self.packet,self.error,self.source_changed,state,self.band_event)

    def band_event(self,kind,value):
        if kind=='emg':return
        if kind not in ('hello','status','emg_configuration','gyro','orientation','gesture'):return
        host=value.get('host_time_s')
        if not isinstance(host,(int,float)) or not math.isfinite(host) or abs(self.clock()-host)>2:return
        if value.get('type')!=kind or value.get('schema_version')!=1:return
        with self.lock:
            payload=value.get('payload',{})
            status=payload.get('status',{}) if kind=='hello' else payload if kind=='status' else {}
            self.sensor_timing.identity(value.get('stream_session_id'),status.get('band_connection_id'),status.get('hand'))
            timing=self.sensor_timing.observe(kind,value.get('band_timestamp_us'),host,self.clock(),payload.get('values')) if kind in ('gyro','orientation','gesture') else None
            self.band_context[kind]={'host_uptime':host,'event':value}
            self.band_event_counts[kind]=self.band_event_counts.get(kind,0)+1
            if self.capture:self.capture.append('band_'+kind,host,event=value,timing=timing)
            if self.collection:self.collection.context(kind,value,host)

    def collection_action(self,action,value):
        with self.lock:
            if action=='start':
                if self.capture:raise ValueError('Finish the active recording before starting a guided session.')
                # Validate before creating a capture directory.
                wearing=value.get('wearing_session','')
                if not isinstance(wearing,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',wearing):raise ValueError('Enter a wearing-session ID.')
                if value.get('role','train') not in ('train','evaluation') or value.get('hand','Right') not in ('Right','Left') or value.get('focus','full') not in ('full','live_intent','intent','snaps','controls','states','transitions'):raise ValueError('Invalid role, hand or focus')
                contribution=value.get('profile')=='micah_emg'
                if contribution:
                    telemetry=self.sensor_timing.status(self.clock());rates=telemetry['delivered_sensor_hz']
                    motion_fresh=all(kind in self.band_context and self.clock()-self.band_context[kind]['host_uptime']<1.5 for kind in ('gyro','orientation'))
                    if not motion_fresh or telemetry['forearm'] is None or not all(rates.get(kind) for kind in ('gyro','orientation')):
                        raise ValueError('Connect Kinesis local sensor feed and select the band wrist; fresh gyro/orientation are required for synchronized contributions.')
                guard=0. if contribution else float(value.get('interaction_guard',1.))
                if not math.isfinite(guard) or not (0 if contribution else .5)<=guard<=3 or value.get('initial_intent','non_intended') not in ('intended','non_intended'):raise ValueError('Invalid click guard or initial toggle state')
                if contribution and (value.get('focus')!='live_intent' or value.get('initial_intent')!='non_intended'):
                    raise ValueError('Micah EMG sessions start in non-intended mode.')
                self.start_capture(root=self.contribution_root if contribution else None,emg_only=contribution);self.target_hand=value.get('hand','Right')
                self.collection=IntentCollection(self.capture,self.clock,wearing,value.get('role','train'),self.target_hand,value.get('focus','full'),value.get('initial_intent','non_intended'),guard,defer_cleanup=contribution)
                if contribution:
                    self.capture.meta.update(kind='micah_emg_intent_contribution',contributor='Micah',
                        collection_protocol='spacebar-held-motion-intent-v1',camera_policy='disabled',
                        input_modalities=['emg'],recorded_context=['available_gyro','available_orientation','available_band_events'],classification_policy='participant_motion_selection_only_no_model_predictions',
                        timing_policy='Native band microseconds, Kinesis receipt uptime, Python receipt uptime and browser alignment all retained. Arrival delay and forearm angles are estimates in the documented Kinesis frame.',
                        postprocessing_required=True,cleanup_applied=False,
                        browser_clock_alignment_at_start=value.get('clock_alignment'),
                        host_monotonic_clock=time.get_clock_info('monotonic').implementation,
                        sensor_timing_at_start=self.sensor_timing.status(self.clock()),
                        label_policy='Immediate participant reports: Space down marks intended, Space up marks non-intended. No keyboard-edge clipping or fixed minimum interval. Preserve baseline context, key times and sensor coverage for later cleanup. Motion/effort are participant selections, not verified physical onsets or force.')
                    self.capture.meta.pop('equipment_rule',None)
                    self.collection._save()
                return {'collection':self.collection.status(),'recording':self.capture.status()}
            if not self.collection or not self.capture:raise ValueError('Start a guided session first.')
            if action=='select-motion':return self.collection.select_motion(value['motion'],value.get('effort'))
            if action in ('intent-mark','interaction'):
                alignment=value.get('alignment',{})
                host=float(value['client_t'])+float(alignment['host_offset_seconds'])
                uncertainty=float(alignment['uncertainty_seconds'])
                if action=='intent-mark':return self.collection.mark_intent(value['label'],host,uncertainty,{**alignment,'client_event_t':value['client_t'],'mapped_host_event_uptime':host,'server_received_host_uptime':self.clock()})
                self.collection.interaction(host,uncertainty,value.get('kind','button'));return {'saved':True}
            if action=='clock-sync':
                calibration=value['alignment'];host=float(calibration['client_sync_t'])+float(calibration['host_offset_seconds'])
                uncertainty=float(calibration['uncertainty_seconds'])
                if not math.isfinite(host) or abs(self.clock()-host)>5 or not math.isfinite(uncertainty) or not 0<=uncertainty<=.5:raise ValueError('Invalid clock calibration')
                self.capture.append('clock_sync',self.clock(),alignment=calibration)
                return {'saved':True}
            if action=='trial':return self.collection.start_trial(self.status()['connected'])
            if action=='confirm':return self.collection.confirm(value)
            if action=='flag':return self.collection.flag(value['kind'],value.get('note',''))
            if action=='finish':
                if self.camera and not self.camera.complete:raise ValueError('Save the camera reference before finishing.')
                collection=self.collection;collection.finish();recording=self.stop_capture()
                self.last_collection_report=collection.finalize();self.collection=None
                return {'recording':recording,'report':self.last_collection_report}
            raise ValueError('Unknown collection action')

    def emg_contribution(self):
        return bool(self.capture and self.capture.meta.get('recording_profile')=='micah_emg')

    def source_changed(self,kind,path):
        with self.lock:
            self.sensor_timing.reset()
            self.input_kind=kind
            self.band_context={}
            if path:self.band_file=path
            self.last_packet=self.last_state=self.last_effort=self.last_snap=-float('inf')
            self.label='none';self.effort=None
            self.decisions.reset();self.effort_memory.reset();self.option.reset()

    def error(self,message):
        with self.lock:
            if not self.errors or self.errors[-1]!=message:self.errors.append(message)

    def packet(self,packet):
        now=self.clock()
        # Reject old/copy-pasted captures rather than displaying replay as live recognition.
        if 'source_uptime' in packet and abs(now-float(packet['source_uptime']))>2.:
            self.error('The raw recording is stale. Start a new live recording in Kinesis.')
            return
        row={'kind':'emg','received':now-self.origin,'t':now-self.origin,**packet}
        with self.lock:
            self.sensor_timing.identity(packet.get('stream_session'))
            row['timing']=self.sensor_timing.observe('emg',packet.get('source_t'),packet.get('source_uptime'),now)
            generation=packet.get('input_generation')
            if generation!=self.input_generation:
                if self.input_generation is not None and self.collection and self.collection.current:
                    self.collection.current['source_changes']=self.collection.current.get('source_changes',0)+1
                if self.capture:self.capture.append('stream_reset',now,reason='input_source_changed')
                self.input_generation=generation
                if isinstance(self.predictor,GesturePredictor):
                    self.predictor=GesturePredictor(self.artifact,diagnostics=True)
                self.previous_seq=None
                self.label='none';self.effort=None
                self.last_state=self.last_effort=self.last_snap=-float('inf')
                self.decisions.reset();self.effort_memory.reset();self.option.reset()
                self.equipment_preview.grip_since=None;self.equipment_preview.open_since=None;self.equipment_preview.last_state_t=None
            seq=packet.get('source_seq')
            if self.previous_seq is not None and seq!=self.previous_seq+1:
                if self.capture:self.capture.append('stream_reset',now,reason='source_sequence_gap',previous_seq=self.previous_seq,next_seq=seq)
                self.label='none';self.effort=None
                self.last_state=self.last_effort=self.last_snap=-float('inf')
                self.decisions.reset();self.effort_memory.reset();self.option.reset()

            if now-self.last_packet>1.25:
                if self.capture:self.capture.append('stream_reset',now,reason='input_silence',seconds=now-self.last_packet)
                self.option.reset()
            self.previous_seq=seq
            self.pre_roll.append((now,dict(row)))
            while self.pre_roll and now-self.pre_roll[0][0]>2.:self.pre_roll.popleft()
            if self.capture:self.capture.append('emg',now,packet=row)
            predictions=[] if self.emg_contribution() else self.predictor.feed(row)
            self.last_packet=now;self.packets+=1
            self.errors.clear()
            if self.collection:self.collection.packet({**packet,'timing':row.get('timing')})
            for prediction in predictions:
                if self.capture:self.capture.append('prediction',now,prediction=prediction)
                kind=prediction['kind']
                if kind=='state':
                    probabilities=prediction.get('probabilities')
                    if probabilities is None:
                        # Compatibility for simpler predictors/tests; real bundles provide raw probabilities.
                        confidence=float(prediction['confidence'])
                        probabilities={k:(confidence if k==prediction['label'] else (1-confidence)/2)
                                       for k in ('none','fist','open')}
                    self.last_raw_probabilities=probabilities
                    self.equipment_preview.state(probabilities,prediction.get('source_t',now))
                    source_t=prediction.get('source_t',now-self.origin)
                    self.label=self.decisions.feed(probabilities,source_t)
                    intent_events=self.option.state(self.label,source_t,fist_confirmed=probabilities.get('fist',0)>=.6,open_confirmed=probabilities.get('open',0)>=.6) if self.display_policy=='equipment' else []
                    self.intent_events(intent_events,now)
                    self.last_state=now;self.state_updates+=1
                    if self.label!='open':self.effort_memory.reset()
                    self.confidence=float(prediction['confidence'])

                elif kind=='effort':
                    probabilities=prediction['probabilities']
                    index=float(prediction['effort_index'])
                    if self.label=='open' and math.isfinite(index) and probabilities:
                        self.effort=self.effort_memory.feed(probabilities,prediction.get('source_t',now-self.origin))
                        self.last_effort=now
                elif kind=='snap':
                    self.equipment_preview.snap(prediction.get('source_t',now))
                    if self.collection:self.collection.predicted_snap()
                    self.last_snap=now;self.fireballs+=1
                    self.recent.append({'t':now-self.origin,'event':'snap_candidate','score':prediction.get('confidence')})
                    events=self.option.snap(prediction.get('source_t',now-self.origin),prediction['event_id'],
                        fist_confirmed=self.label=='fist' and self.last_raw_probabilities.get('fist',0)>=.6) if self.display_policy=='equipment' else []
                    self.intent_events(events,now)
                if kind in ('state','snap'):
                    decision={'t':now-self.origin,'gesture':self.current_gesture(now)[0],
                              'state':self.label,'effort':self.effort,'raw':prediction,
                              'fireball_phase':self.option.phase,'committed':False,
                              'decision_memory':{'label':self.decisions.label,'history':list(self.decisions.history),'smoothed_probabilities':self.decisions.probabilities,'pending':self.decisions.pending,'pending_since':self.decisions.pending_since,'last_support':self.decisions.last_support},'raw_state_probabilities':self.last_raw_probabilities}
                    self.recent.append(decision)
                    if self.capture:self.capture.append('decision',now,decision=decision)

    def intent_events(self,events,now):
        for event in events:
            if event['event']=='fireball_equipped':self.ready_count+=1
            row={'t':now-self.origin,'intent':event,'fireball_phase':self.option.phase,'committed':False}
            self.recent.append(row)
            if self.capture:self.capture.append('spell_state',now,transition=row)

    def current_gesture(self,now):
        fresh=now-self.last_packet<1.25 and not self.stop.is_set()
        if fresh and self.display_policy=='v4_feedback' and now-self.last_snap<1.25:return 'Fireball',None
        if fresh and now-self.last_state<1.25:
            if self.display_policy=='v4_feedback':
                if self.label=='fist':return 'Sword',None
                if self.label=='open':return 'Shield',self.effort if now-self.last_effort<1.25 else None
                return 'Nothing',None
            if self.option.phase=='ready':return 'Fireball equipped',None
            if self.label=='fist':return 'Sword equipped',None
            if self.label=='open':return 'Shield',self.effort if now-self.last_effort<1.25 else None
        return 'Nothing',None

    def start_capture(self,root=None,emg_only=False):
        with self.lock:
            if self.capture:return self.capture.status()
            if not self.status()['connected']:raise ValueError('Wait for live EMG before recording')
            info={'version':self.model_version,'task':self.artifact.get('report',{}).get('task'),
                  'frozen_parameters_sha256':self.artifact.get('report',{}).get('frozen_before_test_sha256'),
                  'decision_memory':True,'snap_policy':self.snap_policy,'display_policy':self.display_policy,
                  'signal':self.artifact.get('signal'),
                  'readiness':{'snap_equips_immediately':self.display_policy=='equipment','ready_expires':False,'fist_cancels':self.display_policy=='equipment','confirmed_shield_cancels':self.display_policy=='equipment','commit_available':False},
                  'snap_window_scores_recorded':True,
                  'memory':{'tau':self.decisions.tau,'history_seconds':self.decisions.history_seconds,'freshness_seconds':1.25}}
            self.camera=None
            if emg_only:info={'signal':self.artifact.get('signal'),'version':'no-model','inference_enabled':False}
            self.capture=LiveCapture(root or self.capture_root,self.clock,info)
            if emg_only:self.capture.meta['recording_profile']='micah_emg'
            for host_t,row in self.pre_roll:self.capture.append('emg',host_t,packet=row,pre_roll=True)
            for decision in ([] if emg_only else self.recent):
                host_t=self.origin+decision['t']
                if self.clock()-host_t<=2.:self.capture.append('decision',host_t,decision=decision,pre_roll=True)
            return self.capture.status()

    def stop_capture(self):
        with self.lock:
            if self.capture:
                if self.camera and not self.camera.complete:raise ValueError('Save or explicitly abandon camera upload before stopping EMG')
                if self.emg_contribution():
                    self.capture.meta['sensor_timing_at_stop']=self.sensor_timing.status(self.clock())
                self.last_capture=self.capture.finish()
                if not self.emg_contribution():review_capture(self.capture.directory)
                self.capture=None
            return self.last_capture

    def mark_correction(self,gesture,timing='after'):
        with self.lock:
            if not self.capture:raise ValueError('Press Record before marking a correction')
            marker=self.capture.mark(gesture,self.current_gesture(self.clock())[0],self.clock(),timing)
            self.recent.append({'t':self.clock()-self.origin,'event':'correction','correction':marker})
            return marker

    def status(self):
        with self.lock:
            now=self.clock()
            # The current Kinesis raw-file writer delivers ~0.5s bursts. Its normal
            # inter-burst silence must not be mistaken for missing model evidence.
            fresh=now-self.last_packet<1.25 and not self.stop.is_set()
            state_fresh=fresh and now-self.last_state<1.25
            gesture,effort=self.current_gesture(now)
            return {'app':'live-model-tester','gesture':gesture,'effort':effort,
                    'connected':fresh,'warming_up':fresh and not state_fresh,
                    'fireballs':self.fireballs,'snap_candidates':self.fireballs,'fireball_readiness_count':self.ready_count,
                    'fireballs_committed':0,'fireball_phase':('disabled_in_feedback_mode' if self.display_policy=='v4_feedback' else self.option.phase) if fresh else 'unavailable',
                    'commit_available':False,'commit_requires':'Quest forward throw after snap and open hand',
                    'equipment':{'Sword':'sword','Sword equipped':'sword','Fireball equipped':'fireball','Shield':'shield_candidate'}.get(gesture,'none'),
                    'packets':self.packets,'errors':list(self.errors),
                    'model_version':self.model_version,'model_task':self.artifact.get('report',{}).get('task'),
                    'band_file':self.band_file,'input_kind':self.input_kind,'auto_source':self.live_input is not None,'shield_pose_verified':False,'interaction_revision':('v4-baseline-feedback' if self.display_policy=='v4_feedback' else 'shield-cancel-1'),
                    'decision_memory':True,'state_updates':self.state_updates,
                    'snap_arbitration':False,'checking_snap':False,'snap_policy':self.snap_policy,'display_policy':self.display_policy,
                    'recording':self.capture.status() if self.capture else self.last_capture,
                    'camera_observer':self.camera_status,'camera_required_for_recording':self.camera_required,
                    'online_learning':False,
                    'collection':self.collection.status() if self.collection else None,
                    'recording_profile':self.capture.meta.get('recording_profile') if self.capture else None,
                    'collection_report':self.last_collection_report,
                    'equipment_preview':self.equipment_preview.status(fresh),
                    'band_context':{kind:{'age_seconds':max(0,now-value['host_uptime']),'event':value['event']} for kind,value in self.band_context.items()},
                    'band_event_counts':dict(self.band_event_counts),
                    'sensor_timing':self.sensor_timing.status(now),
                    'packet_age_seconds':now-self.last_packet if self.packets and math.isfinite(self.last_packet) else None,
                    'session':{'id':'live-model-test','subject':self.artifact.get('report',{}).get('subject','player-a'),
                               'mode':'tester','band_file':self.band_file}}

    def switch_to_shield(self):
        with self.lock:
            now=self.clock()
            if self.display_policy!='equipment':raise ValueError('Equipment switching is disabled in v4 feedback mode')
            if not self.status()['connected'] or self.label!='open' or self.last_raw_probabilities.get('open',0)<.6:
                raise ValueError('Hold your open shield hand while switching to Shield')
            # Explicit participant command, not a gesture prediction or a training label.
            t=self.decisions.last_t
            events=self.option.shield(t,confirmed=True)
            self.intent_events(events,now)
            row={'event':'manual_equipment_command','equipment':'shield','source':'participant_command','verified_gesture':False}
            if self.capture:self.capture.append('equipment_command',now,command=row)
            return {'switched':bool(events),'gesture':self.current_gesture(now)[0]}

    def _active_camera_capture(self,capture_id):
        if not self.capture or self.capture.closed or self.capture.directory.name!=capture_id:
            raise ValueError('Camera capture ID does not match the active recording')
        return self.capture

    def camera_observation(self,value):
        if self.emg_contribution():raise ValueError('Camera is disabled for Micah EMG-only contributions.')
        now=self.clock();observation=value['observation'];alignment=value['alignment']
        client_t=float(observation['client_t']);offset=float(alignment['host_offset_seconds'])
        uncertainty=float(alignment['uncertainty_seconds']);observed_host=client_t+offset
        if not all(math.isfinite(v) for v in (client_t,offset,uncertainty)) or not 0<=uncertainty<=2 or abs(now-observed_host)>5:
            raise ValueError('Camera clock alignment is stale; re-enable camera')
        if not isinstance(observation.get('hands'),list) or len(observation['hands'])>2:raise ValueError('Invalid camera hands')
        target=self.target_hand if self.capture else value.get('target_hand',self.target_hand)
        if target not in ('Right','Left'):raise ValueError('Invalid camera target hand')
        posture=camera_posture(observation,target_hand=target)
        row={**observation,'posture':posture,'alignment':alignment,'band_state_at_receipt':self.label,'band_equipment_at_receipt':self.current_gesture(now)[0],
             'received_host_uptime':now,'independently_reviewed':False,'reference_only':True}
        capture_id=value.get('capture_id')
        if capture_id:
            capture=self._active_camera_capture(capture_id)
            capture.append('camera_observation',observed_host,observation=row)
        self.camera_status={'posture':posture,'agreement':posture['label']==self.label,
                            'host_uptime':observed_host,'recording':bool(capture_id)}
        if self.collection:self.collection.context('camera',row,observed_host)
        return self.camera_status

    def camera_action(self,action,value):
        with self.lock:
            if self.emg_contribution():raise ValueError('Camera is disabled for Micah EMG-only contributions.')
            capture=self._active_camera_capture(value['capture_id'])
            if action=='start':
                if self.camera:raise ValueError('Camera reference already started')
                self.camera=CameraReference(capture,value['mime'],value['alignment'])
                manifest_path=self.vision_assets/'manifest.json'
                if manifest_path.exists():capture.meta['camera_observer_assets']=json.loads(manifest_path.read_text())
                capture.meta['camera_observer_policy']={'target_hand':'Right','inputs':'camera_landmarks_only','geometry':'four_PIP_angles_v1','automatic_ground_truth':False,'band_inference_inputs':'EMG_only'}
                capture.append('camera_event',self.clock(),event='reference_started',alignment=value['alignment'])
                return {'started':True}
            if action=='finish':
                if not self.camera:raise ValueError('Camera reference not started')
                return self.camera.finish(int(value['count']),float(value['ended_client_t']))
            if action=='abandon':
                capture.append('camera_event',self.clock(),event='reference_incomplete',reason=value.get('reason','explicit_abandon'))
                self.camera=None;return {'abandoned':True,'reference_complete':False}
            if action=='display':
                client_t=float(value['client_t']);offset=float(value['alignment']['host_offset_seconds'])
                observed_host=client_t+offset
                if not math.isfinite(observed_host) or abs(self.clock()-observed_host)>5:raise ValueError('Invalid display timestamp')
                capture.append('browser_display',observed_host,display=value['display'],received_host_uptime=self.clock(),alignment=value['alignment'])
                return {'saved':True}
            if action=='event':
                capture.append('camera_event',self.clock(),camera_event=value);return {'saved':True}
            raise ValueError('Unknown camera action')

    def start(self,port=8765,start_feed=True):
        tester=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):
                route=self.path.split('?',1)[0]
                if route in ('/','/contribute','/collect','/live'):
                    name='dashboard-live.html' if route=='/live' else 'dashboard-collect.html' if route=='/collect' else 'dashboard-contribute.html'
                    body=files('spelltrain').joinpath(name).read_text().replace('__CSRF__',tester.csrf).encode()
                    content_type='text/html; charset=utf-8'
                elif route in ('/camera-live.js','/camera-worker.js','/collection.js','/contribution.js'):
                    body=files('spelltrain').joinpath(route[1:]).read_bytes();content_type='text/javascript'
                elif route.startswith('/vision/'):
                    relative=route.removeprefix('/vision/')
                    path=(tester.vision_assets/relative).resolve()
                    if not path.is_relative_to(tester.vision_assets.resolve()) or not path.is_file():self.send_error(404);return
                    body=path.read_bytes();content_type='application/wasm' if path.suffix=='.wasm' else 'text/javascript' if path.suffix in ('.js','.mjs') else 'application/octet-stream'
                elif route=='/api/camera/reference':
                    query=parse_qs(urlparse(self.path).query);capture_id=query.get('capture_id',[''])[0]
                    if not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[a-f0-9]{8}',capture_id):self.send_error(400);return
                    directory=tester.capture_root/capture_id
                    try:
                        meta=json.loads((directory/'metadata.json').read_text());reference=meta['camera_reference']
                        path=(directory/reference['file']).resolve()
                        if not path.is_relative_to(directory.resolve()) or not reference['complete']:raise ValueError('Invalid reference')
                        size=path.stat().st_size;start,end=0,size-1;partial=False
                        if self.headers.get('Range'):
                            match=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers['Range'])
                            if not match:raise ValueError('Invalid range')
                            start=int(match[1]);end=min(size-1,int(match[2]) if match[2] else size-1);partial=True
                            if not 0<=start<=end<size:raise ValueError('Invalid range')
                    except (OSError,KeyError,ValueError):self.send_error(404);return
                    self.send_response(206 if partial else 200);self.send_header('Content-Type',reference['mime'])
                    self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
                    if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    with path.open('rb') as media:
                        media.seek(start);remaining=end-start+1
                        while remaining:
                            chunk=media.read(min(remaining,1024*1024))
                            if not chunk:break
                            self.wfile.write(chunk);remaining-=len(chunk)
                    return
                elif route=='/api/clock':
                    body=json.dumps({'host_uptime':tester.clock()}).encode();content_type='application/json'
                elif route=='/api/observe':
                    with tester.lock:
                        body=json.dumps({'status':tester.status(),'recent':list(tester.recent)},allow_nan=False).encode()
                    content_type='application/json'
                elif route=='/api/status':
                    body=json.dumps(tester.status(),allow_nan=False).encode();content_type='application/json'
                else:
                    self.send_error(404);return
                self.send_response(200)
                self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(len(body)))
                self.send_header('Cache-Control','no-store')
                self.end_headers();self.wfile.write(body)
            def do_POST(self):
                if self.headers.get('X-Session-Token')!=tester.csrf:
                    self.send_response(403);self.end_headers();self.wfile.write(b'{"error":"Refresh the tester to reconnect"}');return
                try:
                    route=urlparse(self.path)
                    if route.path=='/api/camera/chunk':
                        query=parse_qs(route.query);length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<=16*1024*1024:raise ValueError('Invalid camera chunk size')
                        payload=self.rfile.read(length)
                        if len(payload)!=length:raise ValueError('Incomplete camera chunk')
                        with tester.lock:
                            tester._active_camera_capture(query['capture_id'][0])
                            if not tester.camera:raise ValueError('Camera reference not started')
                            tester.camera.chunk(int(query['index'][0]),payload)
                        body=b'{"saved":true}';self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=65536:raise ValueError('Invalid request size')
                    value=json.loads(self.rfile.read(length))
                    if self.path.startswith('/api/collection/'):
                        result=tester.collection_action(self.path.rsplit('/',1)[1],value)
                    elif self.path=='/api/source/stream':
                        if tester.live_input is None:raise ValueError('Restart using Start Partner Bench to enable automatic input.')
                        tester.live_input.set_stream(value['url']);result={'connected':False,'connecting':True}
                    elif self.path=='/api/equipment/shield':result=tester.switch_to_shield()
                    elif self.path=='/api/camera/observations':
                        with tester.lock:result=tester.camera_observation(value)
                    elif self.path.startswith('/api/camera/'):result=tester.camera_action(self.path.rsplit('/',1)[1],value)
                    elif self.path=='/api/record/start':result=tester.start_capture()
                    elif self.path=='/api/record/stop':result=tester.stop_capture()
                    elif self.path=='/api/record/mark':result=tester.mark_correction(value['gesture'],value.get('timing','after'))
                    else:raise ValueError('Unknown recording action')
                    code=200
                except (ValueError,KeyError,TypeError,OSError) as exc:
                    result={'error':str(exc)};code=400
                body=json.dumps(result,allow_nan=False).encode()
                self.send_response(code);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
                self.end_headers();self.wfile.write(body)
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start();self.threads.append(thread)
        if start_feed:
            def feed():
                try:
                    if self.live_input:self.live_input.run(self.stop)
                    else:tail_kinesis(self.band_file,self.stop,self.packet,self.error)
                except Exception as exc:
                    self.error('Model input failed: '+type(exc).__name__)
                    self.stop.set()
            thread=threading.Thread(target=feed,daemon=True);thread.start();self.threads.append(thread)
        return self.server.server_address[1]

    def close(self):
        with self.lock:
            if self.collection:self.collection.finish()
            if self.capture:self.last_capture=self.capture.finish('app_closed');self.capture=None
            if self.collection:self.collection.finalize();self.collection=None
        self.stop.set()
        if self.server:self.server.shutdown();self.server.server_close()
        for thread in self.threads:thread.join(timeout=2)
