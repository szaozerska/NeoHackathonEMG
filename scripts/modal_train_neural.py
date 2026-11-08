#!/usr/bin/env python3
"""Train the neural EMG models on Modal as a parallel sweep, then download the best model.

Runs only in the expected Modal workspace (personal, never the team one):

    PYTHONPATH=src modal run scripts/modal_train_neural.py --output artifacts/modal/neural-emg-NEXT

New guided captures under --captures are uploaded once to the `neohack-emg-data` volume. One
CPU job builds the guided-only dataset; every architecture/size/seed then trains in its own GPU
container. The best checkpoint per task is saved locally as a normal model directory
(model.json + .pt) that NeuralEMGPredictor loads. Nothing is activated automatically.
"""
import json
import os
import subprocess
import time
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_WORKSPACE = os.environ.get('NEOHACK_MODAL_WORKSPACE', 'sofia-zaozerskaya')
REPO = '/root/repo'

app = modal.App('neohack-emg-train')
volume = modal.Volume.from_name('neohack-emg-data', create_if_missing=True)
image = (modal.Image.debian_slim(python_version='3.11')
         .pip_install('torch==2.6.0', 'numpy>=1.26,<3', 'scipy>=1.11,<2', 'scikit-learn>=1.4,<2', 'joblib>=1.3,<2')
         .env({'PYTHONPATH': REPO+'/src'})
         .add_local_dir(ROOT/'src', REPO+'/src', ignore=['**/__pycache__'])
         .add_local_file(ROOT/'scripts/train_neural_emg.py', REPO+'/scripts/train_neural_emg.py'))

# Meta's DiscreteGesturesArchitecture uses 512 hidden x 3 layers; smaller sizes suit our data volume.
LSTM_SIZES = {'quick': [(128, 2), (256, 2)], 'full': [(64, 2), (128, 2), (256, 2), (512, 3)]}
BASELINES = ['fnn', 'cnn', 'tcn']


@app.function(image=image, volumes={'/vol': volume}, cpu=4, memory=32768, timeout=3600)
def build_dataset(captures, name, interval=(), signal=None):
    import joblib
    from spelltrain.neural_data import guided_only_dataset
    volume.reload()
    data = guided_only_dataset([f'/vol/captures/{c}' for c in captures], [f'/vol/interval/{c}' for c in interval], signal)
    Path('/vol/datasets').mkdir(exist_ok=True)
    joblib.dump(data, f'/vol/datasets/{name}.joblib', compress=3)
    volume.commit()
    return {'signal': data['signal'], 'validation_captures': data['validation_captures'],
            'windows': {task: {part: sum(r['part'] == part for r in rows) for part in ('train', 'validation')}
                        for task, rows in data['tasks'].items()},
            'snap_bags': len(data.get('weak_bags', {}).get('snap', []))}


@app.function(image=image, volumes={'/vol': volume}, gpu='T4', memory=32768, timeout=3600)
def train(run):
    volume.reload()
    out = f"/vol/runs/{run['sweep']}/{run['name']}"
    config_path = '/tmp/config.json'
    Path(config_path).write_text(json.dumps(run['config']))
    started = time.monotonic()
    result = subprocess.run(['python', REPO+'/scripts/train_neural_emg.py', '--config', config_path, '--output', out,
                             '--dataset', f"/vol/datasets/{run['dataset']}.joblib", '--skip-incomplete-tasks'],
                            cwd=REPO, capture_output=True, text=True)
    volume.commit()
    if result.returncode:
        return {'name': run['name'], 'error': result.stderr[-2000:]}
    report = json.loads(Path(out, 'training-report.json').read_text())
    tasks = {}
    for task, entry in report['tasks'].items():
        if entry.get('skipped'):
            tasks[task] = {'skipped': True, 'missing_classes': entry['missing_classes']}
            continue
        chosen = entry['selected']
        tasks[task] = {'checkpoint': chosen['checkpoint'], 'architecture': chosen['architecture'], 'seed': chosen['seed'],
                       'threshold': chosen['threshold'], 'selection_score': chosen['selection_score'],
                       'validation_cross_entropy': chosen['training']['validation_weighted_cross_entropy'],
                       'best_epoch': chosen['training']['best_epoch'], 'parameters': chosen['training']['parameters']}
    return {'name': run['name'], 'directory': out.removeprefix('/vol/'), 'tasks': tasks,
            'seconds': time.monotonic()-started}


def check_workspace():
    info = subprocess.run(['modal', 'token', 'info'], capture_output=True, text=True, check=True).stdout
    workspace = next((line.split(':', 1)[1].split('(')[0].strip() for line in info.splitlines()
                      if line.startswith('Workspace:')), None)
    if workspace != EXPECTED_WORKSPACE:
        raise SystemExit(f'Refusing to run in Modal workspace {workspace!r}; expected {EXPECTED_WORKSPACE!r}')
    print('Modal workspace:', workspace, flush=True)


def upload_interval_captures(root):
    """Space-interval contributions: Micah static/dynamic holds and Animation Gesture (Infinite Void)."""
    kinds = ('static', 'dynamic', 'animation/static', 'animation/dynamic')
    found = sorted(p for kind in kinds for p in (Path(root)/kind).glob('*')
                   if ((p/'truth-values.json').exists() or (p/'original/truth-values.json').exists())
                   and not (p/'DO_NOT_USE.json').exists() and not (p/'DO_NOT_USE.md').exists())
    try:
        present = {Path(e.path).name for e in volume.listdir('interval')}
    except Exception:
        present = set()
    missing = [p for p in found if p.name not in present]
    if missing:
        print(f'Uploading {len(missing)} new interval capture(s)', flush=True)
        with volume.batch_upload() as batch:
            for p in missing:
                batch.put_directory(str(p), f'interval/{p.name}')
    return [p.name for p in found]


def upload_captures(root):
    captures = sorted(p.name for p in Path(root).iterdir() if (p/'guided-trials.json').exists())
    try:
        present = {Path(e.path).name for e in volume.listdir('captures')}
    except Exception:
        present = set()
    missing = [c for c in captures if c not in present]
    if missing:
        print(f'Uploading {len(missing)} new capture(s)', flush=True)
        with volume.batch_upload() as batch:
            for c in missing:
                batch.put_directory(str(Path(root)/c), f'captures/{c}')
    return captures


def sweep_runs(config, sweep_name, dataset, kind, epochs):
    runs = []
    base = {**config, **({'epochs': epochs} if epochs else {})}
    for seed in config['seeds']:
        for hidden, layers in LSTM_SIZES[kind]:
            lstm = {**config.get('lstm', {}), 'conv_channels': hidden, 'hidden': hidden, 'layers': layers}
            runs.append({'name': f'lstm{hidden}x{layers}-seed{seed}',
                         'config': {**base, 'architectures': ['lstm'], 'seeds': [seed], 'lstm': lstm}})
        for architecture in BASELINES:
            runs.append({'name': f'{architecture}-seed{seed}',
                         'config': {**base, 'architectures': [architecture], 'seeds': [seed]}})
    return [{**r, 'sweep': sweep_name, 'dataset': dataset} for r in runs]


@app.local_entrypoint()
def main(output: str, captures: str = 'data/ken/guided', config: str = 'configs/neural-emg.json',
         sweep: str = 'quick', epochs: int = 0, interval_captures: str = 'data/micah',
         windows: str = '', architectures: str = ''):
    """windows: 'state:snap' sample lengths, comma separated (e.g. 410:256,820:512); each gets its own dataset."""
    check_workspace()
    output = Path(output)
    if output.exists():
        raise SystemExit('Output exists; choose a new version')
    names = upload_captures(ROOT/captures)
    sweep_name = time.strftime('%Y%m%d-%H%M%S')
    print('Building dataset from', len(names), 'captures', flush=True)
    interval = upload_interval_captures(ROOT/interval_captures) if interval_captures else []
    print('Interval captures:', interval, flush=True)
    variants = {'': None} if not windows else {
        f'-w{s}-{n}': {'state_window': int(s), 'snap_window': int(n)}
        for s, n in (w.split(':') for w in windows.split(','))}
    datasets = [sweep_name+v for v in variants]
    summaries = list(build_dataset.starmap([(names, d, interval, sig) for d, sig in zip(datasets, variants.values())]))
    summary = dict(zip(datasets, summaries)) if windows else summaries[0]
    print(json.dumps(summary), flush=True)
    runs = []
    for d, v in zip(datasets, variants):
        runs += [{**r, 'name': r['name']+v} for r in sweep_runs(json.loads((ROOT/config).read_text()), sweep_name, d, sweep, epochs)]
    if architectures:
        runs = [r for r in runs if r['name'].split('-')[0].rstrip('0123456789x') in architectures.split(',')]
    print(f'Training {len(runs)} runs in parallel', flush=True)
    results = list(train.map(runs))
    for r in results:
        print(r['name'], r.get('error') or {t: v.get('selection_score', 'skipped') for t, v in r['tasks'].items()}, flush=True)
    output.mkdir(parents=True)
    manifest, best = None, {}
    for r in results:
        for task, entry in r.get('tasks', {}).items():
            if entry.get('skipped'):
                continue
            key = (entry['selection_score'], -entry['validation_cross_entropy'])
            if task not in best or key > best[task][0]:
                best[task] = (key, r, entry)
    tasks = {}
    for task, (_, run, entry) in best.items():
        run_manifest = json.loads(b''.join(volume.read_file(run['directory']+'/model.json')))
        manifest = manifest or run_manifest
        filename = f"{task}-{run['name']}.pt"
        (output/filename).write_bytes(b''.join(volume.read_file(run['directory']+'/'+entry['checkpoint'])))
        tasks[task] = {**run_manifest['tasks'][task], 'checkpoint': filename}
    if manifest:
        (output/'model.json').write_text(json.dumps({**manifest, 'tasks': tasks, 'modal_sweep': sweep_name}, indent=2))
    (output/'sweep.json').write_text(json.dumps({'sweep': sweep_name, 'dataset': summary, 'runs': results}, indent=2))
    print('Best per task:', {t: (r['name'], e['selection_score']) for t, (_, r, e) in best.items()})
    print('Saved', output.resolve())
