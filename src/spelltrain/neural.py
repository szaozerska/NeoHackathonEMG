"""Optional PyTorch EMG experiments. No camera inputs or spell logic.

The same classifier factory supports any registered vocabulary. New spells can
reuse gestures; new gestures require examples and a new versioned checkpoint.
"""
from collections import Counter
import time
import numpy as np
import torch
from torch import nn
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from .evaluation import event_metrics


LSTM_DEFAULTS = {'conv_channels': 128, 'kernel_width': 21, 'stride': 10, 'hidden': 128, 'layers': 2,
                 'compression_range': 4., 'compression_midpoint': 4., 'rotation': 1, 'channel_gain': .1, 'noise': .05,
                 'learning_rate': 5e-4, 'warmup_epochs': 5, 'warmup_start_factor': .001,
                 'lr_milestones': [25], 'lr_factor': .5, 'gradient_clip': .5}


def lstm_settings(config):
    return {**LSTM_DEFAULTS, **(config or {}).get('lstm', {})}


class ReinhardCompression(nn.Module):
    """Meta's sEMG squashing: near-linear for small inputs, saturating spikes at ±range."""
    def __init__(self, range_, midpoint):
        super().__init__()
        self.range, self.midpoint = range_, midpoint

    def forward(self, x):
        return self.range*x/(self.midpoint+x.abs())


class CausalBlock(nn.Module):
    """Depthwise-separable dilated causal conv (left padding only), BatchNorm, GELU, residual."""
    def __init__(self, width, dilation, dropout):
        super().__init__()
        self.pad = 2*dilation
        self.depthwise = nn.Conv1d(width, width, 3, dilation=dilation, groups=width)
        self.pointwise = nn.Conv1d(width, width, 1)
        self.norm = nn.BatchNorm1d(width); self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        y = self.pointwise(self.depthwise(nn.functional.pad(x, (self.pad, 0))))
        return x+self.dropout(nn.functional.gelu(self.norm(y)))


TCN_AUGMENTATION = {'rotation': 1, 'channel_gain': .1, 'noise': .05}


class EMGClassifier(nn.Module):
    def __init__(self, architecture, input_shape, classes, dropout=.25, hyper=None):
        super().__init__()
        self.architecture = architecture
        if architecture == 'lstm':
            # Meta's DiscreteGesturesArchitecture (generic-neuromotor-interface), scaled to our data:
            # compression -> strided causal Conv1d -> ReLU/dropout -> LayerNorm -> stacked LSTM -> LayerNorm -> linear.
            # Inputs are per-channel z-scored, so compression saturates beyond ~range standard deviations.
            h = {**LSTM_DEFAULTS, **(hyper or {})}
            self.compression = ReinhardCompression(h['compression_range'], h['compression_midpoint'])
            self.conv = nn.Conv1d(input_shape[0], h['conv_channels'], h['kernel_width'], stride=h['stride'])
            self.conv_dropout = nn.Dropout(dropout)
            self.post_conv_norm = nn.LayerNorm(h['conv_channels'])
            self.lstm = nn.LSTM(h['conv_channels'], h['hidden'], h['layers'], batch_first=True,
                                dropout=dropout if h['layers'] > 1 else 0.)
            self.post_lstm_norm = nn.LayerNorm(h['hidden'])
            self.output = nn.Linear(h['hidden'], classes)
            return
        if architecture == 'fnn':
            self.encoder = nn.Sequential(nn.Linear(input_shape[0], 128), nn.ReLU(), nn.Dropout(dropout),
                                         nn.Linear(128, 64), nn.ReLU(), nn.Dropout(dropout))
            width = 64
        elif architecture == 'cnn':
            # Entire input window is in the past. Padding within that window
            # introduces no lookahead beyond its timestamp.
            self.encoder = nn.Sequential(
                nn.Conv1d(input_shape[0], 16, 15, stride=4, padding=7), nn.ReLU(),
                nn.Conv1d(16, 32, 9, stride=2, padding=4), nn.ReLU(), nn.Dropout(dropout),
                nn.Conv1d(32, 64, 5, stride=2, padding=2), nn.ReLU(),
                nn.AdaptiveAvgPool1d(4), nn.Flatten(),
                nn.Linear(256, 64), nn.ReLU(), nn.Dropout(dropout))
            width = 64
        elif architecture == 'tcn':
            # Fallback to Meta's LSTM: causal dilated TCN on two streams (filtered EMG + 16 ms RMS envelope).
            self.envelope = nn.AvgPool1d(32, stride=1)
            self.stem = nn.Sequential(nn.Conv1d(2*input_shape[0], 64, 5, stride=4), nn.BatchNorm1d(64), nn.GELU())
            self.blocks = nn.Sequential(*[CausalBlock(64, d, dropout) for d in (1, 2, 4, 8, 16)])
            self.head = nn.Sequential(nn.Linear(128, 64), nn.GELU(), nn.Dropout(dropout))
            width = 64
        else:
            raise ValueError('Unknown architecture: '+architecture)
        self.output = nn.Linear(width, classes)

    def forward(self, x):
        if self.architecture == 'lstm':
            x = self.conv_dropout(torch.relu(self.conv(self.compression(x))))
            x, _ = self.lstm(self.post_conv_norm(x.transpose(1, 2)))
            # The window ends at its timestamp, so the last LSTM step has seen the whole (past-only) window.
            return self.output(self.post_lstm_norm(x[:, -1]))
        if self.architecture == 'tcn':
            envelope = self.envelope(nn.functional.pad(x*x, (31, 0))).clamp_min(1e-6).sqrt()
            x = self.blocks(self.stem(nn.functional.pad(torch.cat([x, envelope], 1), (4, 0))))
            return self.output(self.head(torch.cat([x.mean(-1), x[:, :, -1]], 1)))
        return self.output(self.encoder(x))


def input_array(rows, architecture):
    key = 'x' if architecture == 'fnn' else 'waveform'
    x = np.asarray([r[key] for r in rows], dtype=np.float32)
    if not len(x) or not np.isfinite(x).all():
        raise ValueError('Empty or non-finite neural input')
    if architecture == 'fnn':
        if (x < 0).any():
            raise ValueError('Engineered features must be nonnegative')
        x = np.log1p(x)
    return x


def row_weights(rows):
    """Each class weighs the same; within a class each wearer, and within a wearer each clip, weighs the same."""
    person = lambda r: r.get('wearing_session')
    pairs = Counter((r['group'], r['label']) for r in rows)
    groups = Counter((person(r), r['label']) for r in {(r['group'], r['label'], person(r)): r for r in rows}.values())
    people = Counter(label for _, label in groups)
    weight = np.asarray([1/(pairs[r['group'], r['label']]*groups[person(r), r['label']]*people[r['label']])
                         for r in rows], np.float32)
    return weight/weight.mean()


def normalize_fit(x, architecture):
    axes = (0,) if architecture == 'fnn' else (0, 2)
    mean = x.mean(axis=axes, keepdims=True)
    std = np.maximum(x.std(axis=axes, keepdims=True), 1e-4)
    return mean, std


@torch.inference_mode()
def probabilities(model, x, batch_size=512):
    model.eval(); device = next(model.parameters()).device
    return torch.cat([model(torch.from_numpy(np.ascontiguousarray(v)).to(device)).softmax(-1).cpu()
                      for v in np.array_split(x, max(1, int(np.ceil(len(x)/batch_size))))]).numpy()


def rotate_channels(batch, max_shift):
    """Meta's electrode-rotation augmentation: one random circular channel shift per batch."""
    shift = int(torch.randint(-max_shift, max_shift+1, (1,)))
    return batch.roll(shift, dims=1) if shift else batch


def fit_classifier(train, validation, spec, architecture, config, seed, weak_bags=(), selection=None):
    """Only train fits normalization; only validation selects the epoch.

    selection=(rows, score) picks the epoch by score(probabilities on rows), e.g. event F1,
    after any warm-up, instead of weighted cross-entropy.
    """
    torch.manual_seed(seed)
    x = input_array(train, architecture); vx = input_array(validation, architecture)
    bag_arrays = [input_array(b['rows'], architecture) for b in weak_bags]
    normalization_input = np.concatenate([x, *bag_arrays]) if bag_arrays else x
    mean, std = normalize_fit(normalization_input, architecture)
    bags = [torch.from_numpy((v-mean)/std) for v in bag_arrays]
    sx = (input_array(selection[0], architecture)-mean)/std if selection else None
    if bags and 'event_class' not in spec:
        raise ValueError('Weak bags require an event head')
    x = (x-mean)/std; vx = (vx-mean)/std
    labels = spec['classes']
    present = {r['label'] for r in train} | ({spec['event_class']} if bags else set())
    if present != set(labels):
        raise ValueError('Training must contain every registered class')
    y = torch.tensor([labels.index(r['label']) for r in train])
    vy = torch.tensor([labels.index(r['label']) for r in validation])
    device = torch.device(config.get('device') or ('cuda' if torch.cuda.is_available() else 'cpu'))
    w = torch.from_numpy(row_weights(train)).to(device); vw = torch.from_numpy(row_weights(validation)).to(device)
    y = y.to(device); vy = vy.to(device); bags = [b.to(device) for b in bags]
    hyper = lstm_settings(config) if architecture == 'lstm' else None
    aug = hyper or (TCN_AUGMENTATION if architecture == 'tcn' else None)
    model = EMGClassifier(architecture, x.shape[1:], len(labels), config['dropout'], hyper).to(device)
    lr = hyper['learning_rate'] if hyper else config['learning_rate']
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=config['weight_decay'])
    scheduler = None
    if hyper:
        # Meta's schedule: linear warm-up, then step decay at the milestones.
        def lr_scale(epoch):
            if epoch < hyper['warmup_epochs']:
                start = hyper['warmup_start_factor']
                return start+(1-start)*epoch/hyper['warmup_epochs']
            return hyper['lr_factor']**sum(epoch >= m for m in hyper['lr_milestones'])
        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_scale)
    clip = hyper['gradient_clip'] if hyper else 5.
    loss_fn = nn.CrossEntropyLoss(reduction='none')
    tx = torch.from_numpy(x).to(device); tvx = torch.from_numpy(vx).to(device)
    tmean = torch.from_numpy(mean).to(device); tstd = torch.from_numpy(std).to(device)
    best_loss = best_metric = float('inf'); best = None; stale = 0; history = []; scores = []
    warmup = hyper['warmup_epochs'] if hyper else 0
    started = time.monotonic()
    for epoch in range(config['epochs']):
        model.train(); order = torch.randperm(len(x), device=device)
        for ix in order.split(config['batch_size']):
            optimizer.zero_grad()
            batch = tx[ix]
            # Training-only gain jitter; retain channel layout and burst order.
            gain = torch.exp(torch.randn(len(ix), 1, device=device)*.20)
            if architecture != 'fnn':
                raw = batch*tstd+tmean
                raw = raw*gain.unsqueeze(-1)
                if aug and aug['rotation']:
                    raw = rotate_channels(raw, aug['rotation'])
                if aug and aug['channel_gain']:
                    # Per-electrode contact variation on top of the global gain.
                    raw = raw*torch.exp(torch.randn(len(ix), raw.shape[1], 1, device=device)*aug['channel_gain'])
                batch = (raw-tmean)/tstd
                if aug and aug['noise']:
                    batch = batch+torch.randn_like(batch)*aug['noise']
            else:
                logged = batch*tstd+tmean
                values = torch.expm1(logged).clamp_min(0).reshape(len(ix), -1, 40)
                values = values.clone(); values[:, :, :24] *= gain.unsqueeze(-1)
                batch = (torch.log1p(values.reshape(len(ix), -1))-tmean)/tstd
            loss = (loss_fn(model(batch), y[ix])*w[ix]).mean()
            if bags:
                # At least one event in each confirmed positive short clip.
                # Counts remain metadata, never point-event pseudo labels.
                bag_index = int(torch.randint(len(bags), (1,)))
                bag = bags[bag_index]
                if aug and aug['rotation']:
                    bag = (rotate_channels(bag*tstd+tmean, aug['rotation'])-tmean)/tstd
                logits = model(bag)
                event_index = labels.index(spec['event_class'])
                background_index = labels.index(spec['background'])
                odds = logits[:, event_index]-logits[:, background_index]
                pooled = .3*(torch.logsumexp(odds/.3, 0)-np.log(len(odds)))
                loss = loss+.25*nn.functional.softplus(-pooled)
            loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), clip)
            optimizer.step()
        if scheduler:
            scheduler.step()
        model.eval()
        with torch.inference_mode():
            losses = torch.cat([loss_fn(model(tvx[ix]), vy[ix]) for ix in torch.arange(len(vx)).split(512)])
            val_loss = float((losses*vw).sum()/vw.sum())
        history.append(val_loss)
        metric = val_loss
        if selection:
            metric = -selection[1](probabilities(model, sx)) if epoch+1 > warmup or epoch+1 == config['epochs'] else float('inf')
            scores.append(None if metric == float('inf') else -metric)
        if metric < best_metric-1e-5 or (metric == best_metric and val_loss < best_loss):
            best_metric = metric; best_loss = val_loss
            best = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            best_epoch = epoch+1; stale = 0
        else:
            stale += 1
        if stale >= config['patience']:
            break
    model = model.cpu(); model.load_state_dict(best)
    checkpoint = {'schema': 1, 'architecture': architecture, 'input_shape': list(x.shape[1:]),
                  'classes': list(labels), 'dropout': config['dropout'], 'state_dict': best, 'hyper': hyper,
                  'mean': torch.from_numpy(mean), 'std': torch.from_numpy(std), 'seed': seed,
                  'best_epoch': best_epoch}
    return model, checkpoint, probabilities(model, vx), {
        'best_epoch': best_epoch, 'validation_weighted_cross_entropy': best_loss,
        'validation_loss_history': history, 'selection_history': scores, 'seconds': time.monotonic()-started,
        'parameters': sum(p.numel() for p in model.parameters())}


class NeuralClassifier:
    """Portable checkpoint reader; normalization and class order travel with it."""
    def __init__(self, checkpoint):
        if not isinstance(checkpoint, dict):
            checkpoint = torch.load(checkpoint, map_location='cpu', weights_only=True)
        self.checkpoint = checkpoint; self.classes_ = np.array(checkpoint['classes'])
        self.architecture = checkpoint['architecture']
        self.model = EMGClassifier(self.architecture, checkpoint['input_shape'], len(self.classes_),
                                   checkpoint['dropout'], checkpoint.get('hyper'))
        self.model.load_state_dict(checkpoint['state_dict']); self.model.eval()

    def predict_rows(self, rows):
        x = input_array(rows, self.architecture)
        if list(x.shape[1:]) != self.checkpoint['input_shape']:
            raise ValueError('Input shape differs from trained model')
        x = (x-self.checkpoint['mean'].numpy())/self.checkpoint['std'].numpy()
        return probabilities(self.model, x)


def classification_metrics(rows, p, classes, threshold=0.):
    actual = [r['label'] for r in rows]
    predicted = [classes[i] if score >= threshold else 'unknown' for i, score in zip(p.argmax(1), p.max(1))]
    order = list(classes)+['unknown']
    segments = []
    for group, label in dict.fromkeys((r['group'], r['label']) for r in rows):
        ix = [i for i, r in enumerate(rows) if (r['group'], r['label']) == (group, label)]
        avg = p[ix].mean(0); guess = classes[int(avg.argmax())]
        segments.append({'group': group, 'actual': label, 'predicted': guess, 'windows': len(ix)})
    accepted = np.array([v != 'unknown' for v in predicted])
    return {'windows': len(rows), 'window_accuracy': float(accuracy_score(actual, predicted)),
            'window_macro_f1': float(f1_score(actual, predicted, labels=classes, average='macro', zero_division=0)),
            'coverage': float(accepted.mean()),
            'accepted_window_accuracy': float(np.mean(np.array(actual)[accepted] == np.array(predicted)[accepted])) if accepted.any() else None,
            'label_order': order, 'confusion_matrix': confusion_matrix(actual, predicted, labels=order).tolist(),
            'segment_count': len(segments), 'segment_accuracy': sum(r['actual'] == r['predicted'] for r in segments)/len(segments),
            'segments': segments, 'threshold': threshold}


def event_scores(rows, scores, threshold, event_class='snap', background='negative', tolerance=.25):
    total = Counter(); clips = []; negative_seconds = 0.; negative_false = 0
    for trial in dict.fromkeys(r['trial'] for r in rows):
        indices = sorted([i for i, r in enumerate(rows) if r['trial'] == trial], key=lambda i: rows[i]['end'])
        steps = np.diff([rows[i]['end'] for i in indices])
        hop = float(np.median(steps)) if len(steps) else .015625
        truth = rows[indices[0]].get('expected_events', [])
        predicted = []; last = -float('inf'); rearmed = False; previous = None
        for i in indices:
            row = rows[i]; t = row['end']; score = float(scores[i])
            if previous is not None and t-previous > .05:
                rearmed = False
            previous = t
            if score < .4:
                rearmed = True
            emitted = score >= threshold and rearmed and t-last >= .35
            if emitted:
                predicted.append(t); rearmed = False; last = t
                if row['label'] == background:
                    negative_false += 1
            # Hop exposure, counted once even though input windows overlap.
            if row['label'] == background:
                negative_seconds += min(hop, t-row['start'])
        metric = event_metrics(truth, predicted, tolerance)
        for k in ('tp', 'fp', 'fn'):
            total[k] += metric[k]
        clips.append({'trial': trial, 'expected': truth, 'predicted': predicted, **metric})
    tp, fp, fn = (total[k] for k in ('tp', 'fp', 'fn'))
    return {'tp': tp, 'fp': fp, 'fn': fn, 'event_count': tp+fn,
            'precision': tp/(tp+fp) if tp+fp else None, 'recall': tp/(tp+fn) if tp+fn else None,
            'f1': 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,
            'negative_seconds': negative_seconds, 'negative_false_events': negative_false,
            'negative_false_events_per_minute': negative_false/(negative_seconds/60) if negative_seconds else None,
            'threshold': threshold, 'tolerance_seconds': tolerance, 'physical_latency_measured': False, 'clips': clips}


def select_threshold(rows, p, spec):
    if 'event_class' in spec:
        scores = p[:, spec['classes'].index(spec['event_class'])]
        options = [event_scores(rows, scores, t, spec['event_class'], spec['background'])
                   for t in (.5, .65, .75, .85, .9, .95, .98, .995, .998, .999, .9995)]
        best = max(options, key=lambda m: (m['f1'], -m['fp'], m['threshold']))
        return best['threshold'], best['f1'], best
    options = [classification_metrics(rows, p, spec['classes'], t) for t in (0., .55, .65, .75, .85, .95)]
    best = max(options, key=lambda m: (m['window_macro_f1'], m['threshold']))
    return best['threshold'], best['window_macro_f1'], best


class NeuralEMGPredictor:
    """Model-only streaming outputs; external game logic maps gestures to spells."""
    def __init__(self, directory):
        from pathlib import Path
        from .common import read_json
        from .signals import SignalWindows
        self.directory = Path(directory); self.manifest = read_json(self.directory/'model.json')
        self.windows = SignalWindows(self.manifest['signal'], include_waveforms=True)
        self.models = {task: NeuralClassifier(self.directory/value['checkpoint']) for task, value in self.manifest['tasks'].items()}
        self.last_seq = None; self.last_t = None; self.event_id = 0; self.reset_decisions()

    def reset_decisions(self):
        self.memory = {task: {'label': 'unknown', 'candidate': 'unknown', 'votes': 0,
                              'rearmed': False, 'last_event': -float('inf')} for task in self.models}

    def feed(self, packet):
        from .effort import sensor_times
        seq = packet['source_seq']; times = sensor_times(packet, self.manifest['signal']['sample_rate'])
        gap = (self.last_seq is not None and seq != self.last_seq+1) or (
            self.last_t is not None and not 0 < times[0]-self.last_t <= 2.5/self.manifest['signal']['sample_rate'])
        if gap:
            self.windows.reset(); self.reset_decisions()
        self.last_seq = seq; self.last_t = times[-1]; outputs = []
        for feature in self.windows.feed(packet['samples'], times):
            for task, spec in self.manifest['tasks'].items():
                if spec['window_kind'] != feature['kind']:
                    continue
                p = self.models[task].predict_rows([feature])[0]; t = feature['t']; memory = self.memory[task]
                outputs.append({'kind': 'neural_scores', 'task': task, 'source_t': t,
                                'probabilities': dict(zip(spec['classes'], map(float, p)))})
                if 'event_class' in spec:
                    score = float(p[spec['classes'].index(spec['event_class'])])
                    if score < .4:
                        memory['rearmed'] = True
                    if score >= spec['threshold'] and memory['rearmed'] and t-memory['last_event'] >= .35:
                        memory['last_event'] = t; memory['rearmed'] = False; self.event_id += 1
                        outputs.append({'kind': 'neural_event', 'task': task, 'label': spec['event_class'],
                                        'source_t': t, 'confidence': score, 'event_id': str(self.event_id)})
                else:
                    guess = spec['classes'][int(p.argmax())] if max(p) >= spec['threshold'] else 'unknown'
                    memory['votes'] = memory['votes']+1 if guess == memory['candidate'] else 1
                    memory['candidate'] = guess
                    if memory['votes'] >= 2:
                        memory['label'] = guess
                    outputs.append({'kind': 'neural_state', 'task': task, 'label': memory['label'],
                                    'source_t': t, 'confidence': float(max(p))})
        return outputs
