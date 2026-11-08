"""Prompted spell and open-hand shield effort collection, not a trained force estimator."""
import hashlib
import random
from .common import write_json
from .signal_check import SignalCheck


PROTOCOL = 'spells-open-shield-effort-v3'
LABEL_FILE = 'gesture-trials-v3.json'


def protocol(session_id):
    conditions = []
    for effort in ('light', 'medium', 'firm'):
        for movement in ('center', 'left', 'right'):
            position = {'center': 'in front of you', 'left': 'slightly to your left',
                        'right': 'slightly to your right'}[movement]
            conditions.append({'condition': f'shield-{effort}-{movement}', 'spell': 'shield',
                'effort': effort, 'movement': movement, 'hand_state': 'open',
                'orientation': 'fingers_up_palm_out', 'title': f'Shield · {effort} tension · {movement}',
                'instruction': f'Before recording, extend your right arm {position}, open your hand, point your fingers up and face your palm outward toward the opponent. Tense your forearm with {effort} effort while keeping your fingers open. Press Start Record and hold the pose and effort for about 5 seconds, then Stop. No thrust or jerk. Firm means comfortable effort, not a maximum squeeze.'})
    for angle in ('thumb_up', 'palm_down', 'palm_up'):
        description = {'thumb_up':'thumb side facing up', 'palm_down':'knuckles facing up',
                       'palm_up':'knuckles facing down'}[angle]
        conditions.append({'condition': 'sword-'+angle, 'spell':'sword', 'effort':'comfortable',
            'movement':'hold', 'hand_state':'fist', 'orientation':angle,
            'title':'Sword · fist · '+angle.replace('_',' '),
            'instruction':f'Before recording, close your right fist comfortably with {description}. Press Start Record and keep it closed for about 5 seconds, then Stop. No hip position or drawing motion. Change arm position between rounds; keep this trial steady.'})
    conditions += [
        {'condition':'rest','spell':'none','effort':'relaxed','movement':'hold','hand_state':'none',
         'title':'Relax your right hand','instruction':'Before recording, rest your forearm and let your fingers relax naturally. Press Start Record, stay relaxed for about 5 seconds, then Stop.'},
        {'condition':'snap','spell':'fireball','effort':'unspecified','movement':'snap','hand_state':'unlabeled',
         'title':'Fireball · middle finger/thumb snaps','instruction':'Start relaxed. Press Start Record, wait one second, then make 2–3 separate middle-finger/thumb snaps during the recording. Relax between snaps. Press Stop after about 5 seconds. Do not throw. Exact snap times must be reviewed later; the whole clip is not labeled as one snap.'},
        {'condition':'pinch','spell':'none','effort':'unspecified','movement':'pinch','hand_state':'unlabeled',
         'title':'Comparison · touch without snapping','instruction':'Press Start Record, then gently touch your middle finger and thumb together and release 2–3 times without snapping. Stop after about 5 seconds. These are confusing non-snap examples.'},
        {'condition':'ordinary','spell':'none','effort':'unspecified','movement':'ordinary','hand_state':'unlabeled',
         'title':'Comparison · ordinary hand movement','instruction':'Press Start Record, then gently wiggle your fingers and move your wrist naturally for about 5 seconds. Avoid snapping, holding a fist or making the shield pose. Press Stop.'},
    ]
    rng = random.Random(int.from_bytes(hashlib.sha256(session_id.encode()).digest()[:8], 'big'))
    trials = []
    for repetition in range(1, 4):
        block = conditions.copy(); rng.shuffle(block)
        block = [c for c in block if c['condition']=='rest'] + [c for c in block if c['condition']!='rest']
        for condition in block:
            trials.append({**condition, 'id': f"r{repetition}-{condition['condition']}", 'repetition': repetition,
                           'target_seconds': 5, 'minimum_seconds': 3, 'rest_seconds': 5})
    return trials


class ShieldTraining(SignalCheck):
    def __init__(self, session, trials=None, protocol_id=PROTOCOL, filename=LABEL_FILE):
        self.protocol_id = protocol_id
        self.trials = protocol(session.meta['id']) if trials is None else trials
        self.by_id = {t['id']: t for t in self.trials}
        super().__init__(session, [(t['id'], t['title'], t['instruction']) for t in self.trials], filename)

    def status(self):
        with self.lock:
            confirmed = {r['motion'] for r in self.results if r.get('confirmed') is True}
            pending = next((r for r in reversed(self.results) if r['received'] and r.get('confirmed') is None), None)
            next_trial = next((t for t in self.trials if t['id'] not in confirmed), None)
            trial = self.by_id[self.active['motion']] if self.active else self.by_id[pending['motion']] if pending else next_trial
            return {'schema': 1, 'protocol': self.protocol_id, 'session_id': self.session.meta['id'],
                    'subject': self.session.meta['subject'], 'side': 'right', 'stream_file': 'streams.jsonl',
                    'time_basis': 'session-relative Mac monotonic seconds; boundaries use received timestamps',
                    'reported_effort_is_not_measured_force': True, 'effort_model_trained': False,
                    'trials': self.trials, 'current': trial, 'active': dict(self.active) if self.active else None,
                    'pending': pending, 'completed': len(confirmed), 'total': len(self.trials), 'results': list(self.results)}

    def start(self, motion):
        with self.lock:
            state = self.status()
            if state['pending']:
                raise ValueError('Confirm or retry the received recording first')
            if not state['current'] or motion != state['current']['id']:
                raise ValueError('Record the current prompted trial')
            result = super().start(motion)
            self.active.update({'quest_frames': 0, 'quest_valid_frames': 0, 'quest_first': None,
                                'quest_last': None, 'quest_max_gap': 0., 'quest_frame_id': None,
                                'quest_frame_changed': False, 'quest_synced_frames': 0,
                                'emg_first_uptime': None, 'emg_last_uptime': None})
            return dict(self.active)

    def observe(self, row):
        with self.lock:
            super().observe(row)
            if self.active and row['received'] >= self.active['start']:
                uptime = row.get('source_uptime')
                if uptime is not None:
                    relative = uptime - self.session.meta['origin_monotonic']
                    if self.active['emg_first_uptime'] is None:
                        self.active['emg_first_uptime'] = relative
                    self.active['emg_last_uptime'] = relative

    def observe_pose(self, row):
        with self.lock:
            a = self.active
            if not a or row['received'] < a['start']:
                return
            a['quest_frames'] += 1
            pose = row['pose']
            if not (pose['hand']['valid'] and pose['chest']['valid'] and
                    pose['hand']['confidence'] >= .5 and pose['chest']['confidence'] >= .5):
                return
            frame = pose['frame_id']
            if a['quest_frame_id'] is not None and a['quest_frame_id'] != frame:
                a['quest_frame_changed'] = True
            a['quest_frame_id'] = frame
            a['quest_valid_frames'] += 1
            a['quest_synced_frames'] += int(row.get('timing') == 'clock_offset_estimate')
            if a['quest_first'] is None:
                a['quest_first'] = row['received']
            if a['quest_last'] is not None:
                a['quest_max_gap'] = max(a['quest_max_gap'], row['received'] - a['quest_last'])
            a['quest_last'] = row['received']

    def decorate_result(self, result):
        t = self.by_id[result['motion']]
        duration = result['end'] - result['start']
        if result['received'] and duration < t['minimum_seconds']:
            result.update(received=False, message='Too short for a training trial. Record about 5 seconds and try again.')
        # Pairing requires valid pose coverage and synchronized source timing, not just a plugged-in headset.
        pose_ok = (result['quest_valid_frames'] >= max(20, duration*20) and
                   result['quest_first'] is not None and result['quest_first']-result['start'] <= .25 and
                   result['end']-result['quest_last'] <= .25 and result['quest_max_gap'] <= .2 and
                   not result['quest_frame_changed'] and
                   result['quest_valid_frames'] >= .8*result['quest_frames'])
        emg_clock_ok = (result['emg_first_uptime'] is not None and
                        abs(result['emg_first_uptime']-result['start']) <= .25 and
                        abs(result['emg_last_uptime']-result['end']) <= .25)
        sync_ok = pose_ok and result['quest_synced_frames'] == result['quest_valid_frames'] and emg_clock_ok
        capture_mode = 'paired' if sync_ok else 'paired_incomplete' if result['quest_frames'] else 'emg_only'
        return {**result, 'protocol': self.protocol_id, 'condition': t['condition'],
                'intended_spell': t['spell'], 'requires_event_review': t['condition'] == 'snap',
                'intended_effort': t['effort'], 'intended_movement': t['movement'], 'hand_state': t['hand_state'],
                'intended_orientation': t.get('orientation', 'unspecified'),
                'orientation_verified_by_tracking': False,
                'repetition': t['repetition'], 'confirmed': None, 'capture_mode': capture_mode,
                'needs_paired_quest': not bool(sync_ok), 'quest_tracking_ok': bool(pose_ok),
                'paired_timing_ok': bool(sync_ok), 'reported_effort_is_not_measured_force': True}

    def confirm(self, result_id, accepted):
        if type(accepted) is not bool:
            raise ValueError('Confirmation must be true or false')
        with self.lock:
            row = next((r for r in self.results if r['id'] == result_id), None)
            if row is None or not row['received']:
                raise ValueError('Only a received trial can be confirmed')
            if row.get('confirmed') is not None:
                if row['confirmed'] == accepted:
                    return dict(row)  # Safe retry after a lost response.
                raise ValueError('This trial was already reviewed')
            replacement = {**row, 'confirmed': accepted, 'confirmed_at': self.session.now(),
                           'confirmation_source': 'participant_report'}
            results = [replacement if r['id'] == result_id else r for r in self.results]
            write_json(self.result_path, results)
            self.results = results
            return replacement
