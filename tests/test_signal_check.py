import json
import urllib.request
import numpy as np
import pytest
from spelltrain.recorder import Recorder
from spelltrain.session import Session
from spelltrain.signal_check import SignalCheck


def setup_check(tmp_path):
    session = Session(tmp_path/'session', 'tester')
    check = SignalCheck(session)
    clock = [0.]
    session.now = lambda: clock[0]
    return session, check, clock


def send(check, start=0, end=3, flat=False, gaps=False):
    samples = np.zeros((16, 8)) if flat else np.arange(128).reshape(16, 8)
    for t in np.arange(start, end, 1/128):
        check.observe({'received': float(t), 'samples': samples, 'gap': gaps})


def test_no_data_cannot_pass_and_does_not_make_training_labels(tmp_path):
    session, check, clock = setup_check(tmp_path)
    check.start('shield'); clock[0] = 3
    result = check.finish()
    assert not result['received']
    assert result['message'].startswith('No EMG received')
    assert not session.annotations
    assert json.loads((session.directory/'signal-checks.json').read_text()) == [result]
    session.close()


def test_receipt_requires_current_data_and_survives_reload(tmp_path):
    session, check, clock = setup_check(tmp_path)
    clock[0] = 10
    check.start('snap')
    send(check, 0, 3)  # Buffered packets from before Start Record do not count.
    assert check.status()['active']['samples'] == 0
    send(check, 10, 13); clock[0] = 13
    result = check.finish()
    assert result['received'] and result['message'] == 'Received.'
    assert result['verified_gesture'] is False
    assert SignalCheck(session).status()['results'] == [result]
    assert session.annotations == []  # A prompt is not a verified snap timestamp.
    session.close()


@pytest.mark.parametrize('mode', ['short', 'flat', 'stale', 'gaps', 'synthetic'])
def test_bad_capture_cannot_pass(tmp_path, mode):
    session, check, clock = setup_check(tmp_path)
    check.start('sword')
    send(check, end=.2 if mode == 'short' else 3, flat=mode == 'flat', gaps=mode == 'gaps')
    clock[0] = .2 if mode == 'short' else 4 if mode == 'stale' else 3
    session.meta['synthetic'] = mode == 'synthetic'
    assert not check.finish()['received']
    check.start('sword')  # Retrying is possible after every failed check.
    session.close()


def test_wizard_api_and_advanced_view(tmp_path):
    session = Session(tmp_path/'web', 'tester')
    recorder = Recorder(session)
    port = recorder.start_web(0)
    base = f'http://127.0.0.1:{port}'
    try:
        html = urllib.request.urlopen(base+'/check').read().decode()
        assert 'Band movement check' in html and 'Start Record' in html
        token = html.split("const token='")[1].split("'")[0]
        advanced = urllib.request.urlopen(base+'/advanced').read().decode()
        assert 'Annotate actions' in advanced
        def post(path, value):
            request = urllib.request.Request(base+'/api/'+path, data=json.dumps(value).encode(),
                                            headers={'X-Session-Token': token})
            return json.loads(urllib.request.urlopen(request).read())
        state = json.loads(urllib.request.urlopen(base+'/api/check').read())
        assert len(state['motions']) == 6
        post('check/start', {'motion': 'shield'})
        assert not post('check/stop', {})['received']
        assert not session.annotations
    finally:
        recorder.close()


def test_transport_jitter_with_contiguous_samples_can_pass(tmp_path):
    session, check, clock = setup_check(tmp_path)
    check.start('shield')
    samples = np.arange(128).reshape(16, 8)
    for seq in range(384):
        check.observe({'received': seq/128, 'samples': samples, 'source_seq': seq, 'gap': True})
    clock[0] = 3
    assert check.finish()['received']
    check.start('shield')
    for seq in range(384):
        check.observe({'received': 3+seq/128, 'samples': samples, 'source_seq': seq*2, 'gap': False})
    clock[0] = 6
    assert not check.finish()['received']
    session.close()
