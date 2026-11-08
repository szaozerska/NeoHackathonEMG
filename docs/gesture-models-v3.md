# V3 EMG gesture baselines

The completed session is preserved in `data/player-a/band-01`. Its 48 confirmed clips support initial hand-state and relative-effort models, plus a weakly supervised snap model. No verified snap timestamps are fabricated and original annotations remain unchanged.

## Saved models

`artifacts/player-a/gestures-v3/` contains:

- `model.joblib`: combined causal hand-state, shield-effort and weak snap inference bundle.
- `hand-state-model.joblib`: open / fist / relaxed classifier; the fist class is the sword input, and the open class is only part of the shield gate.
- `snap-model.joblib`: experimental multiple-instance snap model and validation-selected clip threshold.
- `training-report.json`, `REPORT.md`, per-trial CSVs and hashed label/source manifest.
- `snap-candidates-for-review.json`: approximate candidate locations, all explicitly unverified. These are not training truth or verified event detections.

The shield effort model at `artifacts/player-a/shield-effort-v3/effort-model.joblib` is copied into the combined bundle without refitting. Its original test round had already been scored; the new trainer verifies matching source hashes and preserves its fitted parameters.

Reproduce in a new output directory:

```sh
.venv/bin/python -m spelltrain train-gestures \
  --session data/player-a/band-01 \
  --effort-model artifacts/player-a/shield-effort-v3/effort-model.joblib \
  --output artifacts/player-a/gestures-v3-reproduction
```

Round 1 fits models, round 2 selects features/clip thresholds and round 3 is scored. Never distribute overlapping windows from a trial across splits. Every feature uses causal filtering with the sensor timestamp, sequence-loss resets, and 0.75-second recording-edge trims. Host Bluetooth-delivery jitter does not reset the filter. Models do not silently refit on validation/test rounds.

## Current results

| Component | Round-3 result | Interpretation |
|---|---|---|
| Sword fist vs other steady holds | 12/13 correct (92.3%) | 2/3 fists detected, zero false positives across ten open/relaxed holds; the palm-up fist was missed |
| Shield open hand vs other steady holds | 13/13 correct | All nine open holds distinguished from three fists and one relaxed hold; no spatial pose accuracy claim |
| Shield light/medium/firm effort | 7/9 correct (77.8%) | Two light/medium confusions; all three firm trials correct |
| Fireball whole-clip snap classifier | 16/16 correct | Only one positive test clip, containing an unknown exact count of snaps; 15 non-snap test clips |
| Fireball causal candidate on/off per clip | 14/16 correct (87.5%) | Snap clip triggered, but ordinary movement and pinch clips also triggered |
| Individual snap-event precision, recall and latency | Unknown | Needs independently verified snap times/counts |

The causal snap rule generated two false candidates across 63.8 seconds of trimmed non-snap test clips (about 1.88/minute in those selected clips). The positive clip generated four candidates, which cannot be matched to actual snaps without a reference. This is not a continuous-play false-activation rate. Whole-clip pooling and instantaneous candidate scoring are different operations; the clip score is not evidence of perfect casting.

The snap model uses smooth-max multiple-instance logistic learning: a positive clip says a snap occurred somewhere in it. It does not train every frame of that clip as a snap. Only one positive clip is available for each split. The trimmed interior is assumed to retain at least one snap, consistent with the prompt; timing reference data is needed to verify that assumption. An always-negative classifier would achieve 15/16 clip accuracy; report the detected positive and false positives alongside accuracy.

All scores come from one person and one band-wearing session. They do not establish performance after replacing the band or during gameplay. Hand-state scores average probabilities over steady clips; live thresholding, debounce and closing/opening latency need separate testing. Validation also confused a relaxed clip with a fist, which reinforces the need for more relaxation/fist examples.

## Causal inference and live preview

```python
import joblib
from spelltrain.gestures import GesturePredictor

bundle = joblib.load('artifacts/player-a/gestures-v3/model.joblib')
predictor = GesturePredictor(bundle)
for prediction in predictor.feed(decoded_emg_row):
    print(prediction)
```

One shared sensor-time filter emits hand state, an ordinal effort index, and experimental snap candidates. Default candidates do not cast fireballs. `GesturePredictor(bundle, experimental_snaps=True)` explicitly enables provisional snap events for testing; that does not change their unverified status.

For a NEW session, the recorder accepts this bundle through `--model` and feeds effort into the server-side shield gate. The optional `--experimental-snaps` flag allows provisional candidates to trigger the fireball preview. Without it, candidates are saved for review while state and effort still run. No physical headset gameplay validation has been performed.

```sh
.venv/bin/python -m spelltrain record --subject player-a \
  --session data/player-a/band-02 --emg-only \
  --kinesis-file data/player-a/raw/band-02.jsonl \
  --model artifacts/player-a/gestures-v3/model.joblib
```

Band-only mode cannot supply shield pose or throw geometry. Add the Quest stream in paired mode for those checks. Unity visuals, collisions and physical headset testing remain separate integration work; an EMG model cannot validate finger direction or arm extension.

Evaluate an untouched later complete v3 session with frozen models:

```sh
.venv/bin/python -m spelltrain evaluate \
  --sessions data/player-a/band-02 \
  --model artifacts/player-a/gestures-v3/model.joblib \
  --output artifacts/player-a/gestures-v3-session-02-evaluation
```

This refuses the training source, even if copied to another directory, unless `--development` is explicit. Development replay is labeled accordingly. It scores confirmed clip labels, not individual snap events or Quest accuracy.

## Data priorities from these results

1. More relaxed hands and fist holds at all angles, especially palm-up; add opening/closing transitions and ordinary tasks to test unintended sword activation.
2. Isolated middle-thumb snaps with synchronized video/audio or another independent timing reference, plus pinches and ordinary finger/wrist activity. Review exact event times/counts and leave an independent test set untouched.
3. Separate wearing sessions, then simultaneous Quest/band sessions for shield pose/movement and fireball throwing. Do not tune against round 3 and continue calling it an untouched test.
