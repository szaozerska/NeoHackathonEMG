# Standalone EMG-only snap candidate

`artifacts/player-a/snap-only-01/snap-model.joblib` is a separately fitted snap-versus-background classifier with its own causal `SnapOnlyPredictor`. Its input is eight-channel EMG with sensor timestamps/sequence only. No Sword/Shield probabilities, camera landmarks, images, audio, equipment state or intended-action marks enter inference. Reviewed video/audio are used only to establish action labels during offline training. The state and effort models and active v4 localhost remain unchanged.

Training used existing independently reviewed reference data plus the first two reviewed snaps and labeled negatives from the new recording. Candidate families compare absolute log-RMS temporal features with amplitude-normalized burst-shape features, with and without an energy term. Only training windows fit scaling and classifier weights. The older validation clips plus one new validation snap select the family, regularization and threshold. The selected model uses temporal log-RMS, C=0.03, threshold=0.999. All settings were frozen before development scoring. This is a new fitted snap classifier, not a copied bundle.

The seven later snap events were already examined in the preceding retraining comparison; they are explicitly development regression, not an untouched test. The standalone fit finds 2/7 events with two extra events; v4 finds 0/7 with zero extra events. The known older reference regression remains 5/5 with no extra events at ±250 ms matching. These tiny, previously examined sets do not establish general accuracy or measured latency. Two later event times have visual-only approximate timing. The candidate has not been activated.

Separating the detector helps isolate snap performance and prevents posture/equipment rules from being mistaken for snap recognition. It does not make the electrical signal intrinsically easier to classify. Collect light/normal snaps and hard negatives (finger presses, incomplete snaps, quick fists, shield release), annotate performed actions independently, and reserve a separately donned session for a fresh test. Include successful normal examples, not only failures.

Reproduce into a new output directory:

```sh
.venv/bin/python scripts/train_snap_only.py --output artifacts/player-a/snap-only-NEW
```

Inference:

```python
import joblib
from spelltrain.snap_only import SnapOnlyPredictor
predictor = SnapOnlyPredictor(joblib.load("artifacts/player-a/snap-only-01/snap-model.joblib"))
# packet contains source_seq, source_t (microseconds), samples (N × 8)
observations = predictor.feed(packet)
```

Outputs are scores and deduplicated/rearmed snap events. Equipment memory is a separate consumer: a snap equips Fireball; neutral/open holds preserve it; a confirmed fist cancels it for Sword. There is no posture veto inside this detector. Standalone inference by itself cannot establish a Quest throw or launch.
