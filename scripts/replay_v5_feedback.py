import json,joblib
from pathlib import Path
from spelltrain.live_test import LiveTester
from spelltrain.common import json_lines
root=Path.cwd();directory=root/'data/player-a/live-corrections/20261107-205630-8571dc8b'
meta=json.loads((directory/'metadata.json').read_text());clock=[meta['started_host_uptime']]
tester=LiveTester(joblib.load(root/'artifacts/player-a/gestures-v5/model.joblib'),root/'data/player-a/raw/live-test-01.jsonl',clock=lambda:clock[0])
transitions=[];last=None;count=0
for row in json_lines(directory/'streams.jsonl'):
 if row['kind']!='emg':continue
 clock[0]=row['host_uptime'];tester.packet(row['packet']);status=tester.status();count+=1
 state=(status['gesture'],status['fireball_phase'])
 if state!=last:transitions.append({'capture_t':row['capture_t'],'gesture':state[0],'phase':state[1]});last=state
out={'kind':'offline_replay_not_new_validation','model':'v5','capture':directory.name,'emg_packets':count,'snap_candidates':tester.fireballs,'ready_events':tester.ready_count,'committed':tester.status()['fireballs_committed'],'transitions':transitions}
(root/'artifacts/player-a/gestures-v5/sequence-replay.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
