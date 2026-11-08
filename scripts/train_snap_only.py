"""Train a separate EMG-only snap detector without modifying the active bundle."""
import argparse
from spelltrain.snap_only import train_snap_only
p=argparse.ArgumentParser();p.add_argument('--base',default='artifacts/player-a/gestures-v4/model.joblib');p.add_argument('--review',default='artifacts/player-a/v4-camera-review-221247/reviewed-labels.json');p.add_argument('--output',required=True);a=p.parse_args()
r=train_snap_only(a.base,a.review,a.output)
print({'selection':(r['selection']['family'],r['selection']['C'],r['selection']['threshold']),
       'development':{k:r['development_check']['candidate'][k] for k in ('tp','fp','fn')},
       'reference':{k:r['known_reference_regression'][k] for k in ('tp','fp','fn')},'activated':False})
