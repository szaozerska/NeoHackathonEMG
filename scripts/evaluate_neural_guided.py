#!/usr/bin/env python3
"""Frozen-model EMG-only check against participant-confirmed action counts.

Count agreement is not exact event precision/recall: a missed true snap and a
false event can cancel. No score from this command updates model parameters.
"""
import argparse
from collections import Counter
from pathlib import Path
import numpy as np
from spelltrain.common import read_json, write_json, json_lines
from spelltrain.neural import NeuralEMGPredictor
from spelltrain.neural_data import verify_files, check_trial_coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--capture', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--development', action='store_true')
    args = parser.parse_args(); source = Path(args.capture)
    if Path(args.output).exists():
        parser.error('Output exists; choose a new report path')
    manifest = read_json(source/'guided-manifest.json'); metadata = read_json(source/'metadata.json')
    verify_files(source, manifest['source_hashes'])
    if not metadata.get('recording_complete'):
        parser.error('Capture incomplete')
    runner = NeuralEMGPredictor(args.model)
    training = runner.manifest.get('training_sources')
    if training is None:
        parser.error('Model lacks source provenance; rebuild with the current trainer')
    overlap = any(s.get('directory') == str(source.resolve()) or
                  s.get('wearing_session') == manifest['wearing_session'] for s in training)
    if not args.development and (overlap or metadata.get('dataset_role') != 'untouched_guided_count_check'):
        parser.error('Use a reserved capture from a different wearing session, or explicitly --development')
    raw = [r for r in json_lines(source/'streams.jsonl') if r['kind'] == 'emg']
    if not raw:
        parser.error('No EMG in capture')
    offset = float(np.median([r['packet']['source_uptime']-metadata['started_host_uptime']-r['packet']['source_t']/1e6 for r in raw]))
    predictions = []
    for row in raw:
        predictions.extend(runner.feed(row['packet']))
    trials = []; totals = Counter(); negative_seconds = 0.
    for trial in read_json(source/'guided-trials.json'):
        if not trial['confirmed']:
            continue
        try:
            check_trial_coverage(raw, trial, metadata)
        except ValueError:
            trials.append({**trial, 'scorable': False, 'reason': 'missing_emg'}); continue
        events = [r for r in predictions if r['kind'] == 'neural_event' and r['task'] == 'snap'
                  and trial['start'] <= r['source_t']+offset <= trial['end']]
        if trial['kind'] in ('snap', 'negative'):
            actual = trial['reported_count']; count = len(events)
            trials.append({**trial, 'scorable': True, 'detected_count': count, 'count_error': count-actual,
                           'capture_event_times': [r['source_t']+offset for r in events]})
            totals['count_trials'] += 1; totals['count_matching_trials'] += int(count == actual)
            totals['reported_snaps'] += actual; totals['detected_events'] += count; totals['absolute_count_error'] += abs(count-actual)
            if actual == 0:
                totals['false_events_on_confirmed_negative_clips'] += count
                negative_seconds += trial['end']-trial['start']
        else:
            states = [r['label'] for r in predictions if r['kind'] == 'neural_state' and r['task'] == 'state'
                      and trial['start']+.5 <= r['source_t']+offset <= trial['end']-.15]
            guess = Counter(states).most_common(1)[0][0] if states else 'unknown'
            trials.append({**trial, 'scorable': True, 'predicted_state': guess})
            totals['state_trials'] += 1; totals['correct_state_trials'] += int(guess == trial['kind'])
    result = {'schema': 1, 'role': 'development' if args.development else 'reserved_guided_count_check',
              'model': str(Path(args.model).resolve()), 'capture': str(source.resolve()),
              'wearing_session_overlap': overlap, 'counts': dict(totals), 'trials': trials,
              'negative_seconds': negative_seconds,
              'false_events_per_minute_on_negative_clips': totals['false_events_on_confirmed_negative_clips']/(negative_seconds/60) if negative_seconds else None,
              'exact_event_precision': None, 'exact_event_recall': None,
              'limitations': ['Participant-confirmed counts are weak labels, not independently verified event times.',
                              'Matching counts can conceal simultaneous misses and false events.',
                              'Prompted clips do not establish continuous gameplay performance or 99% accuracy.']}
    write_json(args.output, result)
    print(result['counts']); print('Saved '+args.output)


if __name__ == '__main__':
    main()
