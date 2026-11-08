import importlib.util
from pathlib import Path
import sys

import numpy as np

scripts = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location('pattern_analysis', scripts/'analyze_micah_patterns.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def test_channel_pattern_and_spectral_features_survive_effort_gain_change():
    rng = np.random.default_rng(4)
    raw = rng.normal(size=(5, 400, 8))*np.arange(1, 9)[None, None, :]
    a = analysis.features(raw); b = analysis.features(raw*3)
    assert a.shape == (5, 73)
    np.testing.assert_allclose(a[:, 1:9], b[:, 1:9], atol=1e-10)
    np.testing.assert_allclose(a[:, 33:], b[:, 33:], atol=1e-10)
    assert np.all(b[:, 0] > a[:, 0])


def test_long_hold_does_not_outvote_short_hold_or_other_class():
    y = np.array(['intended']*101+['non_intended']*5)
    group = np.array([1]*100+[2]+[3]*5)
    w = analysis.interval_weights(y, group)
    np.testing.assert_allclose(w[:100].sum(), w[100])
    np.testing.assert_allclose(w[y == 'intended'].sum(), w[y == 'non_intended'].sum())


def test_effort_validation_rejects_windows_as_independent_trials():
    data = {'motion': np.array(['shield_hold']*100), 'effort': np.array(['low']*100),
            'margin': np.ones(100), 'group': np.ones(100, dtype=int)}
    result = analysis.effort_support(data)
    assert result['whole_intervals_with_interior_windows']['shield_hold:low'] == 1
    assert not result['six_class_validation_supported']
