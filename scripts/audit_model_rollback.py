"""Compare frozen EMG classifiers and presentation policies on existing feedback.
This is development replay, not a new independent accuracy test.
"""
import json,hashlib,copy
from pathlib import Path
import joblib
from spelltrain.common import json_lines
from spelltrain.gestures import GesturePredictor
from spelltrain.live_test import LiveTester

class ReplayOutputs:
    def __init__(self):self.outputs=[]
    def feed(self,row):return self.outputs

root=Path(__file__).resolve().parents[1];out=root/'artifacts/player-a/rollback-v4-audit';out.mkdir(exist_ok=True)
report={'kind':'development_replay_weight_and_policy_comparison','ground_truth':'participant intent windows; no verified event timestamps','models':{},'captures':[]}
captures=['20261107-204149-e28bdbac','20261107-205630-8571dc8b','20261107-212304-5dbb9730']
for name in captures:
 directory=root/'data/player-a/live-corrections'/name;meta=json.loads((directory/'metadata.json').read_text());marks=json.loads((directory/'corrections.json').read_text())
 packets=[row for row in json_lines(directory/'streams.jsonl') if row['kind']=='emg'];capture={'id':name,'packets':len(packets),'versions':{}}
 for version in ('v4','v5','v6'):
  model_path=root/'artifacts/player-a'/('gestures-'+version)/'model.joblib';artifact=joblib.load(model_path);predictor=GesturePredictor(artifact)
  report['models'][version]={'sha256':hashlib.sha256(model_path.read_bytes()).hexdigest(),'snap_threshold':artifact['snap_threshold']}
  clock=[meta['started_host_uptime']];replay=ReplayOutputs()
  testers={policy:LiveTester(artifact,root/'data/player-a/raw/live-test-01.jsonl',clock=lambda:clock[0],predictor=replay,display_policy=policy) for policy in ('v4_feedback','equipment')}
  events=[];transitions={policy:[] for policy in testers};previous={policy:None for policy in testers};weak_states=[]
  for row in packets:
   clock[0]=row['host_uptime'];packet=row['packet'];received=row['capture_t']
   replay.outputs=predictor.feed({'kind':'emg','received':received,'t':received,**packet})
   events.extend({'capture_t':received,'source_t':p['source_t'],'score':p['confidence']} for p in replay.outputs if p['kind']=='snap')
   for policy,tester in testers.items():
    tester.packet(packet);gesture=tester.current_gesture(clock[0])[0]
    if gesture!=previous[policy]:transitions[policy].append({'capture_t':received,'gesture':gesture});previous[policy]=gesture
  checks=[]
  for i,mark in enumerate(marks):
   if mark.get('timing')!='before':continue
   start=mark['reported_at']+.05;end=min(mark['review_window_end']-.1,marks[i+1]['reported_at']-.1 if i+1<len(marks) else meta['duration_seconds'])
   selected=[p for p in events if start<=p['capture_t']<=end]
   checks.append({'gesture':mark['gesture'],'start':start,'end':end,'snap_events':len(selected),'intended_snap':mark['gesture']=='Fireball','verified_physical_actions':False})
  capture['versions'][version]={'raw_snap_events':events,'intent_clip_checks':checks,'display_transitions':transitions}
 report['captures'].append(capture)
 print(name,{version:len(values['raw_snap_events']) for version,values in capture['versions'].items()},flush=True)
(out/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
print(out/'comparison.json')
