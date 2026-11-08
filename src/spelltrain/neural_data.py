"""Rebuild neural inputs from the existing source-checked review manifest.

All source values stay local. Intent marks and automatic camera estimates are
not labels. Historical test clips remain known development regression checks.
"""
from pathlib import Path
import joblib
import numpy as np
from .snap_onsets import refine_snap_onsets
from .signals import SignalWindows
from .common import read_json
from .effort import effort_dataset, _hash
from .retraining import prepare_records
from .feedback_update import capture_features
from .camera_retraining import reviewed_records
from .dataset_policy import require_usable_capture, require_training_capture


def verify_files(directory, hashes):
    for filename, digest in hashes.items():
        if _hash(Path(directory) / filename) != digest:
            raise ValueError('Reviewed source changed: ' + filename)


def check_trial_coverage(raw, trial, metadata):
    """A contiguous fragment cannot stand in for a full confirmed action clip."""
    def timestamp(row):
        uptime = row['packet'].get('source_uptime')
        return uptime-metadata['started_host_uptime'] if uptime is not None else row['capture_t']
    packets = [r for r in raw if trial['start']-.5 <= timestamp(r) <= trial['end']+.1]
    seqs = [r['packet']['source_seq'] for r in packets]
    if (len(seqs) < 10 or any(b != a+1 for a, b in zip(seqs, seqs[1:])) or
            timestamp(packets[0]) > trial['start']+.1 or timestamp(packets[-1]) < trial['end']-.1):
        raise ValueError('Guided trial has missing EMG; discard/re-record '+trial['id'])
    return packets


def build_dataset(reference_cache, reference_review, camera_reviews=()):
    """Preserve reviewed clip/block splits while regenerating raw waveforms."""
    cache = joblib.load(reference_cache)  # Locally produced, trusted cache only.
    review = read_json(reference_review)
    sources, records, quality = [], [], []
    for source in cache['sources']:
        directory = Path(source['directory'])
        require_training_capture(directory)
        supplemental = read_json(directory/'metadata.json').get('training_profile') == 'supplemental'
        label_file = 'supplemental-trials-v4.json' if supplemental else 'gesture-trials-v3.json'
        verify_files(directory, {name: source[key] for name, key in (
            ('streams.jsonl', 'streams_sha256'), ('metadata.json', 'metadata_sha256'),
            (label_file, 'labels_sha256'))})
        if supplemental:
            if source['labels_sha256'] != review['source_labels_sha256']:
                raise ValueError('Reference review label hash mismatch')
            for trial in review['trials']:
                verify_files(directory, {trial['reference_file']: trial['reference_sha256']})
        kwargs = {'include_snap': True, 'alignment': 'source_uptime', 'include_waveforms': True,
                  'signal': cache['signal']}
        if supplemental:
            from .supplemental import PROTOCOL, LABEL_FILE
            kwargs.update(label_file=LABEL_FILE, expected_protocol=PROTOCOL)
        rows, checks, manifest, signal = effort_dataset(directory, **kwargs)
        for row in rows:
            row.update(session=directory.name, local_trial=row['trial'],
                       trial=directory.name+':'+row['trial'])
        records.extend(rows); quality.extend(checks); sources.append(manifest)
    states, _, snaps = prepare_records({'records': records}, review)
    tasks = {'state': states, 'snap': snaps}
    seen = {str(Path(s['directory']).resolve()) for s in sources}
    for path in camera_reviews:
        annotation = read_json(path); directory = Path(annotation['source_directory'])
        if str(directory.resolve()) in seen:
            raise ValueError('Duplicate recording in dataset')
        seen.add(str(directory.resolve()))
        verify_files(directory, annotation['source_hashes'])
        capture = capture_features(directory, include_waveforms=True)
        if capture['metadata']['model']['signal'] != signal:
            raise ValueError('Signal settings differ across recordings')
        state, snap = reviewed_records(capture, annotation)
        waves = {(f['kind'], f['start'], f['t']): f['waveform'] for f in capture['features']}
        for name, rows in (('state', state), ('snap', snap)):
            for row in rows:
                row['waveform'] = waves[(name, row['start'], row['end'])]
                row['trial'] = directory.name+':'+row['trial']
                row['session'] = directory.name
            tasks[name].extend(rows)
        sources.append({'directory': str(directory.resolve()), 'review': str(Path(path).resolve()),
                        'review_sha256': _hash(path), 'hashes': annotation['source_hashes']})
    for name, rows in tasks.items():
        key = 'hand_state' if name == 'state' else 'snap_label'
        for row in rows:
            row['label'] = row[key]
            row['group'] = row.get('parent_trial', row['trial'])
    result = {'schema': 1, 'signal': signal, 'tasks': tasks, 'sources': sources,
              'reference_review_sha256': _hash(reference_review), 'quality': quality,
              'evaluation_role': 'known_development_regression_not_independent_session'}
    validate_dataset(result)
    return result


def validate_dataset(dataset):
    """No original clip or overlapping raw window may span task splits."""
    for name, supervised in dataset['tasks'].items():
        rows = list(supervised)
        for bag in dataset.get('weak_bags', {}).get(name, []):
            if bag['part'] != 'train' or not bag['positive']:
                raise ValueError('Weak positive bags must be training-only')
            rows.extend(bag['rows'])
        groups = {}; sessions = {}
        for row in rows:
            if row['part'] not in ('train', 'validation', 'test'):
                raise ValueError('Invalid split')
            group = (row['session'], row['group'])
            if group in groups and groups[group] != row['part']:
                raise ValueError('Original clip crosses splits: '+str(group))
            groups[group] = row['part']
            if not row['start'] < row['end']:
                raise ValueError('Invalid window times')
            if not np.isfinite(row['x']).all() or not np.isfinite(row['waveform']).all():
                raise ValueError('Non-finite input')
            sessions.setdefault(row['session'], {}).setdefault(row['part'], []).append(row)
        for session, parts in sessions.items():
            names = list(parts)
            for i, a in enumerate(names):
                # Check actual window unions, allowing disjoint clips in each split.
                for b in names[i+1:]:
                    aa = sorted(parts[a], key=lambda r: r['start'])
                    bb = sorted(parts[b], key=lambda r: r['start'])
                    j = 0
                    for r in aa:
                        while j < len(bb) and bb[j]['end'] <= r['start']:
                            j += 1
                        if j < len(bb) and bb[j]['start'] < r['end']:
                            raise ValueError('Raw windows overlap across splits: '+session+':'+name)


def add_reviewed_examples(dataset, path, config):
    """Append independently reviewed examples, including future gesture classes.

    NPZ contains feature[N,F] and waveform[N,C,T]. JSON rows carry their source,
    group, split, label and times. Unreviewed/intent-only examples are rejected.
    This interface is separate from the historical protocol-specific adapter.
    """
    manifest = read_json(path)
    require_training_capture(Path(path).parent)
    if manifest.get('independently_reviewed') is not True:
        raise ValueError('Independent example review required')
    root = Path(path).resolve().parent
    verify_files(root, manifest['source_hashes'])
    for task, entry in manifest['tasks'].items():
        if task not in config['tasks']:
            raise ValueError('Task absent from class registry: '+task)
        if entry['arrays'] not in manifest['source_hashes']:
            raise ValueError('Example arrays must be source-hashed')
        with np.load(root/entry['arrays'], allow_pickle=False) as arrays:
            if len(arrays['features']) != len(entry['rows']) or len(arrays['waveforms']) != len(entry['rows']):
                raise ValueError('Example/array count mismatch')
            for i, row in enumerate(entry['rows']):
                if row['label'] not in config['tasks'][task]['classes'] and row['label'] is not None:
                    raise ValueError('Label absent from class registry')
                dataset['tasks'].setdefault(task, []).append({**row, 'x': arrays['features'][i].copy(),
                                                            'waveform': arrays['waveforms'][i].copy()})
    dataset['sources'].append({'review': str(Path(path).resolve()), 'sha256': _hash(path),
                               'hashes': manifest['source_hashes']})
    validate_dataset(dataset)


def add_guided_capture(dataset, directory, hold_negatives=False, audio_onsets=False, signal=None):
    """Count-confirmed positives become MIL bags, never guessed snap windows.

    All new guided clips fit only; fresh evaluation must remain separate. A
    20-snap block is collected as 20 individually confirmed short bags, with
    rotation/intensity variants. Count > 1 still supplies at-least-one evidence.
    """
    directory = Path(directory)
    require_training_capture(directory)
    if any(s.get('directory') == str(directory.resolve()) for s in dataset['sources']):
        raise ValueError('Duplicate guided capture')
    manifest = read_json(directory/'guided-manifest.json')
    verify_files(directory, manifest['source_hashes'])
    capture = capture_features(directory, include_waveforms=True, signal=signal)
    if capture['metadata'].get('dataset_role') == 'untouched_guided_count_check':
        raise ValueError('Reserved evaluation capture cannot enter fitting')
    if {**capture['metadata']['model']['signal'], **(signal or {})} != dataset['signal']:
        raise ValueError('Guided capture signal settings differ')
    from .common import json_lines
    raw = [r for r in json_lines(directory/'streams.jsonl') if r['kind'] == 'emg']
    # audio_onsets: trials whose marks refine to an audible transient the EMG agrees with become supervised.
    refined = refine_snap_onsets(directory, capture['features']) if audio_onsets else {}
    for trial in read_json(directory/'guided-trials.json'):
        if not trial['confirmed']:
            continue
        check_trial_coverage(raw, trial, capture['metadata'])
        group = directory.name+':'+trial['id']
        rows = []
        for feature in capture['features']:
            if feature['start'] < trial['start']+.15 or feature['t'] > trial['end']-.15:
                continue
            kind = 'snap' if trial['kind'] in ('snap', 'negative') else 'state'
            if feature['kind'] != kind and not (hold_negatives and kind == 'state'):
                continue
            rows.append({**feature, 'end': feature['t'], 'part': 'train', 'group': group, 'trial': group,
                         'session': directory.name, 'wearing_session': manifest['wearing_session'],
                         'label_source': 'participant_confirmation'})
        if not rows:
            raise ValueError('No usable windows in guided clip')
        if trial['id'] in refined:
            onsets = refined[trial['id']]['onsets']
            for row in rows:
                t = row['end']
                if any(o-.05 <= t <= o+.125 for o in onsets):
                    label = 'snap'
                elif any(row['start']-.3 <= o <= t+.3 for o in onsets):
                    label = None  # Ambiguous: replayed for event scoring, never fitted.
                else:
                    label = 'negative'
                dataset['tasks']['snap'].append({**row, 'label': label, 'snap_label': label, 'expected_events': onsets,
                                                 'label_source': 'audio_refined_action_mark'})
            dataset.setdefault('snap_onsets', {})[group] = refined[trial['id']]
        elif trial['kind'] in ('snap', 'negative') and trial['reported_count'] > 0:
            dataset.setdefault('weak_bags', {}).setdefault('snap', []).append({
                'rows': rows, 'reported_count': trial['reported_count'], 'group': group,
                'part': 'train', 'positive': True, 'label_source': 'participant_confirmed_count',
                'instruction': trial['instruction']})
        else:
            for row in rows:
                # A confirmed hold contains no snap, so its snap windows are negatives too.
                label = 'negative' if row['kind'] == 'snap' else trial['kind']
                row['label'] = label; row['hand_state' if row['kind'] == 'state' else 'snap_label'] = label
                row['expected_events'] = []
                dataset['tasks'].setdefault(row['kind'], []).append(row)
    dataset['sources'].append({'directory': str(directory.resolve()), 'supervision': 'weak_participant_confirmed',
                              'hashes': manifest['source_hashes'], 'wearing_session': manifest['wearing_session']})
    validate_dataset(dataset)


INTERVAL_STATES = {'shield_hold': 'open', 'sword_hold': 'fist', 'animation_gesture': 'infinite_void'}


def interval_capture_features(directory, signal=None):
    """Gap-reset windows for a Space-interval contribution (gzip stream, sensor clock mapped to host)."""
    import gzip, json
    meta = read_json(directory/'metadata.json')
    stream = directory/'streams.jsonl'
    opener = open if stream.exists() else gzip.open
    stream = stream if stream.exists() else directory/'streams.jsonl.gz'
    fs = meta['model']['signal']['sample_rate']
    windows = SignalWindows({**meta['model']['signal'], **(signal or {})}, include_waveforms=True)
    features = []; last = epoch = None
    with opener(stream, 'rt') as f:
        for line in f:
            row = json.loads(line)
            if row['kind'] != 'emg':
                continue
            packet = row['packet']; timing = packet.get('timing') or {}
            if last is not None and (packet['source_seq'] != last+1 or timing.get('clock_epoch') != epoch):
                windows.reset()
            last, epoch = packet['source_seq'], timing.get('clock_epoch')
            # The collector's lower-envelope band->host mapping; Python receipt lag is not action time.
            end = timing['mapped_band_host_uptime_estimate']-meta['started_host_uptime']
            times = end-np.arange(len(packet['samples'])-1, -1, -1)/fs
            features.extend(windows.feed(packet['samples'], times))
    return features, meta


def add_interval_capture(dataset, directory, validation_after=.7, signal=None):
    """Micah-style Space-held intervals: holds -> open/fist, non-intended -> none/negative, snaps -> bags.

    Within each class (non-intended, snap, shield, sword) the intervals after the first
    validation_after fraction validate, since contributions are recorded in class blocks. Validation snaps use the published reference peak as expected event; snaps without
    one are dropped from validation. Windows within 1 s of a published snap-like candidate in a
    non-intended interval are excluded rather than relabeled.
    """
    directory = Path(directory)
    original = directory/'original' if (directory/'original').is_dir() else directory
    require_usable_capture(directory); require_usable_capture(original)
    features, meta = interval_capture_features(original, signal)
    if not meta.get('recording_complete'):
        raise ValueError('Interval capture incomplete')
    if {**meta['model']['signal'], **(signal or {})} != dataset['signal']:
        raise ValueError('Interval capture signal settings differ')
    intervals = read_json(original/'truth-values.json')['intervals']
    analysis = directory/'analysis'
    peaks = {r['label_index']: r['peak_capture_t'] for r in read_json(analysis/'reference-quality.json')} \
        if (analysis/'reference-quality.json').exists() else {}
    suspects = [c['capture_t_seconds'] for c in read_json(analysis/'review-candidates.json')] \
        if (analysis/'review-candidates.json').exists() else []
    classes = {}
    for i, interval in enumerate(intervals):
        classes.setdefault((interval.get('selected_motion') or {}).get('motion') if interval['intended'] else None, []).append(i)
    validation = {i for ix in classes.values() for i in ix[len(ix)-round(len(ix)*(1-validation_after)):]} \
        if validation_after else set()
    by_kind = {k: sorted((f for f in features if f['kind'] == k), key=lambda f: f['t']) for k in ('state', 'snap')}
    ends = {k: np.array([f['t'] for f in v]) for k, v in by_kind.items()}
    session = meta['id']; added = {'state': 0, 'snap': 0, 'bags': 0}
    # Animation Gesture (Infinite Void) contributions report possible gesture contamination in
    # red time, so their non-intended intervals are not used as negatives.
    animation = 'animation_gesture' in classes
    for index, interval in enumerate(intervals):
        a, b = interval['start'], interval['end']
        part = 'validation' if index in validation else 'train'
        motion = (interval.get('selected_motion') or {}).get('motion') if interval['intended'] else None
        if interval['intended'] and motion not in INTERVAL_STATES and motion != 'snap' or animation and not interval['intended']:
            continue
        group = f'{session}:interval-{index:04d}'
        base = {'part': part, 'group': group, 'trial': group, 'session': session,
                'wearing_session': meta['wearing_session'], 'label_source': 'participant_spacebar_interval'}

        def rows(kind, lo, hi):
            ix = np.flatnonzero((ends[kind] >= lo) & (ends[kind] <= hi))
            return [{**by_kind[kind][i], 'end': by_kind[kind][i]['t'], **base} for i in ix]
        clear = lambda r: all(abs(r['end']-c) > 1. and abs(r['start']-c) > 1. for c in suspects)
        if motion == 'snap':
            if part == 'train':
                bag = rows('snap', a, b+.15)
                if bag:
                    dataset.setdefault('weak_bags', {}).setdefault('snap', []).append({
                        'rows': bag, 'reported_count': 1, 'group': group, 'part': 'train', 'positive': True,
                        'label_source': 'participant_spacebar_interval', 'instruction': 'snap'})
                    added['bags'] += 1
            elif index in peaks:
                o = peaks[index]
                # Starts stay clear of the previous interval's windows (its margin is >= .15 s).
                for r in rows('snap', a-.05, b+.3):
                    label = 'snap' if o-.05 <= r['end'] <= o+.125 else None if r['start']-.3 <= o <= r['end']+.3 else 'negative'
                    dataset['tasks']['snap'].append({**r, 'label': label, 'snap_label': label, 'expected_events': [o],
                                                     'label_source': 'micah_review_reference_peak'})
                    added['snap'] += 1
            continue
        state = INTERVAL_STATES.get(motion, 'none')
        # Space marks the first finger interaction; the multi-step sign forms and undoes inside the hold.
        margin = 1. if motion == 'animation_gesture' else .15 if interval['intended'] else .3
        for kind in ('state', 'snap'):
            for r in rows(kind, a+margin, b-margin):
                if r['start'] < a+margin or (not interval['intended'] and not clear(r)):
                    continue
                label = state if kind == 'state' else 'negative'
                r.update({'label': label, ('hand_state' if kind == 'state' else 'snap_label'): label, 'expected_events': []})
                dataset['tasks'][kind].append(r); added[kind] += 1
    dataset['sources'].append({'directory': str(directory.resolve()), 'supervision': 'weak_participant_spacebar_intervals',
                              'wearing_session': meta['wearing_session'], 'validation_after': validation_after, 'windows': added})



RESERVED = __import__('re').compile(r'valid|holdout|held.?out|test.?set|evaluation', __import__('re').I)


def require_training_directory(directory):
    """Reserved validation/test recordings and contributor rejections never enter training."""
    directory = Path(directory)
    if any(RESERVED.search(part) for part in directory.resolve().parts[-4:]):
        raise ValueError(f'{directory} is reserved validation/test data')
    if any((d/'DO_NOT_USE.json').exists() or (d/'DO_NOT_USE.md').exists() for d in (directory, *directory.parents[:2])):
        raise ValueError(f'{directory} is marked DO NOT USE')


def guided_only_dataset(directories, interval_directories=(), signal=None):
    """Train from guided captures alone, without the historical reference review.

    Whole captures are the split unit: for every held kind with two or more
    captures the newest one validates (a single capture: each clip's last 20%).
    The latest quarter of audio-refined snap trials validates snap recall;
    unrefined count bags stay training-only. signal overrides window sizes etc.
    """
    directories = sorted(Path(d) for d in directories)
    for d in [*directories, *interval_directories]:
        require_training_directory(d)
    if not directories:
        raise ValueError('No guided captures given')
    overrides = signal or {}
    signal = {**read_json(directories[0]/'metadata.json')['model']['signal'], **overrides}
    dataset = {'schema': 1, 'signal': signal, 'tasks': {'state': [], 'snap': []}, 'sources': [],
               'evaluation_role': 'guided_capture_holdout_same_wearing_sessions'}
    kinds = {}
    for directory in directories:
        add_guided_capture(dataset, directory, hold_negatives=True, audio_onsets=True, signal=overrides)
        trial_kinds = {t['kind'] for t in read_json(directory/'guided-trials.json') if t['confirmed']}
        if len(trial_kinds) == 1 and not trial_kinds & {'snap', 'negative'}:
            kinds.setdefault(trial_kinds.pop(), []).append(directory.name)
    held_out = {names[-1] for names in kinds.values() if len(names) > 1}
    single = {names[0] for names in kinds.values() if len(names) == 1}
    timed = sorted(dataset.get('snap_onsets', {}), key=lambda g: dataset['snap_onsets'][g]['onsets'][0])
    snap_validation = set(timed[len(timed)-len(timed)//4:])
    for name, rows in dataset['tasks'].items():
        spans = {}
        for row in rows:
            a, b = spans.get(row['group'], (row['start'], row['end']))
            spans[row['group']] = (min(a, row['start']), max(b, row['end']))
        kept = []
        for row in rows:
            if row['session'] in held_out or row['group'] in snap_validation:
                row['part'] = 'validation'
            elif row['session'] in single:
                # A kind with one capture validates on the last 20% of each clip; straddling windows are dropped.
                a, b = spans[row['group']]; cut = a+.8*(b-a)
                if row['start'] < cut < row['end']:
                    continue
                if row['start'] >= cut:
                    row['part'] = 'validation'; row['group'] += ':tail'; row['trial'] += ':tail'
            kept.append(row)
        dataset['tasks'][name] = kept
    for directory in interval_directories:
        add_interval_capture(dataset, directory, signal=overrides)
    dataset['validation_captures'] = sorted(held_out)
    dataset['validation_tail_captures'] = sorted(single)
    dataset['validation_snap_trials'] = sorted(snap_validation)
    validate_dataset(dataset)
    return dataset
