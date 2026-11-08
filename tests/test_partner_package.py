import importlib.util
from pathlib import Path
import json
import numpy as np
import pytest
import joblib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('partner_prepare', ROOT/'scripts/prepare_partner.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def test_packaged_files_match_manifest_and_corruption_is_rejected(tmp_path):
    assert prepare.verify_bundle(ROOT)['kinesis']['architecture'] == 'arm64'
    (tmp_path/'models').mkdir()
    manifest = {'models': {'missing.pt': {'sha256': 'bad'}}, 'kinesis': {'archive': 'k.zip', 'sha256': 'bad'}}
    (tmp_path/'models/manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Missing or changed'):
        prepare.verify_bundle(tmp_path)


def test_packaged_fallback_loads_and_http_dashboard_runs():
    from spelltrain.live_test import LiveTester
    import urllib.request
    import tempfile
    artifact = joblib.load(ROOT/'models/gestures-v4/model.joblib')
    assert artifact['report']['model_version'] == 'v4'
    with tempfile.TemporaryDirectory() as directory:
        tester = LiveTester(artifact, Path(directory)/'new-raw.jsonl')
        try:
            port = tester.start(0, start_feed=False)
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status') as response:
                status = json.load(response)
            assert status['app'] == 'live-model-tester'
            assert status['model_version'] == 'v4'
        finally:
            tester.close()
