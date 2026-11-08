#!/usr/bin/env python3
"""Guided EMG-only collection: one separately confirmed action per short clip."""
import argparse
from collections import deque
import json
from pathlib import Path
import random
import threading
import time
from spelltrain.feeds import tail_kinesis
from spelltrain.live_capture import LiveCapture
from spelltrain.signals import DEFAULT_SIGNAL
from spelltrain.common import write_json
from spelltrain.effort import _hash

SNAP_VARIANTS = [
    'One SOFT snap with MINIMAL wrist rotation',
    'One comfortable FIRM snap with MINIMAL wrist rotation',
    'One SOFT snap with your NATURAL wrist rotation',
    'One comfortable FIRM snap with your NATURAL wrist rotation',
    'One SOFT snap with EXAGGERATED comfortable wrist rotation',
    'One comfortable FIRM snap with EXAGGERATED comfortable wrist rotation',
]
NEGATIVE_VARIANTS = [
    'Rotate the wrist gently WITHOUT snapping',
    'Rotate the wrist more than usual WITHOUT snapping',
    'Touch middle finger and thumb, then release WITHOUT snapping',
    'Close and open your fist WITHOUT snapping',
    'Wiggle/curl your fingers WITHOUT snapping',
    'Reach and return naturally WITHOUT snapping',
]


def plan(kind, repetitions, seed=7, instruction=None, event=False):
    variants = SNAP_VARIANTS if kind == 'snap' else NEGATIVE_VARIANTS if kind == 'negative' else [instruction] if event else [
        instruction or {'fist': 'Hold a comfortable closed fist', 'open': 'Hold your deliberate open shield hand',
         'none': 'Keep the hand relaxed; do not hold a fist or shield'}.get(kind, '')]
    if not all(variants):
        raise ValueError('New gesture labels require --instruction')
    items = [{'id': f'{kind}-{i+1:03}', 'kind': kind, 'instruction': variants[i % len(variants)],
              'intended_count': 1 if kind == 'snap' or event else 0} for i in range(repetitions)]
    random.Random(seed).shuffle(items)
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kinesis-file', required=True)
    parser.add_argument('--kind', default='snap', help='snap, negative, or a registered state label')
    parser.add_argument('--config', default='configs/neural-emg.json')
    parser.add_argument('--instruction', help='Collection instruction for a new state or event gesture')
    parser.add_argument('--event', action='store_true', help='Quick one-off gesture, counted per clip like snap (needs --instruction)')
    parser.add_argument('--repetitions', type=int, default=20)
    parser.add_argument('--seconds', type=float, default=3.)
    parser.add_argument('--output-root', default='data/player-a/neural-guided')
    parser.add_argument('--wearing-session', required=True, help='Same ID for all blocks without removing/repositioning band')
    parser.add_argument('--role', choices=['train', 'evaluation'], default='train', help='Evaluation blocks are reserved from fitting')
    args = parser.parse_args()
    registry = json.loads(Path(args.config).read_text())
    counted = args.kind in ('snap', 'negative') or args.event
    if args.event and (args.kind in ('snap', 'negative') or not args.instruction):
        parser.error('--event is for a new gesture name and needs --instruction')
    if not counted and args.kind not in registry['tasks']['state']['classes']:
        parser.error('Add new gesture to the state class registry first, or pass --event for a quick gesture')
    trial_plan = plan(args.kind, args.repetitions, instruction=args.instruction, event=args.event)
    if args.repetitions < 1 or args.seconds < 2:
        parser.error('Use at least one repetition and at least two seconds per clip')
    stop = threading.Event(); lock = threading.RLock(); buffer = deque(maxlen=512)
    state = {'capture': None, 'last': None, 'error': None}
    def packet(value):
        now = time.monotonic()
        if 'source_uptime' not in value or abs(now-value['source_uptime']) > 2:
            state['error'] = 'Stale/missing Kinesis source uptime'; return
        with lock:
            row = {'kind': 'emg', **value}
            buffer.append((now, row)); state['last'] = now
            if state['capture'] is not None:
                state['capture'].append('emg', now, packet=row)
    reader = threading.Thread(target=tail_kinesis, args=(args.kinesis_file, stop, packet,
                              lambda message: state.update(error=message)), daemon=True)
    reader.start(); capture = None; trials = []
    print('EMG only. Start Kinesis raw recording at: '+str(Path(args.kinesis_file).resolve()), flush=True)
    print('One action per short clip, repeated 20 times by default. No event timestamps are assumed.', flush=True)
    try:
        while state['last'] is None:
            if state['error']:
                print(state['error'], flush=True); state['error'] = None
            if stop.wait(.25):
                return
        capture = LiveCapture(args.output_root, time.monotonic, {'signal': DEFAULT_SIGNAL, 'model_version': 'guided-collection-no-model'})
        capture.meta.update(kind='neural_emg_guided', wearing_session=args.wearing_session,
                            supervision='participant_confirmed_clip_labels_no_event_timestamps',
                            dataset_role='training_only_weak_labels' if args.role == 'train' else 'untouched_guided_count_check')
        print('Saving to '+str(capture.directory.resolve()), flush=True)
        with lock:
            state['capture'] = capture
            for now, row in buffer:
                capture.append('emg', now, packet=row)
        for index, trial in enumerate(trial_plan):
            input(f'\n{index+1}/{args.repetitions}: {trial["instruction"]}. Press Enter when ready. ')
            for remaining in (3, 2, 1):
                print(remaining, flush=True); stop.wait(1.)
            if state['last'] is None or time.monotonic()-state['last'] > .5:
                raise ValueError('No fresh EMG: recording paused; restart collection after checking Kinesis')
            start = time.monotonic()-capture.start
            print('\aGO — '+trial['instruction'], flush=True)
            stop.wait(args.seconds)
            end = time.monotonic()-capture.start
            print('STOP', flush=True)
            if counted:
                while True:
                    answer = input(f'How many actual {"snaps" if args.kind == "negative" else args.kind + "s"}? '
                                   '[Enter = intended count; x = uncertain/discard] ').strip().lower()
                    try:
                        count = None if answer == 'x' else trial['intended_count'] if not answer else int(answer)
                        if count is not None and count < 0:
                            raise ValueError()
                        break
                    except ValueError:
                        print('Enter a nonnegative whole count, or x to discard.', flush=True)
                confirmed = count is not None
            else:
                confirmed = input('Held the requested hand state throughout? [Enter=yes, x=discard] ').strip().lower() == ''
                count = None
            result = {**trial, 'start': start, 'end': end, 'confirmed': confirmed, 'reported_count': count,
                      'label_source': 'participant_confirmation', 'exact_event_times_verified': False}
            trials.append(result); write_json(capture.directory/'guided-trials.json', trials)
        with lock:
            state['capture'] = None; capture.finish()
        write_json(capture.directory/'guided-manifest.json', {
            'schema': 1, 'wearing_session': args.wearing_session, 'supervision': 'weak_clip_labels',
            'source_hashes': {name: _hash(capture.directory/name) for name in ('streams.jsonl', 'metadata.json', 'guided-trials.json')}})
        print('Saved '+str(capture.directory.resolve()), flush=True)
    finally:
        stop.set(); reader.join(timeout=2)
        if capture is not None and not capture.closed:
            with lock:
                state['capture'] = None; capture.finish(reason='interrupted')


if __name__ == '__main__':
    main()
