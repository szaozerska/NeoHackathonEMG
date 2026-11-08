"""Initial reception checks, deliberately separate from training annotations."""
import threading
import uuid
import numpy as np
from .common import read_json, write_json

MOTIONS = (
    ('rest', 'Relax your right hand', 'Keep your fingers loose and rest your arm for about 3 seconds.'),
    ('shield', 'Hold your shield', 'Before recording, extend your right arm, fingers up and open palm facing outward. Press Start Record and hold for 3 seconds. No thrust.'),
    ('sword', 'Summon your sword', 'Before recording, close your right fist at any comfortable angle. Press Start Record and hold it closed for 3 seconds. No drawing motion.'),
    ('release', 'Dismiss your sword', 'Start with your right fist closed. Press Start Record, open your hand, and hold it open for 3 seconds.'),
    ('snap', 'Create a fireball', 'Press Start Record, then snap your right middle finger against your thumb 2–3 times.'),
    ('throw', 'Throw your fireball', 'Press Start Record, then make a forward throwing motion with your right hand. Opening your hand is optional.'),
)

class SignalCheck:
    def __init__(self, session, motions=MOTIONS, filename='signal-checks.json'):
        self.session = session
        self.motions = motions
        self.lock = threading.RLock()
        self.active = None
        path = self.result_path = session.directory / filename
        self.results = read_json(path) if path.exists() else []

    def status(self):
        with self.lock:
            return {'motions': [{'id': key, 'title': title, 'instruction': text} for key, title, text in self.motions],
                    'active': dict(self.active) if self.active else None, 'results': list(self.results)}

    def start(self, motion):
        with self.lock:
            if motion not in {m[0] for m in self.motions}:
                raise ValueError('Unknown motion')
            if self.active:
                raise ValueError('Stop the current recording first')
            self.active = {'id': uuid.uuid4().hex, 'motion': motion, 'start': self.session.now(),
                           'samples': 0, 'batches': 0, 'last': None, 'varying': False, 'gaps': 0,
                           'last_seq': None}
            return dict(self.active)

    def observe(self, row):
        with self.lock:
            a = self.active
            if not a or row['received'] < a['start']:
                return
            samples = np.asarray(row['samples'])
            a['samples'] += len(samples)
            a['batches'] += 1
            a['last'] = row['received']
            a['varying'] |= bool(np.any(np.std(samples, axis=0) > 0))
            # A discontinuity preceding the first batch does not damage this capture.
            if a['batches'] > 1:
                seq = row.get('source_seq')
                # Bluetooth delivery jitter can flag timeline gaps without losing samples.
                missing = (seq != a['last_seq'] + 1 if seq is not None and a['last_seq'] is not None
                           else row.get('gap', False))
                a['gaps'] += int(missing)
            a['last_seq'] = row.get('source_seq')

    def finish(self):
        with self.lock:
            if not self.active:
                raise ValueError('Press Start Record first')
            a = dict(self.active)
            end = self.session.now()
            duration = end - a['start']
            coverage = a['samples'] / (2048 * max(duration, .001))
            reason = ''
            if not a['samples']:
                reason = 'No EMG received. Connect the Kinesis raw recording, then try again.'
            elif duration < 1 or a['samples'] < 1024:
                reason = 'Recording too short. Try again for about 3 seconds.'
            elif end - a['last'] > .5 or coverage < .5 or a['gaps']:
                reason = 'EMG was interrupted. Check the band connection and try again.'
            elif not a['varying']:
                reason = 'The signal was flat. Check band contact and try again.'
            elif self.session.meta.get('synthetic'):
                reason = 'Synthetic data cannot confirm your band connection.'
            result = {**a, 'end': end, 'coverage': coverage, 'received': not bool(reason),
                      'message': reason or 'Received.', 'verified_gesture': False}
            result = self.decorate_result(result)
            results = self.results + [result]
            write_json(self.result_path, results)
            self.results = results
            self.active = None
            return result

    def decorate_result(self, result):
        return result
