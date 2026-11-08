"""Read-only software smoke checks. No account access or band connection."""
from pathlib import Path
import importlib.metadata
import platform
import sys
import joblib
import numpy as np
from prepare_partner import verify_bundle

ROOT = Path(__file__).resolve().parents[1]


def main():
    verify_bundle()
    for name in ('numpy', 'scipy', 'scikit-learn', 'joblib', 'torch', 'spelltrain'):
        print(name+': '+importlib.metadata.version(name))
    for version in ('v4', 'v6'):
        artifact = joblib.load(ROOT/f'models/gestures-{version}/model.joblib')
        probability = artifact['state_model'].predict_proba(np.ones((1, artifact['state_columns'])))
        assert np.isfinite(probability).all() and np.isclose(probability.sum(), 1)
    from spelltrain.neural import NeuralEMGPredictor
    neural = NeuralEMGPredictor(ROOT/'models/neural-emg-03')
    for task, model in neural.models.items():
        kind = neural.manifest['tasks'][task]['window_kind']
        waveform = np.zeros((8, neural.manifest['signal'][kind+'_window']), np.float32)
        from spelltrain.signals import features, snap_features
        x = (features if kind == 'state' else snap_features)(waveform.T)
        p = model.predict_rows([{'x': x, 'waveform': waveform}])
        assert p.shape == (1, len(model.classes_)) and np.isfinite(p).all()
    print('PASS: model hashes, imports and classical/neural inference.')
    print('Host: '+platform.platform())
    print('Hardware pending: Bluetooth approval, Meta sign-in, pairing and fresh raw EMG must be checked by the wearer.')


if __name__ == '__main__':
    main()
