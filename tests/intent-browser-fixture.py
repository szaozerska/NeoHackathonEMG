"""Synthetic localhost fixture. Never connects to the wearer's band/camera."""
from pathlib import Path
import signal
import threading
import time

from spelltrain import intent_collection
from spelltrain.live_test import LiveTester
from spelltrain.signals import DEFAULT_SIGNAL

original=intent_collection.protocol
intent_collection.protocol=lambda:[{**next(t for t in original() if t['kind']==kind),'seconds':1} for kind in ('snap','intent')]

class Predictor:
    def feed(self,row):
        return [{'kind':'state','label':'none','confidence':.99,'probabilities':{'none':.99,'fist':.005,'open':.005},'source_t':row['source_t']/1e6}]

tester=LiveTester({'report':{'model_version':'v4'},'signal':DEFAULT_SIGNAL},
    'data/browser-check/unused.jsonl',predictor=Predictor(),capture_root='data/browser-check/intent-captures')
tester.contribution_root=Path('data/browser-check/Micah data contribution')
def pump():
    seq=0;start=time.monotonic()
    while not tester.stop.wait(.005):
        target=int((time.monotonic()-start)*128)
        while seq<target:
            seq+=1;now=start+seq/128
            tester.packet({'source_seq':seq,'source_t':seq*7812.5,'source_uptime':now,'samples':[[32768]*8]*16})
            if seq%8==0:
                for kind,values in [('orientation',[1,0,0,0]),('gyro',[0,0,0])]:
                    tester.band_event(kind,{'schema_version':1,'type':kind,'host_time_s':now,'band_timestamp_us':seq*7812.5,'payload':{'values':values}})
threading.Thread(target=pump,daemon=True).start()
signal.signal(signal.SIGTERM,lambda *_:tester.stop.set())
signal.signal(signal.SIGINT,lambda *_:tester.stop.set())
port=tester.start(0,start_feed=False)
print(f'http://127.0.0.1:{port}',flush=True)
tester.stop.wait()
tester.close()
