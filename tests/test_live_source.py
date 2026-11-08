import threading
import time
import json
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from spelltrain import live_source
from spelltrain.feeds import normalize_sse


def test_discover_only_kinesis_open_recording(monkeypatch, tmp_path):
    path = tmp_path/'chosen.jsonl'
    path.touch()
    def lsof(arguments, **kwargs):
        assert arguments == ['/usr/sbin/lsof', '-a', '-c', 'Kinesis', '-Fn']
        return SimpleNamespace(stdout=f'p123\nn{path}\nn/tmp/unrelated.txt\n')
    monkeypatch.setattr(live_source.subprocess, 'run', lsof)
    assert live_source.discover_recording() == path


@pytest.mark.parametrize('url', [
    'https://127.0.0.1:8766/events?token=x',
    'http://example.com:8766/events?token=x',
    'http://127.0.0.1:8766/haptics?token=x',
    'http://user:password@127.0.0.1:8766/events?token=x',
    'http://127.0.0.1:8766/events',
    'http://127.0.0.1:8766/events?token=x&token=y',
])
def test_stream_rejects_invalid_urls_without_exposing_them(url):
    with pytest.raises(ValueError, match='Use the local stream URL'):
        live_source.validate_stream_url(url)


def test_stream_link_is_local_private_and_not_status_metadata(tmp_path):
    state = tmp_path/'local/link'
    source = live_source.LiveInput(tmp_path/'fallback', None, None, None, state)
    url = 'http://127.0.0.1:8766/events?token=test-only'
    source.set_stream(url)
    assert state.stat().st_mode & 0o777 == 0o600
    assert live_source.LiveInput(tmp_path/'fallback', None, None, None, state).url == url


def test_normalize_real_kinesis_schema_preserves_sensor_time_and_freshness():
    row = {'type':'emg', 'stream_session_id':'stream-a', 'host_time_s':123.4,
           'band_timestamp_us':987654, 'payload':{'sequence':42, 'values':[[32768]*8]*16}}
    packet = normalize_sse(row, config={
        'samples_path':'payload.values', 'sequence_path':'payload.sequence',
        'timestamp_path':'band_timestamp_us', 'uptime_path':'host_time_s'})
    assert packet['source_seq'] == 42
    assert packet['source_t'] == 987654
    assert packet['source_uptime'] == 123.4
    assert packet['stream_session'] == 'stream-a'


def test_auto_source_follows_recording_changes_and_ignores_old_worker(monkeypatch, tmp_path):
    selected = [tmp_path/'first.jsonl']
    monkeypatch.setattr(live_source, 'discover_recording', lambda: selected[0])
    callbacks = {}
    def tail(path, stop, callback, error):
        callbacks[path] = callback
        stop.wait(5)
    monkeypatch.setattr(live_source, 'tail_kinesis', tail)
    packets, changes = [], []
    source = live_source.LiveInput(tmp_path/'fallback', packets.append, lambda _: None,
                                   lambda *change: changes.append(change))
    stop = threading.Event()
    worker = threading.Thread(target=source.run, args=(stop,))
    worker.start()
    try:
        deadline = time.monotonic()+4
        first = str(selected[0])
        while first not in callbacks and time.monotonic()<deadline:time.sleep(.01)
        assert first in callbacks
        callbacks[first]({'source_seq':1})
        selected[0] = tmp_path/'second.jsonl'
        second = str(selected[0])
        while second not in callbacks and time.monotonic()<deadline:time.sleep(.01)
        assert second in callbacks
        callbacks[first]({'source_seq':2})
        callbacks[second]({'source_seq':3})
        assert [packet['source_seq'] for packet in packets] == [1,3]
        assert changes == [('file',first),('file',second)]
    finally:
        stop.set()
        worker.join(2)


def test_dashboard_connects_real_sse_without_recording_or_exposing_link(monkeypatch, tmp_path):
    from spelltrain.live_test import LiveTester
    monkeypatch.setattr(live_source, 'discover_recording', lambda: None)
    class Predictor:
        def __init__(self):self.called=threading.Event()
        def feed(self, row):
            assert row['source_seq']==42 and row['source_t']==987654
            self.called.set()
            return []
    class FeedHandler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            assert self.path=='/events?token=test-only'
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            row={'type':'emg','host_time_s':time.monotonic(),'band_timestamp_us':987654,
                 'stream_session_id':'test-a','payload':{'sequence':42,'values':[[32768]*8]*16}}
            self.wfile.write(('event: emg\ndata: '+json.dumps(row)+'\n\n').encode())
            self.wfile.flush()
    feed=ThreadingHTTPServer(('127.0.0.1',0),FeedHandler)
    threading.Thread(target=feed.serve_forever,daemon=True).start()
    predictor=Predictor()
    tester=LiveTester({'report':{'model_version':'v4'}},tmp_path/'unused.jsonl',predictor=predictor)
    tester.live_input=live_source.LiveInput(tester.band_file,tester.packet,tester.error,tester.source_changed)
    try:
        port=tester.start(0)
        url=f'http://127.0.0.1:{feed.server_port}/events?token=test-only'
        request=urllib.request.Request(f'http://127.0.0.1:{port}/api/source/stream',
            data=json.dumps({'url':url}).encode(),
            headers={'X-Session-Token':tester.csrf,'Content-Type':'application/json'})
        with urllib.request.urlopen(request) as response:assert response.status==200
        assert predictor.called.wait(3)
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status') as response:
            status=json.load(response)
        assert status['input_kind']=='stream' and status['connected'] and status['packets']>=1
        assert 'test-only' not in json.dumps(status)
        assert not (tmp_path/'unused.jsonl').exists()
    finally:
        tester.close()
        feed.shutdown()
        feed.server_close()


def test_auto_reader_reopens_recording_replaced_at_same_path(monkeypatch,tmp_path):
    path=tmp_path/'recording.jsonl';path.write_text('old\n')
    monkeypatch.setattr(live_source,'discover_recording',lambda:path)
    opened=[]
    def reader(filename,stop,callback,error):
        opened.append(__import__('pathlib').Path(filename).read_text())
        stop.wait(5)
    monkeypatch.setattr(live_source,'tail_kinesis',reader)
    source=live_source.LiveInput(path,lambda _:None,lambda _:None,lambda *_:None)
    stop=threading.Event();worker=threading.Thread(target=source.run,args=(stop,));worker.start()
    try:
        deadline=time.monotonic()+4
        while not opened and time.monotonic()<deadline:time.sleep(.01)
        replacement=tmp_path/'replacement.jsonl';replacement.write_text('new\n');replacement.replace(path)
        while len(opened)<2 and time.monotonic()<deadline:time.sleep(.01)
        assert opened==['old\n','new\n']
    finally:stop.set();worker.join(2)
