import json
import socket
import time
import urllib.request
from spelltrain.session import Session
from spelltrain.recorder import Recorder


def test_quest_handshake_clock_sync_and_pose_written(tmp_path):
    session=Session(tmp_path/'session','tester')
    recorder=Recorder(session)
    recorder.spawn(recorder.worker)
    port=recorder.start_tcp('127.0.0.1',0)
    try:
        with socket.create_connection(('127.0.0.1',port)) as sock:
            stream=sock.makefile('rwb')
            stream.write(b'{"type":"hello","role":"vr"}\n');stream.flush()
            assert json.loads(stream.readline())['player_id']=='P1'
            stream.write(b'{"type":"time_ping","t":123}\n');stream.flush()
            assert json.loads(stream.readline())['client_t']==123
            from test_fusion import pose
            packet={'type':'pose','t':123.,'t_mac':time.monotonic(),'sync_rtt':.01,'seq':1,**pose()}
            stream.write((json.dumps(packet)+'\n').encode());stream.flush()
            deadline=time.monotonic()+2
            while session.counts['pose']==0 and time.monotonic()<deadline:time.sleep(.01)
            assert session.counts['pose']==1
            assert recorder.clock_rtt==.01
    finally:
        recorder.close()
    rows=[json.loads(l) for l in (session.directory/'streams.jsonl').read_text().splitlines()]
    assert rows[0]['timing']=='clock_offset_estimate'


def test_web_annotations_require_token(tmp_path):
    s=Session(tmp_path/'one','tester');r=Recorder(s)
    port=r.start_web(0)
    try:
        html=urllib.request.urlopen(f'http://127.0.0.1:{port}/').read().decode()
        token=html.split("const token='")[1].split("'")[0]
        value={'label':'open','start':1,'end':3,'trial_id':'trial','verified':True}
        req=urllib.request.Request(f'http://127.0.0.1:{port}/api/annotation',data=json.dumps(value).encode(),headers={'X-Session-Token':token})
        row=json.loads(urllib.request.urlopen(req).read())
        assert row['verified']
        assert len(s.annotations)==1
    finally:r.close()


def test_emg_only_cli_without_quest_listener_and_clean_stop(tmp_path):
    import subprocess
    import sys
    import re
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0))
        quest_port=reserved.getsockname()[1]
        with socket.socket() as available:
            available.bind(('127.0.0.1',0))
            web_port=available.getsockname()[1]
        process=subprocess.Popen([sys.executable,'-m','spelltrain','record','--subject','test-person',
                                  '--session',str(tmp_path/'band-01'),'--emg-only',
                                  '--port',str(quest_port),'--web-port',str(web_port),
                                  '--kinesis-file',str(tmp_path/'not-created.jsonl')],
                                 stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            base=f'http://127.0.0.1:{web_port}'
            deadline=time.monotonic()+5
            while True:
                try:
                    status=json.loads(urllib.request.urlopen(base+'/api/status',timeout=.5).read())
                    break
                except OSError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.05)
            assert status['session']['mode']=='emg_only'
            assert not status['errors']
            assert not status['emg_fresh']
            html=urllib.request.urlopen(base).read().decode()
            token=re.search("const token='([^']+)'",html).group(1)
            req=urllib.request.Request(base+'/api/stop',data=b'{}',headers={'X-Session-Token':token})
            assert json.loads(urllib.request.urlopen(req).read())['ok']
            assert process.wait(timeout=5)==0
            meta=json.loads((tmp_path/'band-01/metadata.json').read_text())
            assert meta['recording_closed']
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(5)
