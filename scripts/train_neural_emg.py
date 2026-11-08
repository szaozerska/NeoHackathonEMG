#!/usr/bin/env python3
"""Versioned, isolated FNN/CNN/LSTM development comparison; never switches live model."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import time
import joblib
import numpy as np
import torch
from spelltrain.common import read_json, write_json
from spelltrain.effort import _hash
from spelltrain.neural_data import (build_dataset, add_reviewed_examples, add_guided_capture, validate_dataset,
                                    guided_only_dataset)
from spelltrain.neural import (fit_classifier, NeuralClassifier, classification_metrics,
                              event_scores, select_threshold)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/neural-emg.json')
    parser.add_argument('--output', required=True)
    parser.add_argument('--reference-cache', default='artifacts/player-a/reference-review-v4/features.joblib')
    parser.add_argument('--reference-review', default='artifacts/player-a/reference-review-v4/reviewed-labels.json')
    parser.add_argument('--review', action='append', default=[], help='Previously reviewed labels; no camera at inference or new camera collection')
    parser.add_argument('--examples', action='append', default=[], help='Additional independently reviewed neural example manifests')
    parser.add_argument('--dataset', help='Reuse a locally generated trusted neural-dataset.joblib')
    parser.add_argument('--guided-capture', action='append', default=[], help='EMG-only participant-confirmed training clips')
    parser.add_argument('--epochs', type=int)
    parser.add_argument('--guided-only', action='store_true',
                        help='Build the dataset from --guided-capture clips alone (no reference review); whole captures are held out')
    parser.add_argument('--skip-incomplete-tasks', action='store_true',
                        help='Skip a task whose training data lacks a registered class instead of failing')
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error('Output exists; choose a new version')
    config = read_json(args.config)
    if args.epochs is not None:
        config['epochs'] = args.epochs
    if config['epochs'] < 1 or config['patience'] < 1:
        parser.error('Epochs and patience must be positive')
    for spec in config['tasks'].values():
        labels = spec['classes']
        if len(labels) < 2 or len(set(labels)) != len(labels) or 'unknown' in labels or spec['background'] not in labels:
            parser.error('Classes must be unique, include background, and reserve unknown for rejection')
        if 'event_class' in spec and (spec['event_class'] not in labels or spec['event_class'] == spec['background']):
            parser.error('Event class must be a registered non-background class')
    torch.set_num_threads(4)
    output.mkdir(parents=True, exist_ok=False)
    backup = output/'backups'; backup.mkdir()
    baselines = {}
    for version in ('v4', 'v6'):
        source = Path(f'artifacts/player-a/gestures-{version}/model.joblib')
        if source.exists():
            target = backup/f'gestures-{version}.joblib'; shutil.copy2(source, target)
            baselines[version] = {'source': str(source.resolve()), 'backup': str(target.resolve()), 'sha256': _hash(source)}
            if _hash(target) != baselines[version]['sha256']:
                raise ValueError('Backup hash mismatch')
    write_json(output/'backup-manifest.json', baselines)
    write_json(output/'config.json', config)
    print('Preserved fallback models. Rebuilding source-checked EMG dataset.', flush=True)
    guided = list(args.guided_capture)
    if args.dataset:
        data = joblib.load(args.dataset)
    elif args.guided_only:
        data = guided_only_dataset(guided); guided = []
    else:
        data = build_dataset(args.reference_cache, args.reference_review, args.review)
    for path in args.examples:
        add_reviewed_examples(data, path, config)
    for path in guided:
        add_guided_capture(data, path)
    validate_dataset(data)
    if not args.dataset:
        joblib.dump(data, output/'neural-dataset.joblib', compress=3)
    report = {'schema': 1, 'evaluation_role': data['evaluation_role'], 'automatically_activated': False,
              'config': config, 'sources': data['sources'], 'baselines': baselines,
              'torch_version': str(torch.__version__), 'input_modalities': ['emg'], 'tasks': {},
              'augmentation': 'training_only_log_normal_global_gain_sigma_0.20; no synthetic rotation',
              'limitations': [
                  'Historical check clips were examined in earlier development; these are regression checks, not fresh independent benchmarks.',
                  'Train/validation/check share wearing sessions. No 99% accuracy claim or unseen-person generalization.',
                  'Repeated overlapping windows are not independent trials. Segment averages do not measure live response accuracy.',
                  'Approximate reviewed snap times use 250ms event matching, not measured hardware latency.',
                  'Softmax confidence is uncalibrated; unknown rejection is not a guarantee of out-of-distribution detection.',
                  'Gain augmentation does not simulate real wrist rotation, electrode repositioning or all soft/firm snap variation.',
                  'Effort remains in the preserved classical model and is not retrained by this experiment.']}
    selected = {}; all_candidates = {}; start = time.monotonic()
    for task, spec in config['tasks'].items():
        rows = data['tasks'][task]
        labeled = lambda part: [r for r in rows if r['part'] == part and r['label'] is not None]
        training, validation = labeled('train'), labeled('validation')
        bag_classes = {spec['event_class']} if 'event_class' in spec and data.get('weak_bags', {}).get(task) else set()
        missing = set(spec['classes'])-{r['label'] for r in training}-bag_classes
        if args.skip_incomplete_tasks and (missing or not validation):
            print(f'Skipping {task}: no training windows for {sorted(missing)}' if missing else f'Skipping {task}: no validation windows', flush=True)
            report['tasks'][task] = {'skipped': True, 'missing_classes': sorted(missing)}
            continue
        if any(r['label'] not in spec['classes'] for r in training+validation):
            raise ValueError('Dataset labels absent from registry')
        # Event replay includes ambiguous windows, never using their labels for fitting.
        selection_rows = [r for r in rows if r['part'] == 'validation'] if 'event_class' in spec else validation
        candidates = []
        for architecture in config['architectures']:
            for seed in config['seeds']:
                print(f'Training {task}: {architecture}, seed {seed}, {len(training)} fitting windows', flush=True)
                weak_bags = data.get('weak_bags', {}).get(task, [])
                _, checkpoint, _, training_report = fit_classifier(training, validation, spec, architecture, config, seed, weak_bags)
                predictor = NeuralClassifier(checkpoint)
                p = predictor.predict_rows(selection_rows)
                threshold, score, validation_report = select_threshold(selection_rows, p, spec)
                name = f'{task}-{architecture}-seed{seed}.pt'
                torch.save(checkpoint, output/name)
                candidates.append({'checkpoint': name, 'architecture': architecture, 'seed': seed,
                                   'threshold': threshold, 'selection_score': score,
                                   'validation': validation_report, 'training': training_report})
                print(f'  validation selection score: {score:.4f}, epoch {training_report["best_epoch"]}', flush=True)
        chosen = max(candidates, key=lambda c: (c['selection_score'], -c['training']['validation_weighted_cross_entropy']))
        selected[task] = {**spec, 'checkpoint': chosen['checkpoint'], 'threshold': chosen['threshold']}
        all_candidates[task] = candidates
        report['tasks'][task] = {'selected': copy.deepcopy(chosen), 'candidates': candidates,
                                 'weak_training_bags': len(data.get('weak_bags', {}).get(task, [])),
                                 'counts': {part: len(labeled(part)) for part in ('train', 'validation', 'test')}}
    # Freeze the selected checkpoints and thresholds before any check scoring.
    manifest = {'schema': 1, 'task': 'neural_emg_only', 'signal': data['signal'], 'tasks': selected,
                'spell_mapping': config.get('spell_mapping', {}), 'automatically_activated': False,
                'training_sources': data['sources']}
    write_json(output/'model.json', manifest)
    write_json(output/'frozen-before-check.json', {'model_sha256': _hash(output/'model.json'),
               'checkpoints': {c['checkpoint']: _hash(output/c['checkpoint']) for candidates in all_candidates.values() for c in candidates}})
    failures = []
    for task, spec in config['tasks'].items():
        rows = [r for r in data['tasks'][task] if r['part'] == 'test' and ('event_class' in spec or r['label'] is not None)]
        if task not in selected or not rows:
            continue
        def evaluate(p, threshold):
            if 'event_class' in spec:
                return event_scores(rows, p[:, spec['classes'].index(spec['event_class'])], threshold, spec['event_class'], spec['background'])
            return classification_metrics(rows, p, spec['classes'], threshold)
        for candidate in all_candidates[task]:
            p = NeuralClassifier(output/candidate['checkpoint']).predict_rows(rows)
            candidate['development_check'] = evaluate(p, candidate['threshold'])
        chosen = selected[task]; p = NeuralClassifier(output/chosen['checkpoint']).predict_rows(rows)
        report['tasks'][task]['selected']['development_check'] = evaluate(p, chosen['threshold'])
        report['tasks'][task]['baseline_checks'] = {}
        for version, info in baselines.items():
            baseline = joblib.load(info['backup']); x = np.array([r['x'] for r in rows])
            if task == 'state':
                model = baseline['state_model']; oldp = model.predict_proba(x[:, :baseline['state_columns']])
                if set(spec['classes']) != set(model.classes_):
                    report['tasks'][task]['baseline_checks'][version] = {'available': False, 'reason': 'Baseline vocabulary differs'}
                    continue
                oldp = oldp[:, [list(model.classes_).index(c) for c in spec['classes']]]
                metric = evaluate(oldp, baseline['state_threshold'])
            elif task == 'snap':
                scores = baseline['snap_model'].window_scores(x)
                metric = event_scores(rows, scores, baseline['snap_threshold'])
            else:
                continue
            report['tasks'][task]['baseline_checks'][version] = metric
        for row, scores in zip(rows, p):
            predicted = spec['classes'][int(scores.argmax())] if max(scores) >= chosen['threshold'] else 'unknown'
            if row['label'] is not None and predicted != row['label']:
                failures.append({'task': task, 'session': row['session'], 'group': row['group'],
                                 'start': row['start'], 'end': row['end'], 'reviewed_label': row['label'],
                                 'predicted': predicted, 'score': float(max(scores)), 'eligible_for_automatic_training': False})
    report['seconds'] = time.monotonic()-start
    write_json(output/'training-report.json', report)
    write_json(output/'failure-review-queue.json', {'role': 'known_check_errors_do_not_auto_refit', 'windows': failures})
    lines = ['# Neural EMG experiment', '', 'Known development regression checks; not independent-session accuracy.', '',
             '| Task | Selected architecture | Check | v4 fallback |', '|---|---|---|---|']
    for task, result in report['tasks'].items():
        if 'development_check' not in result.get('selected', {}):
            continue
        s = result['selected']; m = s['development_check']; old = result['baseline_checks'].get('v4', {})
        if 'event_class' in config['tasks'][task]:
            text = f"TP {m['tp']}, FP {m['fp']}, FN {m['fn']}"; oldtext = f"TP {old.get('tp')}, FP {old.get('fp')}, FN {old.get('fn')}"
        else:
            text = f"window {m['window_accuracy']:.1%}, segment {m['segment_accuracy']:.1%}"; oldtext = f"window {old.get('window_accuracy', 0):.1%}, segment {old.get('segment_accuracy', 0):.1%}"
        lines.append(f"| {task} | {s['architecture']} (seed {s['seed']}) | {text} | {oldtext} |")
    lines += ['', 'Both classical models were copied and hash-checked. Neural models are experimental and were not activated.', '', *report['limitations']]
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[:8]), flush=True)
    print('Saved experiment: '+str(output.resolve()), flush=True)


if __name__ == '__main__':
    main()
