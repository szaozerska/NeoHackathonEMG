"""Replay a Space-interval capture through neural bundles exactly as the live predictor would, but batched.

Windows come from the same `SignalWindows` and gap resets as `NeuralEMGPredictor.feed`; the models then score every
window at once and the same snap/state decision rules run over the scores. Reports, per split part when
`--parts` is given: held-state majority per interval, snap recall, and false snaps per minute outside snaps.

    python scripts/replay_capture.py data/sophie/dynamic-20261108-040247-0a14a2cd models/neural-emg-04 models/neural-emg-05
"""
import argparse
import collections
import gzip
import json
import re
from pathlib import Path

import numpy as np

from spelltrain.effort import sensor_times
from spelltrain.neural import NeuralClassifier
from spelltrain.signals import SignalWindows

STATE = {'shield_hold': 'open', 'sword_hold': 'fist', 'animation_gesture': 'infinite_void', None: 'none'}


def read_packets(capture):
    path = next(p for p in (capture/'original/streams.jsonl.gz', capture/'streams.jsonl.gz', capture/'streams.jsonl',
                            capture/'original/streams.jsonl')
                if p.exists())
    with (gzip.open if path.suffix == '.gz' else open)(path, 'rt') as f:
        for line in f:
            row = json.loads(line)
            if row.get('kind') != 'emg':
                continue
            packet = row['packet']; mapped = (packet.get('timing') or {}).get('mapped_band_host_uptime_estimate')
            capture_t = mapped-(row['host_uptime']-row['capture_t']) if mapped is not None and 'host_uptime' in row \
                else row['capture_t']
            yield packet, float(capture_t)


def windows(capture, signal):
    """All live windows with the segment they belong to (a gap resets the live decision state)."""
    sw = SignalWindows(signal, include_waveforms=True); rate = signal['sample_rate']
    rows = []; sensor, host = [], []; last_seq = last_t = None; segment = 0
    for packet, capture_t in read_packets(capture):
        times = sensor_times(packet, rate); seq = packet['source_seq']
        if (last_seq is not None and seq != last_seq+1) or (
                last_t is not None and not 0 < times[0]-last_t <= 2.5/rate):
            sw.reset(); segment += 1
        last_seq, last_t = seq, times[-1]; sensor.append(times[0]); host.append(capture_t)
        for w in sw.feed(packet['samples'], times):
            w['segment'] = segment; rows.append(w)
    return rows, np.asarray(sensor), np.asarray(host)


def decide(manifest, rows, scores, snap_threshold=None, confirm=1, cooldown=.35):
    """Live decision rules; a snap fires after `confirm` consecutive windows at or above the threshold."""
    events, states = [], []
    for task, spec in manifest['tasks'].items():
        ix = [i for i, r in enumerate(rows) if r['kind'] == spec['window_kind']]; p = scores[task]
        memory = None; segment = None
        for i, pi in zip(ix, p):
            r = rows[i]; t = r['t']
            if r['segment'] != segment:
                segment = r['segment']; memory = {'label': 'unknown', 'candidate': 'unknown', 'votes': 0,
                                                  'rearmed': False, 'last': -float('inf'), 'run': 0}
            if 'event_class' in spec:
                s = float(pi[spec['classes'].index(spec['event_class'])])
                if s < .4:
                    memory['rearmed'] = True
                threshold = spec['threshold'] if snap_threshold is None else snap_threshold
                memory['run'] = memory['run']+1 if s >= threshold else 0
                if memory['run'] >= confirm and memory['rearmed'] and t-memory['last'] >= cooldown:
                    memory['last'] = t; memory['rearmed'] = False; events.append(t)
            else:
                guess = spec['classes'][int(pi.argmax())] if pi.max() >= spec['threshold'] else 'unknown'
                memory['votes'] = memory['votes']+1 if guess == memory['candidate'] else 1
                memory['candidate'] = guess
                if memory['votes'] >= 2:
                    memory['label'] = guess
                states.append((t, memory['label']))
    return np.asarray(events), states


def score_model(model_dir, rows, manifest):
    scores = {}
    for task, spec in manifest['tasks'].items():
        model = NeuralClassifier(model_dir/spec['checkpoint'])
        task_rows = [r for r in rows if r['kind'] == spec['window_kind']]
        scores[task] = np.concatenate([model.predict_rows(task_rows[i:i+2048]) for i in range(0, len(task_rows), 2048)])
    return scores


def report(intervals, parts, events, states, to_capture):
    ev = to_capture(events); st = to_capture(np.asarray([t for t, _ in states])); labels = np.asarray([l for _, l in states])
    out = {}
    for part in sorted(set(parts.values()) | {'not in split' if parts else 'all'}):
        clips = collections.defaultdict(lambda: [0, 0]); snaps = [0, 0]; false = 0; seconds = 0.
        for i, iv in enumerate(intervals):
            if parts and parts.get(i, 'not in split') != part:
                continue
            a, b = iv['start'], iv['end']
            motion = (iv.get('selected_motion') or {}).get('motion') if iv.get('intended') else None
            if motion == 'snap':
                snaps[1] += 1; snaps[0] += bool(((ev >= a-.1) & (ev <= b+.3)).any()); continue
            if motion not in STATE:
                continue
            false += int(((ev >= a) & (ev <= b)).sum()); seconds += b-a
            held = labels[(st >= a+.15) & (st <= b)]
            if len(held):
                clips[STATE[motion]][1] += 1
                clips[STATE[motion]][0] += collections.Counter(held).most_common(1)[0][0] == STATE[motion]
        out[part] = {'state_intervals': {k: f'{v[0]}/{v[1]}' for k, v in sorted(clips.items())},
                     'snaps_detected': f'{snaps[0]}/{snaps[1]}', 'false_snaps': false,
                     'false_snaps_per_min': round(false/seconds*60, 1) if seconds else None}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('capture', type=Path)
    parser.add_argument('models', type=Path, nargs='+')
    parser.add_argument('--labels', default='original/truth-values.json')
    parser.add_argument('--parts', type=Path, help='parts.json from build_pooled_dataset (session -> group -> part)')
    parser.add_argument('--sweep', action='store_true', help='also sweep snap threshold x confirm windows')
    args = parser.parse_args()
    intervals = json.loads((args.capture/args.labels).read_text())['intervals']
    parts = {}
    if args.parts:
        session = re.sub(r'^.*?(\d{8}-\d{6}-[0-9a-f]{8})$', r'\1', args.capture.name)
        for key, groups in json.loads(args.parts.read_text()).items():
            for group, part in groups.items() if key.split(':')[0] == session else ():
                m = re.search(r'interval-(\d+)', group)
                if m:
                    parts.setdefault(int(m.group(1)), part)
    cache = {}
    for model_dir in args.models:
        manifest = json.loads((model_dir/'model.json').read_text())
        key = json.dumps(manifest['signal'], sort_keys=True)
        if key not in cache:
            cache[key] = windows(args.capture, manifest['signal'])
        rows, sensor, host = cache[key]
        scores = score_model(model_dir, rows, manifest); to_capture = lambda t: np.interp(t, sensor, host)  # noqa: E731
        events, states = decide(manifest, rows, scores)
        print(json.dumps({'model': str(model_dir), **report(intervals, parts, events, states, to_capture)}, indent=1))
        if args.sweep:
            for threshold in (.99, .995, .998, .999, .9995):
                for confirm in (1, 2, 3):
                    events, _ = decide(manifest, rows, scores, threshold, confirm)
                    result = report(intervals, parts, events, states, to_capture)
                    print('sweep', model_dir.name, threshold, confirm, json.dumps(
                        {k: (v['snaps_detected'], v['false_snaps'], v['false_snaps_per_min']) for k, v in result.items()}))


if __name__ == '__main__':
    main()
