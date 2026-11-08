"""Synthetic EMG fixture; camera browser tests use Chrome's fake media only."""
import tempfile,threading,time
from pathlib import Path
from spelltrain.live_test import LiveTester
class Predictor:
    def feed(self,row):return [{'kind':'state','source_t':row['received'],'label':'none','confidence':.99}]
root=Path(tempfile.mkdtemp(prefix='spelltrain-camera-test-'))
tester=LiveTester({'report':{'model_version':'v6'}},root/'raw.jsonl',predictor=Predictor(),capture_root=root/'captures')
port=tester.start(0,start_feed=False)
def pump():
    seq=0
    while not tester.stop.is_set():
        tester.packet({'source_seq':seq,'source_uptime':time.monotonic(),'samples':[[0]*8]*16});seq+=1;time.sleep(.05)
threading.Thread(target=pump,daemon=True).start();print('http://127.0.0.1:'+str(port),flush=True)
try:
    while True:time.sleep(1)
except KeyboardInterrupt:tester.close()
