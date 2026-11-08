"""Stricter, signal-quality-only selection of training intervals from a Space-interval capture.

Builds on the validation filter (`quality-filter.json`) and writes, under `<capture>/analysis/`:

- `training-selection.json`: every interval with `train_eligible` and the reasons it was dropped.
- `reference-quality.json`: the EMG envelope peak of each eligible snap (`label_index`, `peak_capture_t`), the
  expected event used to score snap windows outside the training part.
- `review-candidates.json`: snap-sized bursts inside non-intended time; nearby windows are never used as negatives.

No model predictions are used and no label or timestamp is changed.

    python -m spelltrain.training_selection data/sophie/<capture>
"""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np
from scipy import signal

from . import validation_filter as vf
from .dataset_policy import require_usable_capture

MIN_HOLD_S = 0.7
"""Shortest interval that still yields one 400 ms state window after the 0.15 s edge margins."""
MAX_CLIPPED_SHARE = 0.10
"""Holds and snaps with more of their samples at the ADC limits than this are dropped (flat-topped signal)."""
SNAP_PEAK_OF_MOVEMENT = 3.0
"""A snap's envelope peak must reach this multiple of the median non-intended movement level."""
MIN_PATTERN_CORR = 0.5
"""Channel pattern must correlate this well with the class median pattern (wrong or half-formed gesture otherwise)."""
MAX_HOLD_BURSTS = 2


def _channel_filtered(path: Path) -> np.ndarray:
    batches, seqs = [], []
    with (gzip.open if path.suffix == '.gz' else open)(path, 'rt') as f:
        for line in f:
            if line.startswith('{"kind":"emg"'):
                packet = json.loads(line)['packet']
                batches.append(np.asarray(packet['samples'], float)); seqs.append(packet['source_seq'])
    raw = np.concatenate(batches); per = len(batches[0])
    edges = np.r_[0, (np.flatnonzero(np.diff(seqs) != 1)+1)*per, len(raw)]
    out = np.zeros_like(raw)
    for a, b in zip(edges[:-1], edges[1:]):
        seg = raw[a:b]-raw[a:b][:min(256, b-a)].mean(0)
        for sos in vf.FILTERS:
            seg = signal.sosfilt(sos, seg, axis=0)
        out[a:b] = signal.lfilter(*vf.NOTCH, seg, axis=0)
    return out


def interval_metrics(stream: dict, filtered: np.ndarray, decisions: list[dict]) -> list[dict]:
    t, env, clipped = stream['t'], stream['envelope'], stream['clipped']
    span = lambda a, b: slice(*np.searchsorted(t, [a, b]))
    rows = []
    for d in decisions:
        a, b = d['start'], d['end']; s = span(a, b); e = env[s]
        r = {'index': d['index'], 'motion': d['motion'] or 'non_intended', 'effort': d['effort'], 'start': a, 'end': b,
             'filter_kept': d['decision'] == 'kept', 'filter_reasons': d['reasons'],
             'clipped_share': float(clipped[s].mean()) if e.size else 0.}
        if e.size and np.isfinite(e).any():
            coarse = np.nan_to_num(e[::32])
            peaks, _ = signal.find_peaks(coarse, prominence=.35*coarse.max(), distance=8)
            r.update(median=float(np.nanmedian(e)), peak=float(np.nanmax(e)), bursts=len(peaks))
            if r['motion'] == 'snap':
                r['peak_capture_t'] = float(t[s][int(np.nanargmax(e))])
                w = span(r['peak_capture_t']-.1, r['peak_capture_t']+.1)
            else:
                w = span(a+.15, b-.15) if b-a > .4 else s
            x = filtered[w]
            if len(x):
                r['pattern'] = np.log(np.sqrt((x**2).mean(0))+1e-6).tolist()
        rows.append(r)
    return rows


def select(rows: list[dict]) -> list[dict]:
    movement = float(np.median([r['median'] for r in rows if r['motion'] == 'non_intended' and r['filter_kept']
                                and 'median' in r]))
    corr = {}
    for motion in {r['motion'] for r in rows} - {'non_intended'}:
        group = [r for r in rows if r['motion'] == motion and r['filter_kept'] and 'pattern' in r]
        if not group:
            continue
        p = np.array([r['pattern'] for r in group], float); p -= p.mean(1, keepdims=True); centre = np.median(p, 0)
        corr.update({r['index']: float(np.corrcoef(v, centre)[0, 1]) for r, v in zip(group, p)})
    for r in rows:
        why = [f'validation filter: {x}' for x in r['filter_reasons']]
        if 'pattern' not in r and not why:
            why.append('no usable signal')
        if r['motion'] != 'non_intended' and not why:
            r['pattern_corr'] = corr.get(r['index'])
            if r['end']-r['start'] < MIN_HOLD_S:
                why.append(f'shorter than {MIN_HOLD_S} s (no full state window)')
            if r['clipped_share'] > MAX_CLIPPED_SHARE:
                why.append(f'more than {MAX_CLIPPED_SHARE:.0%} of samples clipped')
            if r['pattern_corr'] is not None and r['pattern_corr'] < MIN_PATTERN_CORR:
                why.append('channel pattern unlike the rest of this gesture')
            if r['motion'] == 'snap':
                if r['bursts'] != 1:
                    why.append('not exactly one burst')
                if r['peak'] < SNAP_PEAK_OF_MOVEMENT*movement:
                    why.append(f'peak below {SNAP_PEAK_OF_MOVEMENT:g}x the movement level')
            elif r['bursts'] > MAX_HOLD_BURSTS:
                why.append('several separate bursts inside the hold')
        r['train_eligible'] = not why; r['reasons'] = why
        r.pop('pattern', None)
    return rows


def select_capture(directory: Path) -> dict:
    directory = Path(directory)
    require_usable_capture(directory)
    quality = directory/'quality-filter.json'
    if not quality.exists():
        vf.filter_capture(directory)
    decisions = json.loads(quality.read_text())['intervals']
    path = vf.stream_path(directory)
    rows = select(interval_metrics(vf.load_stream(path), _channel_filtered(path), decisions))
    analysis = directory/'analysis'; analysis.mkdir(exist_ok=True)
    rules = {'min_hold_seconds': MIN_HOLD_S, 'max_clipped_share': MAX_CLIPPED_SHARE,
             'snap_peak_of_movement_median': SNAP_PEAK_OF_MOVEMENT, 'min_pattern_corr': MIN_PATTERN_CORR,
             'max_hold_bursts': MAX_HOLD_BURSTS}
    summary = {}
    for r in rows:
        s = summary.setdefault(r['motion'], {'intervals': 0, 'train_eligible': 0, 'dropped': {}})
        s['intervals'] += 1; s['train_eligible'] += r['train_eligible']
        for why in r['reasons']:
            s['dropped'][why] = s['dropped'].get(why, 0)+1
    report = {'schema': 1, 'session_id': directory.name, 'method': 'signal quality only', 'model_predictions_used': False,
              'labels_or_timestamps_changed': False, 'rules': rules, 'summary': summary, 'intervals': rows}
    (analysis/'training-selection.json').write_text(json.dumps(report, indent=1)+'\n')
    (analysis/'reference-quality.json').write_text(json.dumps(
        [{'label_index': r['index'], 'peak_capture_t': r['peak_capture_t'], 'interval_start': r['start'],
          'interval_end': r['end'], 'source': 'emg_envelope_peak'} for r in rows
         if r['motion'] == 'snap' and r['train_eligible']], indent=1)+'\n')
    (analysis/'review-candidates.json').write_text(json.dumps(
        [{'capture_t_seconds': r['peak_capture_t'] if 'peak_capture_t' in r else (r['start']+r['end'])/2,
          'label_index': r['index'], 'original_label': 'non_intended', 'category': 'unlabeled_snap_like_burst'}
         for r in rows if r['motion'] == 'non_intended' and any('burst' in x for x in r['filter_reasons'])], indent=1)+'\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('capture', type=Path)
    report = select_capture(parser.parse_args(argv).capture)
    print(json.dumps(report['summary'], indent=1))


if __name__ == '__main__':
    main()
