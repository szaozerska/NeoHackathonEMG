#!/usr/bin/env python3
"""Guided EMG-only collection: one separately confirmed action per short clip."""
import argparse
from collections import deque
import json
from pathlib import Path
import random
import sys
import threading
import time
from spelltrain.audio_reference import AudioReference, AUDIO_FILE, TIMING_FILE
from spelltrain.feeds import KINESIS_STREAM_ADAPTER, read_sse, tail_kinesis
from spelltrain.terminal_marks import keypress_mode, space_presses_until
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

MARK_GRACE_SECONDS = 1.


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
    parser.add_argument('--kinesis-file', help='Tail a Kinesis raw JSONL recording; omit to paste the Kinesis live stream URL')
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
    report = lambda message: state.update(error=message)
    if args.kinesis_file:
        band_source = 'kinesis_raw_jsonl'
        reader = threading.Thread(target=tail_kinesis, args=(args.kinesis_file, stop, packet, report), daemon=True)
        print('EMG only. Start Kinesis raw recording at: '+str(Path(args.kinesis_file).resolve()), flush=True)
    else:
        band_source = 'kinesis_live_stream'
        url = input('EMG only. In Kinesis enable Live EMG, then paste the stream URL from its stream tab: ').strip()
        reader = threading.Thread(target=read_sse, args=(url, KINESIS_STREAM_ADAPTER, stop, packet, report), daemon=True)
    reader.start(); capture = None; audio = None; trials = []
    action = 'snap' if args.kind in ('snap', 'negative') else args.kind
    print('EMG is the only model input; microphone audio is saved as a timing reference for labels.', flush=True)
    if counted:
        print(f'One action per short clip, repeated 20 times by default. Press SPACE with your other hand right after every {action}.', flush=True)
    try:
        while state['last'] is None:
            if state['error']:
                print(state['error'], flush=True); state['error'] = None
            if stop.wait(.25):
                return
        capture = LiveCapture(args.output_root, time.monotonic, {'signal': DEFAULT_SIGNAL, 'model_version': 'guided-collection-no-model'})
        capture.meta.update(kind='neural_emg_guided', wearing_session=args.wearing_session, band_source=band_source,
                            supervision='participant_confirmed_clip_counts_with_spacebar_after_action_marks' if counted
                            else 'participant_confirmed_clip_labels_no_event_timestamps',
                            dataset_role='training_only_weak_labels' if args.role == 'train' else 'untouched_guided_count_check')
        audio = AudioReference(capture.directory, capture.start, time.monotonic)
        print('Saving to '+str(capture.directory.resolve())+' · microphone: '+audio.device, flush=True)
        with lock:
            state['capture'] = capture
            for now, row in buffer:
                capture.append('emg', now, packet=row)
        stop.wait(1.)
        if audio.peak == 0:
            raise ValueError('Microphone delivers silence: allow this terminal in System Settings → '
                             'Privacy & Security → Microphone, then restart collection')
        def record_mark(pressed_at):
            with lock:
                capture.append('action_mark', pressed_at, action=action, source='participant_spacebar_after_action')
            print('  marked', flush=True)
        for index, trial in enumerate(trial_plan):
            input(f'\n{index+1}/{args.repetitions}: {trial["instruction"]}. Press Enter when ready. ')
            for remaining in (3, 2, 1):
                print(remaining, flush=True); stop.wait(1.)
            if state['last'] is None or time.monotonic()-state['last'] > .5:
                raise ValueError('No fresh EMG: recording paused; restart collection after checking Kinesis')
            go = time.monotonic(); start = go-capture.start
            print('\aGO — '+trial['instruction'], flush=True)
            if counted:
                with keypress_mode(sys.stdin.fileno()):
                    presses = space_presses_until(sys.stdin.fileno(), go+args.seconds, time.monotonic, record_mark)
                    stopped = time.monotonic(); end = stopped-capture.start
                    print(f'STOP — press SPACE now if you just made a {action}', flush=True)
                    presses += space_presses_until(sys.stdin.fileno(), stopped+MARK_GRACE_SECONDS,
                                                   time.monotonic, record_mark)
                marks = [pressed_at-capture.start for pressed_at in presses]
            else:
                stop.wait(args.seconds)
                end = time.monotonic()-capture.start
                print('STOP', flush=True)
            if counted:
                while True:
                    answer = input(f'How many actual {action}s? [Enter = {len(marks)} marked; x = uncertain/discard] ').strip().lower()
                    try:
                        count = None if answer == 'x' else len(marks) if not answer else int(answer)
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
            if counted:
                result.update(action_marks=marks, marks_match_count=count == len(marks),
                              action_mark_source='participant_spacebar_after_action_includes_reaction_delay')
            trials.append(result); write_json(capture.directory/'guided-trials.json', trials)
        capture.meta.update(audio_reference=audio.finish())
        with lock:
            state['capture'] = None; capture.finish()
        write_json(capture.directory/'guided-manifest.json', {
            'schema': 1, 'wearing_session': args.wearing_session, 'supervision': 'weak_clip_labels',
            'source_hashes': {name: _hash(capture.directory/name) for name in
                              ('streams.jsonl', 'metadata.json', 'guided-trials.json', AUDIO_FILE, TIMING_FILE)}})
        print('Saved '+str(capture.directory.resolve()), flush=True)
    finally:
        stop.set(); reader.join(timeout=2)
        if audio is not None and not audio.closed:
            capture.meta.update(audio_reference=audio.finish())
        if capture is not None and not capture.closed:
            with lock:
                state['capture'] = None; capture.finish(reason='interrupted')


if __name__ == '__main__':
    main()
