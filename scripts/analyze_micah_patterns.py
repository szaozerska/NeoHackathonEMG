#!/usr/bin/env python3
"""Exploratory EMG attribution and cross-condition evaluation; never changes labels/live models."""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np
from scipy import signal
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import balanced_accuracy_score, confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from review_micah_dynamic import clock_fit, digest, save
from spelltrain.dataset_policy import require_usable_capture

FS = 2048
WINDOW = 400  # 195.3125 ms, divisible into eight 24.4 ms subwindows
HOP = 100
FAMILIES = {'energy': slice(0, 1), 'profile': slice(1, 9),
            'amplitude': slice(9, 33), 'spectral': slice(33, 57),
            'temporal': slice(57, 73)}


def features(w):
    """[windows,samples,channels], causal windows: no future or timing/label inputs."""
    rms = np.sqrt(np.mean(w*w, axis=1))
    mav = np.mean(np.abs(w), axis=1)
    wl = np.mean(np.abs(np.diff(w, axis=1)), axis=1)
    energy = np.sqrt(np.mean(rms*rms, axis=1, keepdims=True))
    profile = rms / np.maximum(np.linalg.norm(rms, axis=1, keepdims=True), 1e-9)
    power = np.abs(np.fft.rfft(w*np.hanning(WINDOW)[None, :, None], axis=1))**2
    hz = np.fft.rfftfreq(WINDOW, 1/FS)
    bands = np.stack([power[:, (hz >= a)&(hz < b)].sum(1)
                      for a, b in [(20, 100), (100, 225), (225, 450)]], axis=1)
    bands /= np.maximum(bands.sum(1, keepdims=True), 1e-9)
    sub = np.sqrt(np.mean(w.reshape(len(w), 8, 50, 8)**2, axis=2))
    cv = sub.std(1)/np.maximum(sub.mean(1), 1e-9)
    rise = (sub[:, -2:].mean(1)-sub[:, :2].mean(1))/np.maximum(rms, 1e-9)
    return np.concatenate([np.log1p(energy), profile, np.log1p(rms), np.log1p(mav),
                           np.log1p(wl), bands.reshape(len(w), -1), cv, rise], axis=1)


def extract(source, cache):
    source = Path(source)
    require_usable_capture(source)
    meta = json.loads((source/'metadata.json').read_text())
    if not meta.get('recording_complete'):
        raise ValueError('Finish capture before analysis')
    truth = json.loads((source/'truth-values.json').read_text())['intervals']
    stream = source/'streams.jsonl'
    if not stream.exists():
        stream = source/'streams.jsonl.gz'
    identity = {'raw_sha256': digest(stream), 'truth_sha256': digest(source/'truth-values.json'),
                'algorithm': 'raw-causal-400x100-v1'}
    marker = cache.with_suffix('.json')
    if cache.exists() and marker.exists() and json.loads(marker.read_text())['identity'] == identity:
        with np.load(cache) as data:
            arrays = {k: data[k] for k in data.files}
        return arrays, json.loads(marker.read_text()), truth
    n = meta['counts']['emg']
    raw = np.empty((n, 16, 8), np.uint16)
    native = np.empty(n); receipt = np.empty(n); epochs = np.empty(n, np.int64)
    seq = np.empty(n, np.int64); delivery = np.empty(n)
    opener = gzip.open if stream.suffix == '.gz' else open
    i = 0
    with opener(stream, 'rt') as f:
        for line in f:
            row = json.loads(line)
            if row['kind'] != 'emg':
                continue
            p = row['packet']; raw[i] = p['samples']; native[i] = p['source_t']/1e6
            receipt[i] = p['source_uptime']; seq[i] = p['source_seq']
            epochs[i] = (p.get('timing') or {}).get('clock_epoch', 0)
            delivery[i] = row['host_uptime']-receipt[i]; i += 1
    if i != n:
        raise ValueError('Packet count mismatch')
    mapped = np.empty(n); fits = []
    for epoch in np.unique(epochs):
        ix = np.flatnonzero(epochs == epoch)
        mapped[ix], fit = clock_fit(native[ix], receipt[ix]); fits.append(fit)
    breaks = np.flatnonzero((np.diff(seq) != 1)|(np.diff(epochs) != 0)|
                           (np.abs(np.diff(native)-16/FS) > 2.5/FS))+1
    sos = np.vstack([signal.butter(4, [20, 450], fs=FS, btype='bandpass', output='sos'),
                     signal.tf2sos(*signal.iirnotch(60, 30, fs=FS))])
    all_x = []; all_start = []; all_end = []
    for a, b in zip(np.r_[0, breaks], np.r_[breaks, n]):
        x = raw[a:b].reshape(-1, 8).astype(float)-32768
        # Reset at gaps; skip 250 ms of filter settling after each reset.
        offsets = np.arange(512, len(x)-WINDOW+1, HOP)
        if not len(offsets):
            continue
        x = signal.sosfilt(sos, x, axis=0, zi=signal.sosfilt_zi(sos)[:, :, None]*x[0])[0]
        for start in range(0, len(offsets), 256):
            ix = offsets[start:start+256]
            w = x[ix[:, None]+np.arange(WINDOW)[None, :]]
            all_x.append(features(w).astype(np.float32))
            sample_start = mapped[a+ix//16]+(ix % 16)/FS-meta['started_host_uptime']
            all_start.append(sample_start); all_end.append(sample_start+(WINDOW-1)/FS)
    X = np.concatenate(all_x); start = np.concatenate(all_start); end = np.concatenate(all_end)
    intervals = np.asarray([v['end'] for v in truth])
    group = np.searchsorted(intervals, start, side='right')
    valid = (group < len(truth)) & (start >= 0) & (end <= meta['duration_seconds'])
    safe = np.minimum(group, len(truth)-1)
    # Entire window must belong to one reported interval; crossing windows are not mislabeled.
    valid &= end <= intervals[safe]
    y = np.array(['intended' if truth[v]['intended'] else 'non_intended' for v in safe])
    motion = np.array([(truth[v].get('selected_motion') or {}).get('motion', 'non_intended')
                       if truth[v]['intended'] else 'non_intended' for v in safe])
    effort = np.array([(truth[v].get('selected_motion') or {}).get('effort', 'none') or 'none' for v in safe])
    margin = np.minimum(start-np.array([truth[v]['start'] for v in safe]), intervals[safe]-end)
    arrays = {k: v[valid] for k, v in dict(X=X, start=start, end=end, group=group,
                                         intent=y, motion=motion, effort=effort, margin=margin).items()}
    report = {'identity': identity, 'session_id': meta['id'], 'wearing_session': meta.get('wearing_session'),
              'condition': meta.get('test_condition'), 'duration_seconds': meta['duration_seconds'],
              'counts': meta['counts'], 'window_count': int(valid.sum()), 'sequence_discontinuities': len(breaks),
              'clipped_adc_fraction': float(np.mean((raw == 0)|(raw == 65535))),
              'delivery_lag_quantiles_seconds': list(map(float, np.quantile(delivery, [.5, .95, .99]))),
              'clock_fits': fits, 'original_truth_intervals': len(truth),
              'interior_definition': 'At least 0.5 seconds inside both reported boundaries; sensitivity analysis only, no labels edited.'}
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **arrays); save(marker, report)
    return arrays, report, truth


def interval_weights(y, groups):
    """Every class has equal weight; every interval within that class has equal weight."""
    weights = np.empty(len(y))
    for label in np.unique(y):
        same = y == label; ids = np.unique(groups[same])
        for group in ids:
            ix = same & (groups == group)
            weights[ix] = 1/(len(ids)*ix.sum())
    return weights*len(weights)/weights.sum()


def metrics(y, prediction, groups, classes):
    w = interval_weights(y, groups)
    matrix = confusion_matrix(y, prediction, labels=classes, sample_weight=w)
    matrix = matrix/np.maximum(matrix.sum(1, keepdims=True), 1e-9)
    return {'classes': list(classes), 'interval_balanced_recall': float(np.trace(matrix)/len(classes)),
            'window_balanced_accuracy': float(balanced_accuracy_score(y, prediction)),
            'interval_weighted_confusion_row_fractions': matrix.tolist(),
            'intervals_per_class': {v: len(np.unique(groups[y == v])) for v in classes},
            'recall_by_class': dict(zip(classes, map(float, matrix.diagonal()))),
            'windows': len(y), 'accuracy_scope': 'Agreement with weak Spacebar reports; not verified event accuracy'}


def model(name):
    if name == 'lda':
        return make_pipeline(StandardScaler(), LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto'))
    return ExtraTreesClassifier(n_estimators=160, max_depth=12, min_samples_leaf=8,
                                random_state=7, n_jobs=2)


def fit(estimator, name, X, y, groups):
    if name == 'trees':
        estimator.fit(X, y, sample_weight=interval_weights(y, groups))
    else:
        # LDA lacks sample weights: deterministic equal-count sampling by class and interval.
        rng = np.random.default_rng(7); selected = []
        counts = {v: np.unique(groups[y == v]) for v in np.unique(y)}
        for label, ids in counts.items():
            count = max(1, 1500//len(ids))
            for group in ids:
                ix = np.flatnonzero((y == label)&(groups == group))
                selected.extend(rng.choice(ix, count, replace=len(ix) < count))
        estimator.fit(X[selected], y[selected])
    return estimator


def experiment(train, test, task, columns, name, interior=True):
    def subset(data):
        y = data['intent'] if task == 'intent' else data['motion']
        keep = np.ones(len(y), bool)
        if interior:
            keep &= data['margin'] >= .5
        if task == 'hold':
            keep &= np.isin(y, ['shield_hold', 'sword_hold'])
        return data['X'][keep][:, columns], y[keep], data['group'][keep]
    X, y, groups = subset(train); classes = np.unique(y)
    if test is not None:
        Z, target, tg = subset(test)
        if not set(target).issubset(set(classes)):
            return {'unavailable': 'Unseen target class'}
        estimator = fit(model(name), name, X, y, groups)
        return metrics(target, estimator.predict(Z), tg, classes)
    counts = [len(np.unique(groups[y == v])) for v in classes]
    splits = min(3, min(counts))
    if splits < 2:
        return {'unavailable': 'Fewer than two whole intervals for a class', 'interval_counts': counts}
    prediction = np.full(len(y), '', dtype=y.dtype); folds = []
    for tr, te in StratifiedGroupKFold(splits, shuffle=True, random_state=7).split(X, y, groups):
        assert not set(groups[tr]) & set(groups[te])
        if len(np.unique(y[tr])) != len(classes):
            return {'unavailable': 'A whole-interval fold lacks a training class'}
        estimator = fit(model(name), name, X[tr], y[tr], groups[tr])
        prediction[te] = estimator.predict(X[te])
        folds.append({'train_intervals': list(map(int, np.unique(groups[tr]))),
                      'test_intervals': list(map(int, np.unique(groups[te])))})
    return {**metrics(y, prediction, groups, classes), 'folds': folds}


def hold_summaries(data, labels):
    rows = []
    for i, label in enumerate(labels):
        if not label['intended']:
            continue
        ix = np.flatnonzero((data['group'] == i)&(data['margin'] >= .5))
        row = {'original_interval': i, 'start': label['start'], 'end': label['end'],
               'selected_motion': label.get('selected_motion'), 'original_label_retained': True}
        if not len(ix):
            rows.append({**row, 'review_note': 'Too short or no complete interior window; retained in raw data.'})
            continue
        energy = np.expm1(data['X'][ix, 0]); profile = data['X'][ix, 1:9]
        chunks = np.array_split(np.arange(len(ix)), 3)
        thirds = [float(np.median(energy[v])) for v in chunks]
        bins = np.floor((data['start'][ix]-label['start'])/5).astype(int)
        trajectory = [{'seconds_into_hold': int(v)*5,
                       'median_rms_adc': float(np.median(energy[bins == v]))} for v in np.unique(bins)]
        row.update(interior_windows=len(ix), median_rms_adc=float(np.median(energy)),
                   rms_p10_p90=list(map(float, np.quantile(energy, [.1, .9]))),
                   median_rms_first_middle_last_third=thirds,
                   last_to_first_third_ratio=thirds[-1]/max(thirds[0], 1e-9),
                   normalized_channel_profile_median=np.median(profile, axis=0).tolist(),
                   five_second_amplitude_trajectory=trajectory,
                   note='Amplitude change can reflect effort drift, pose/contact change or fatigue; not measured force.')
        rows.append(row)
    return rows


def effort_support(data):
    counts = {}
    for motion in ['shield_hold', 'sword_hold']:
        for effort in ['low', 'medium', 'high']:
            keep = (data['motion'] == motion)&(data['effort'] == effort)&(data['margin'] >= .5)
            counts[motion+':'+effort] = len(np.unique(data['group'][keep]))
    return {'whole_intervals_with_interior_windows': counts,
            'six_class_validation_supported': min(counts.values()) >= 2,
            'note': 'A single sustained trial does not provide independent train/test repetitions. Effort selections are not calibrated force.'}


def run(static, dynamic, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    datasets = {}; summary = {}; labels = {}
    for kind, path in [('static', static), ('dynamic', dynamic)]:
        print('Extracting', kind, flush=True)
        datasets[kind], summary[kind], labels[kind] = extract(path, output/(kind+'-features.npz'))
    variants = {'energy_only': [0], 'channel_profile_only': list(range(1, 9)),
                'full_time_spectral': list(range(73))}
    results = {}
    for task in ['intent', 'hold']:
        for variant, cols in variants.items():
            for name in ['lda', 'trees']:
                for train, target in [('static', None), ('dynamic', None), ('dynamic', 'static'), ('static', 'dynamic')]:
                    key = f'{task}/{variant}/{name}/{train}_to_{target or "group_cv"}'
                    print(key, flush=True)
                    results[key] = experiment(datasets[train], datasets.get(target), task, cols, name)
    # Untrimmed sensitivity preserves every full-window label without fixed edge exclusions.
    for task in ['intent', 'hold']:
        results[f'{task}/full_time_spectral/trees/dynamic_to_static_untrimmed'] = experiment(
            datasets['dynamic'], datasets['static'], task, list(range(73)), 'trees', interior=False)
    report = {'purpose': 'Exploratory signal attribution, drift and cross-condition checks',
              'live_model_replaced': False, 'participant_labels_changed': False,
              'window_samples': WINDOW, 'hop_samples': HOP, 'sample_rate_hz': FS,
              'feature_families': {k: [v.start, v.stop] for k, v in FAMILIES.items()},
              'datasets': summary, 'experiments': results,
              'static_effort_validation_support': effort_support(datasets['static']),
              'static_hold_summaries': hold_summaries(datasets['static'], labels['static']),
              'limitations': ['Both recordings share a wearing-session identifier; transfer is across conditions, not independent wearing sessions.',
                  'Static holds are sequentially blocked by class/effort; elapsed-time/contact drift can confound classification.',
                  'Interior windows are a sensitivity subset, not automatic boundary correction. Raw labels remain unchanged.',
                  'No static snaps or relaxed open-fireball trials; shield tension is not a verified relaxed-open baseline.',
                  'Requested effort can drift. ADC amplitude is not calibrated force or a measurement of individual muscles.',
                  'No gyro/orientation was recorded; continuous orientation invariance cannot be evaluated here.',
                  'Multiple model comparisons are exploratory development, not reserved final evaluation.',
                  'Binary intent predicts report-associated patterns; a hard gate may suppress subtle true snaps.']}
    save(output/'pattern-report.json', report)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), layout='constrained')
    data = datasets['static']; energy = np.expm1(data['X'][:, 0])
    axes[0].plot(data['end'], energy, lw=.6, color='black')
    colors = {'shield_hold': '#147d92', 'sword_hold': '#b34156'}
    for label in labels['static']:
        if label['intended']:
            selected = label.get('selected_motion') or {}
            axes[0].axvspan(label['start'], label['end'], color=colors.get(selected.get('motion'), 'gray'), alpha=.18)
            if label['end']-label['start'] > 8:
                axes[0].text((label['start']+label['end'])/2, .98,
                    selected.get('motion', '').replace('_hold', '')+'\n'+str(selected.get('effort')),
                    transform=axes[0].get_xaxis_transform(), ha='center', va='top', fontsize=8)
    axes[0].set(yscale='log', ylabel='Filtered RMS (ADC counts)', xlabel='Recording seconds',
                title='Static baseline: reported effort can vary throughout a hold')
    rows = [v for v in report['static_hold_summaries'] if 'normalized_channel_profile_median' in v]
    im = axes[1].imshow([v['normalized_channel_profile_median'] for v in rows], aspect='auto', cmap='viridis')
    axes[1].set_yticks(range(len(rows)), [f"#{v['original_interval']} {v['selected_motion']['motion']} {v['selected_motion']['effort']}" for v in rows])
    axes[1].set_xticks(range(8), [f'Ch {i+1}' for i in range(8)])
    axes[1].set_title('Amplitude-normalized channel patterns (electrode positions, not identified muscles)')
    fig.colorbar(im, ax=axes[1], label='Normalized RMS')
    fig.savefig(output/'static-patterns.png', dpi=150); plt.close(fig)
    lines = ['# Micah EMG pattern analysis — 2026-11-08', '',
             'Exploratory development results using unchanged participant reports. No live model was replaced.', '',
             '## Shield versus sword: what information helps?', '',
             'Train on dynamic holds; evaluate on static holds. Equal weight per class and per original interval. '
             'This is cross-condition transfer within a shared wearing-session identifier, not independent session validation.', '',
             '| Features (ExtraTrees) | Mean interval-balanced recall | Shield recall | Sword recall |',
             '|---|---:|---:|---:|']
    for variant in variants:
        v = results[f'hold/{variant}/trees/dynamic_to_static']
        lines.append(f"| {variant} | {v['interval_balanced_recall']:.1%} | {v['recall_by_class']['shield_hold']:.1%} | {v['recall_by_class']['sword_hold']:.1%} |")
    lines += ['', 'The relative channel pattern is much more useful than total amplitude alone. '
              'These are electrode measurements; no anatomical muscle or causal intent attribution is established.', '',
              '## Effort drift', '',
              '| Original interval | Participant selection | Median RMS (ADC) | Last/first-third amplitude |',
              '|---|---|---:|---:|']
    for row in rows:
        selected = row['selected_motion']
        lines.append(f"| {row['original_interval']} | {selected['motion']} {selected['effort']} | {row['median_rms_adc']:.1f} | {row['last_to_first_third_ratio']:.2f} |")
    lines += ['', 'Strength drift is preserved, not automatically relabeled. Medium and high shield amplitude overlap; '
              'the short high-shield interval #7 has a different profile and merits review without changing its label. '
              'Low sword is close to the quiet signal floor. Three subsecond intended intervals have no 0.5-second '
              'interior and remain in the raw dataset and untrimmed sensitivity analysis.', '',
              '## Intent gate and boundary sensitivity', '',
              'The full-feature ExtraTrees dynamic-to-static intent model achieves '
              f"{results['intent/full_time_spectral/trees/dynamic_to_static']['interval_balanced_recall']:.1%} "
              'mean interval-balanced recall on interior windows; fitting/evaluating with all complete untrimmed '
              f"windows gives {results['intent/full_time_spectral/trees/dynamic_to_static_untrimmed']['interval_balanced_recall']:.1%}. "
              'This difference shows dependence on window selection and weak label boundaries. It does not establish '
              'the true event boundary or justify cleaning labels with model predictions. A hard intent gate is not ready.', '',
              '## Validation limits', '']
    lines += ['- '+v for v in report['limitations']]
    lines += ['', 'Six-way motion/strength validation lacks repeated shield-low and shield-medium trials. '
              'Collect interleaved repetitions across strengths and poses, including low sword, relaxed-open holds '
              'and hard negative movements. Keep new wearing sessions separate.', '',
              '## Reproduce', '', '```sh',
              '.venv/bin/python scripts/analyze_micah_patterns.py \\',
              '  --static "Micah contributed data/static/20261108-014551-cf745f65" \\',
              '  --dynamic "Micah contributed data/dynamic/20261108-011407-c127f0d5/original" \\',
              '  --output .local/micah-pattern-analysis', '```', '',
              'Reads raw JSONL or its lossless gzip form. Caches are hash-keyed and stay in the requested output folder. '
              'Matplotlib is needed for the plot. Full scores, fold membership, timing and five-second drift trajectories '
              'are in `pattern-report.json`.']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print('Report:', output/'pattern-report.json', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--static', required=True, type=Path)
    parser.add_argument('--dynamic', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); run(args.static, args.dynamic, args.output)
