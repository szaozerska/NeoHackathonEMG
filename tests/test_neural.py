import copy
import numpy as np
import pytest

torch = pytest.importorskip('torch')
from spelltrain.neural import (EMGClassifier, NeuralClassifier, fit_classifier, normalize_fit,
                              event_scores, classification_metrics)
from spelltrain.neural_data import validate_dataset, add_reviewed_examples
from spelltrain.signals import SignalWindows


def row(start, part='train', group='a', label='none'):
    return {'session': 's', 'group': group, 'trial': group, 'part': part, 'label': label,
            'start': start, 'end': start+.2, 'x': np.ones(40), 'waveform': np.ones((8, 410))}


def test_clip_and_raw_window_leakage_rejected():
    data = {'tasks': {'state': [row(0), row(2, 'test')]}}
    with pytest.raises(ValueError, match='clip crosses'):
        validate_dataset(data)
    data['tasks']['state'][1]['group'] = 'b'
    validate_dataset(data)
    data['tasks']['state'][1]['start'] = .1
    with pytest.raises(ValueError, match='overlap'):
        validate_dataset(data)


def test_waveform_export_preserves_streaming_features_and_packet_boundaries():
    rng = np.random.default_rng(1); raw = rng.normal(32000, 10, (1200, 8)); t = np.arange(1200)/2048
    a = SignalWindows(include_waveforms=True); b = SignalWindows()
    aa = a.feed(raw[:500], t[:500])+a.feed(raw[500:], t[500:]); bb = b.feed(raw, t)
    assert len(aa) == len(bb) > 0
    from spelltrain.signals import features, snap_features
    for x, y in zip(aa, bb):
        np.testing.assert_allclose(x['x'], y['x'])
        fn = features if x['kind'] == 'state' else snap_features
        np.testing.assert_allclose(fn(x['waveform'].T), y['x'], rtol=1e-5, atol=1e-6)


@pytest.mark.parametrize('architecture,shape', [('fnn', (40,)), ('cnn', (8, 410))])
def test_vocabulary_can_expand_and_checkpoint_reloads(tmp_path, architecture, shape):
    torch.manual_seed(7)
    model = EMGClassifier(architecture, shape, 4, 0.)
    model.eval(); raw = torch.randn(3, *shape)
    checkpoint = {'architecture': architecture, 'input_shape': list(shape),
                  'classes': ['none', 'fist', 'open', 'future_gesture'], 'dropout': 0.,
                  'state_dict': model.state_dict(), 'mean': torch.zeros((1, *shape)),
                  'std': torch.ones((1, *shape))}
    path = tmp_path/'model.pt'; torch.save(checkpoint, path)
    restored = NeuralClassifier(path)
    with torch.inference_mode():
        torch.testing.assert_close(model(raw), restored.model(raw))
    assert restored.model(raw).shape == (3, 4)


def test_only_training_fits_normalization_and_weak_bag_uses_clip_supervision():
    torch.set_num_threads(1)
    training = [row(i, group=str(i), label='snap' if i%2 else 'negative') for i in range(6)]
    validation = [row(10+i, 'validation', group='v'+str(i), label='snap' if i%2 else 'negative') for i in range(4)]
    for i, r in enumerate(training+validation):
        r['x'] *= i+1
    spec = {'classes': ['negative', 'snap'], 'background': 'negative', 'event_class': 'snap'}
    config = {'epochs': 2, 'patience': 1, 'dropout': 0., 'learning_rate': .001, 'weight_decay': .01, 'batch_size': 3}
    bags = [{'rows': [row(20, label=None)], 'positive': True, 'reported_count': 1}]
    _, a, _, _ = fit_classifier(training, validation, spec, 'fnn', config, 7, bags)
    altered = copy.deepcopy(validation)
    for r in altered:
        r['x'] *= 100
    _, b, _, _ = fit_classifier(training, altered, spec, 'fnn', config, 7, bags)
    torch.testing.assert_close(a['mean'], b['mean']); torch.testing.assert_close(a['std'], b['std'])
    assert bags[0]['rows'][0]['label'] is None


def test_unknown_rejection_and_one_to_one_event_metrics():
    rows = [row(i*.015625, label='negative') for i in range(100)]
    for r in rows:
        r['expected_events'] = [.5]
    scores = np.zeros(100); scores[32:35] = .99; scores[70] = .99
    result = event_scores(rows, scores, .9)
    assert (result['tp'], result['fp'], result['fn']) == (1, 1, 0)
    states = [row(0), row(1, label='fist')]
    m = classification_metrics(states, np.array([[.51, .49], [.1, .9]]), ['none', 'fist'], .8)
    assert m['coverage'] == .5 and m['window_accuracy'] == .5


def test_unreviewed_additions_cannot_silently_become_labels(tmp_path):
    import json
    path = tmp_path/'examples.json'; path.write_text(json.dumps({'independently_reviewed': False}))
    with pytest.raises(ValueError, match='Independent example review'):
        add_reviewed_examples({}, path, {})


def test_guided_variants_cover_soft_firm_and_rotation_without_camera():
    import runpy
    from pathlib import Path
    module = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/collect_neural_emg.py'))
    items = module['plan']('snap', 20)
    assert len(items) == 20 and len({r['id'] for r in items}) == 20
    assert all(r['intended_count'] == 1 for r in items)
    for intensity in ('SOFT', 'FIRM'):
        for rotation in ('MINIMAL', 'NATURAL', 'EXAGGERATED'):
            assert any(intensity in r['instruction'] and rotation in r['instruction'] for r in items)
    assert all(r['intended_count'] == 0 for r in module['plan']('negative', 20))
    custom = module['plan']('new_gesture', 3, instruction='Hold two fingers extended')
    assert all(r['kind'] == 'new_gesture' for r in custom)


def test_guided_counts_become_bags_not_fabricated_positive_windows(tmp_path, monkeypatch):
    import json
    import spelltrain.neural_data as module
    from spelltrain.effort import _hash
    from spelltrain.signals import DEFAULT_SIGNAL
    raw = [{'kind': 'emg', 'capture_t': i*.01, 'packet': {'source_seq': i}} for i in range(210)]
    (tmp_path/'streams.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in raw))
    trials = [{'id': 'one', 'kind': 'snap', 'confirmed': True, 'start': 0., 'end': 2.,
               'reported_count': 1, 'instruction': 'one soft snap'}]
    (tmp_path/'guided-trials.json').write_text(json.dumps(trials))
    (tmp_path/'guided-manifest.json').write_text(json.dumps({'wearing_session': 'wearing-new',
        'source_hashes': {name: _hash(tmp_path/name) for name in ('streams.jsonl', 'guided-trials.json')}}))
    features = [{'kind': 'snap', 'start': .5, 't': .625, 'x': np.ones(160), 'waveform': np.ones((8, 256))}]
    capture = {'features': features, 'metadata': {'model': {'signal': DEFAULT_SIGNAL}}}
    monkeypatch.setattr(module, 'capture_features', lambda *args, **kwargs: capture)
    dataset = {'signal': DEFAULT_SIGNAL, 'sources': [], 'tasks': {'snap': []}}
    module.add_guided_capture(dataset, tmp_path)
    assert dataset['tasks']['snap'] == []
    bag = dataset['weak_bags']['snap'][0]
    assert bag['reported_count'] == 1 and 'label' not in bag['rows'][0]
    assert bag['part'] == 'train'
    with pytest.raises(ValueError, match='Duplicate'):
        module.add_guided_capture(dataset, tmp_path)
    dataset['sources'] = []; capture['metadata']['dataset_role'] = 'untouched_guided_count_check'
    with pytest.raises(ValueError, match='Reserved evaluation'):
        module.add_guided_capture(dataset, tmp_path)


def test_partial_contiguous_clip_is_rejected_in_count_training_and_evaluation():
    from spelltrain.neural_data import check_trial_coverage
    trial = {'id': 'one', 'start': 0., 'end': 3.}
    raw = [{'capture_t': i*.01, 'packet': {'source_seq': i}} for i in range(50)]
    with pytest.raises(ValueError, match='missing EMG'):
        check_trial_coverage(raw, trial, {})
