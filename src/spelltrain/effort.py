"""Personalized shield effort baseline from confirmed, versioned open-hand trials.

Effort classes are participant reports, not measurements of contact force.
"""
from __future__ import annotations
from bisect import bisect_right
from collections import Counter
from importlib.metadata import version
from pathlib import Path
import csv
import hashlib
import json
import platform

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from .common import json_lines, read_json, write_json
from .signals import DEFAULT_SIGNAL, SignalWindows

LEVELS = ('light', 'medium', 'firm')
from .shield_training import PROTOCOL, LABEL_FILE
CANDIDATES = {'log_rms': 8, 'log_amplitude': 24}


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def sensor_times(row, fs=2048):
    """Sensor sample clock, not Bluetooth delivery time; packet timestamp is its end."""
    if 'source_t' not in row or 'source_seq' not in row:
        raise ValueError('Effort training requires Kinesis sensor timestamp and sequence')
    samples = np.asarray(row['samples'], dtype=float)
    if samples.ndim != 2 or samples.shape[1] != 8 or not len(samples):
        raise ValueError('Expected eight EMG channels')
    end = float(row['source_t'])/1e6
    if not np.isfinite(end):
        raise ValueError('Invalid sensor timestamp')
    return end - np.arange(len(samples)-1, -1, -1)/fs


def effort_dataset(directory, margin=.75, signal=None, include_snap=False,
                   label_file=LABEL_FILE, expected_protocol=PROTOCOL, alignment='received',
                   include_waveforms=False):
    directory = Path(directory)
    meta = read_json(directory/'metadata.json')
    if meta.get('synthetic') or meta.get('incomplete'):
        raise ValueError('Use a complete real recording for this effort model')
    if not meta.get('recording_closed'):
        raise ValueError('Finish the recording before training a reproducible model')
    source = directory/label_file
    all_trials = read_json(source)
    trials = sorted([r for r in all_trials if r.get('confirmed') is True and r.get('received') is True],
                    key=lambda r:r['start'])
    if not trials or any(r.get('protocol') != expected_protocol for r in trials):
        raise ValueError('Expected confirmed '+expected_protocol+' trials')
    if len({r['motion'] for r in trials}) != len(trials):
        raise ValueError('Duplicate accepted protocol trials; review them first')
    starts = [r['start']-.75 for r in trials]
    buckets = [[] for _ in trials]
    for row in json_lines(directory/'streams.jsonl'):
        if row.get('kind') != 'emg':
            continue
        i = bisect_right(starts, row['received'])-1
        if i >= 0 and row['received'] <= trials[i]['end']+.25:
            buckets[i].append(row)
    config = DEFAULT_SIGNAL | (signal or {})
    records, quality = [], []
    for trial, rows in zip(trials, buckets):
        if not rows:
            raise ValueError('No raw EMG for confirmed trial '+trial['motion'])
        # Approximate sensor -> recorder time mapping per trial. This affects label inclusion,
        # not feature values. Button boundaries are deliberately trimmed on both sides.
        if alignment == 'source_uptime':
            host_times = [r['source_uptime']-meta['origin_monotonic'] for r in rows]
        elif alignment == 'received':
            host_times = [r['received'] for r in rows]
        else:
            raise ValueError('Unknown sensor/host alignment method')
        offset = float(np.median([t-float(r['source_t'])/1e6 for t,r in zip(host_times,rows)]))
        timing_residual = np.array([t-(float(r['source_t'])/1e6+offset) for t,r in zip(host_times,rows)])
        if np.max(np.abs(timing_residual)) > margin:
            raise ValueError('Delivery timing exceeds the edge margin for '+trial['motion'])
        windows = SignalWindows(config, include_waveforms=include_waveforms)
        last_seq = None
        gaps, emitted = 0, 0
        for row in rows:
            if last_seq is not None and row['source_seq'] != last_seq+1:
                windows.reset(); gaps += 1
            last_seq = row['source_seq']
            times = sensor_times(row, config['sample_rate'])
            for feature in windows.feed(row['samples'], times):
                if feature['kind'] != 'state' and not include_snap:
                    continue
                start, end = feature['start']+offset, feature['t']+offset
                if start >= trial['start']+margin and end <= trial['end']-margin:
                    records.append({'trial':trial['motion'], 'result_id':trial['id'], 'round':trial['repetition'],
                                    'condition':trial['condition'], 'effort':trial['intended_effort'],
                                    'movement':trial['intended_movement'], 'hand_state':trial['hand_state'],
                                    'start':start, 'end':end, 'kind':feature['kind'], 'x':feature['x']})
                    if include_waveforms:
                        records[-1]['waveform'] = feature['waveform']
                    emitted += 1
        quality.append({'trial':trial['motion'], 'round':trial['repetition'], 'condition':trial['condition'],
                        'raw_batches':len(rows), 'sequence_discontinuities':gaps, 'feature_windows':emitted,
                        'button_duration_seconds':trial['end']-trial['start'],
                        'timing_residual_abs_max_seconds':float(np.max(np.abs(timing_residual))),
                        'alignment':alignment, 'sensor_to_session_offset_seconds':offset,
                        'transport_gap_flags_ignored':sum(bool(r.get('gap')) for r in rows)})
        if emitted < 10:
            raise ValueError('Too few usable windows for '+trial['motion'])
    manifest = {'session_id':meta['id'], 'subject':meta['subject'], 'side':meta['side'],
                'directory':str(directory.resolve()), 'streams_sha256':_hash(directory/'streams.jsonl'),
                'labels_sha256':_hash(source), 'metadata_sha256':_hash(directory/'metadata.json')}
    return records, quality, manifest, config


def is_shield(row):
    return (row['condition'] in {f'shield-{level}-{movement}' for level in LEVELS for movement in ('center','left','right')}
            and row['hand_state'] == 'open' and row['effort'] in LEVELS)


def split_rounds(records):
    parts = {name:[r for r in records if is_shield(r) and r['round']==round_]
             for name,round_ in (('train',1),('validation',2),('test',3))}
    for name,rows in parts.items():
        counts = Counter({r['trial']:r['effort'] for r in rows}.values())
        if any(counts[level] != 3 for level in LEVELS):
            raise ValueError(name+' needs three complete independent trials per effort level')
    groups = [{r['trial'] for r in rows} for rows in parts.values()]
    if any(groups[i] & groups[j] for i in range(3) for j in range(i)):
        raise ValueError('Trials overlap across the evaluation split')
    return parts


def _x(rows, columns):
    return np.array([r['x'][:columns] for r in rows])


def _ordered_prob(model, x):
    probability = model.predict_proba(x)
    return probability[:, [list(model.classes_).index(level) for level in LEVELS]]


def evaluate_effort(model, rows, columns):
    probabilities = _ordered_prob(model, _x(rows, columns))
    actual = [r['effort'] for r in rows]
    window_predictions = np.array(LEVELS)[probabilities.argmax(axis=1)]
    trials = []
    for key in dict.fromkeys(r['trial'] for r in rows):
        indices = [i for i,r in enumerate(rows) if r['trial']==key]
        p = probabilities[indices].mean(axis=0)
        first = rows[indices[0]]
        trials.append({'trial':key, 'round':first['round'], 'movement':first['movement'],
                       'actual':first['effort'], 'predicted':LEVELS[int(p.argmax())],
                       'probabilities':dict(zip(LEVELS,p.tolist())), 'windows':len(indices)})
    truth, predicted = [r['actual'] for r in trials], [r['predicted'] for r in trials]
    correct = sum(a==b for a,b in zip(truth,predicted)); n=len(trials)
    z=1.96; center=(correct/n+z*z/(2*n))/(1+z*z/n)
    half=z*np.sqrt((correct/n)*(1-correct/n)/n+z*z/(4*n*n))/(1+z*z/n)
    return {'trial_count':n,'correct_trials':correct,'trial_accuracy':float(accuracy_score(truth,predicted)),
            'trial_macro_f1':float(f1_score(truth,predicted,labels=LEVELS,average='macro',zero_division=0)),
            'confusion_matrix':confusion_matrix(truth,predicted,labels=LEVELS).tolist(),
            'ordinal_mean_absolute_error':float(np.mean([abs(LEVELS.index(a)-LEVELS.index(b)) for a,b in zip(truth,predicted)])),
            'trial_accuracy_wilson_95_interval':[float(center-half),float(center+half)],
            'window_count':len(rows),'window_accuracy':float(accuracy_score(actual,window_predictions)),
            'trials':trials}


def fit_effort(directory, output):
    output=Path(output)
    if output.exists():
        raise ValueError('Output already exists; choose a new effort model version')
    records,quality,manifest,config=effort_dataset(directory)
    parts=split_rounds(records)
    training=parts['train']; labels=[r['effort'] for r in training]
    counts=Counter(r['trial'] for r in training)
    weights=np.array([1/counts[r['trial']] for r in training]);weights *= len(weights)/weights.sum()
    models,validation={},{}
    for name,columns in CANDIDATES.items():
        model=make_pipeline(FunctionTransformer(np.log1p),StandardScaler(),
                            LogisticRegression(C=.1,max_iter=2000,random_state=7))
        model.fit(_x(training,columns),labels,logisticregression__sample_weight=weights)
        models[name]=model
        validation[name]=evaluate_effort(model,parts['validation'],columns)
    # Ties prefer the simpler eight-channel RMS model. Test labels do not select anything.
    selected=max(CANDIDATES,key=lambda name:validation[name]['trial_macro_f1'])
    model=models[selected];columns=CANDIDATES[selected]
    test=evaluate_effort(model,parts['test'],columns)
    controls=[]
    control_rows=[r for r in records if not is_shield(r)]
    for key in dict.fromkeys(r['trial'] for r in control_rows):
        rows=[r for r in control_rows if r['trial']==key]
        p=_ordered_prob(model,_x(rows,columns)).mean(axis=0)
        controls.append({'trial':key,'condition':rows[0]['condition'],'predicted':LEVELS[int(p.argmax())],
                         'probabilities':dict(zip(LEVELS,p.tolist()))})
    report={'schema':1,'task':'shield_relative_emg_effort','protocol':PROTOCOL,
            'subject':manifest['subject'],'side':manifest['side'],'levels':list(LEVELS),
            'source':manifest,'selected_candidate':selected,'feature_columns':columns,'signal':config,
            'edge_margin_seconds':.75,'window_seconds':config['state_window']/config['sample_rate'],
            'hop_seconds':config['state_hop']/config['sample_rate'],
            'timing':'Sensor microsecond timestamps preserve sample spacing; per-trial median receive offset approximates button alignment. Edges trimmed 0.75 seconds. No response-latency claim.',
            'split':{name:{'round':i,'trials':sorted({r['trial'] for r in parts[name]}),'windows':len(parts[name])}
                     for name,i in (('train',1),('validation',2),('test',3))},
            'validation_candidates':validation,'test':test,'quality':quality,
            'control_predictions_diagnostic_only':controls,
            'limitations':['Single subject and single band-wearing session; round 3 is held out but is not an independent session.',
                          'Only nine test trials (three per level); overlapping windows are not independent trials.',
                          'Labels are participant-reported light/medium/firm effort, not measured force or physical impulse.',
                          'Trial scores average window probabilities offline; they do not measure live response accuracy.',
                          'This three-class model always predicts an effort class, including on non-shield controls. It requires a separate open-hand/spell/tracking gate.',
                          'No Quest pose verification, calibrated shield power curve, sword detector, or fireball model is trained here.',
                          'Artifact is fitted on round 1 only; round 2 selects features and round 3 is evaluation only.'],
            'versions':{'python':platform.python_version(),**{k:version(k) for k in ('numpy','scipy','scikit-learn','joblib')}}}
    artifact={'schema':1,'task':report['task'],'protocol':PROTOCOL,'model':model,'feature_columns':columns,
              'levels':LEVELS,'signal':config,'report':report}
    output.mkdir(parents=True,exist_ok=False)
    joblib.dump(artifact,output/'effort-model.joblib')
    write_json(output/'training-report.json',report)
    with (output/'test-predictions.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['trial','movement','actual','predicted','windows'])
        writer.writeheader();writer.writerows([{k:r[k] for k in writer.fieldnames} for r in test['trials']])
    lines=['# Shield EMG effort baseline','',f"Subject: {manifest['subject']}; session: {manifest['session_id']}",
           f"Selected model: {selected}; training round 1, validation round 2, test round 3.",'',
           f"Held-out trial accuracy: {test['correct_trials']}/{test['trial_count']} ({test['trial_accuracy']:.1%}).",
           f"Trial macro F1: {test['trial_macro_f1']:.3f}. Window accuracy: {test['window_accuracy']:.1%}.",
           '', 'Confusion matrix: rows are actual effort; columns are predicted effort.', '',
           '| Actual / predicted | Light | Medium | Firm |','|---|---:|---:|---:|']
    lines += ['| '+level+' | '+' | '.join(map(str,row))+' |' for level,row in zip(LEVELS,test['confusion_matrix'])]
    lines += ['','## Limits','']+['- '+text for text in report['limitations']]
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return report


class EffortPredictor:
    """Causal effort-only output. Caller must supply separate hand/spell/motion gates."""
    def __init__(self, artifact):
        if artifact.get('task') != 'shield_relative_emg_effort' or artifact.get('protocol') != PROTOCOL:
            raise ValueError('Not a compatible shield effort artifact')
        self.artifact=artifact
        self.windows=SignalWindows(artifact['signal'])
        self.last_seq=None

    def feed(self,row):
        if row.get('kind') != 'emg':return []
        if self.last_seq is not None and row['source_seq'] != self.last_seq+1:self.windows.reset()
        self.last_seq=row['source_seq']
        out=[]
        for window in self.windows.feed(row['samples'],sensor_times(row,self.artifact['signal']['sample_rate'])):
            if window['kind'] != 'state':continue
            p=_ordered_prob(self.artifact['model'],np.array([window['x'][:self.artifact['feature_columns']]]))[0]
            out.append({'kind':'effort','source_t':window['t'],'label':LEVELS[int(p.argmax())],
                        'probabilities':dict(zip(LEVELS,p.tolist())),
                        'effort_index':float(p @ np.array([0.,.5,1.])),
                        'effort_index_meaning':'0=light, 0.5=medium, 1=firm; not force or shield strength'})
        return out
