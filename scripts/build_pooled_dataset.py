#!/usr/bin/env python3
"""Build the pooled Ken/Micah/Sophie train/validation/test dataset (joblib) for scripts/train_neural_emg.py --dataset.

    PYTHONPATH=src python scripts/build_pooled_dataset.py --output artifacts/pooled/dataset.joblib --windows 820:328
"""
import argparse
import collections
import json
from pathlib import Path

import joblib

from spelltrain.dataset_policy import require_usable_capture
from spelltrain.neural_data import pooled_split_dataset

ROOT = Path(__file__).resolve().parents[1]
INTERVAL_GLOBS = ['data/micah/static/*', 'data/micah/dynamic/*', 'data/micah/animation/static/*', 'data/sophie/*']


def usable(path):
    try:
        require_usable_capture(path)
        return (path/'metadata.json').exists() or (path/'original/metadata.json').exists()
    except ValueError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--guided-root', default='data/ken/guided')
    parser.add_argument('--interval', action='append', help='Interval capture directories (default: all usable)')
    parser.add_argument('--windows', default='820:328', help='state:snap window samples')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--fractions', default='0.7,0.15,0.15')
    parser.add_argument('--chunk-seconds', type=float, default=3.)
    args = parser.parse_args()
    guided = sorted(p for p in (ROOT/args.guided_root).iterdir() if (p/'guided-trials.json').exists())
    interval = [Path(p) for p in args.interval] if args.interval else sorted(
        p for g in INTERVAL_GLOBS for p in ROOT.glob(g) if p.is_dir() and usable(p))
    state, snap = map(int, args.windows.split(':'))
    data = pooled_split_dataset(guided, interval, args.seed, tuple(map(float, args.fractions.split(','))),
                                args.chunk_seconds, {'state_window': state, 'snap_window': snap})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(data, args.output, compress=3)
    summary = collections.Counter()
    for task, rows in data['tasks'].items():
        for r in rows:
            summary[(task, r['wearing_session'][:10], str(r['label']), r['part'])] += 1
    groups = collections.Counter((r['wearing_session'][:10], str(r['label']), r['part'])
                                 for r in data['tasks']['state'] for r in [r])
    print(json.dumps({'sources': [s['directory'] for s in data['sources']],
                      'weak_snap_bags': len(data.get('weak_bags', {}).get('snap', []))}, indent=1))
    for k in sorted(summary):
        print(*k, summary[k])
    print('Saved', args.output)


if __name__ == '__main__':
    main()
