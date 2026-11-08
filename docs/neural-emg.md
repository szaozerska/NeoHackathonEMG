# Neural EMG development

The new model uses Neuroband EMG only. No new camera work is part of this
workflow. Existing reference-reviewed labels remain historical development data;
images/audio/landmarks are never neural inputs. The v4 fallback and v6 saved
experiment are copied and hash-checked in each experiment's `backups/`.
The live launcher is not switched automatically.

## Architecture and future spells

`configs/neural-emg.json` is the class/task registry. Learned gestures and spells
are separate. `open` is shield evidence, `fist` is sword evidence, and `snap` is
an equip event. Quest geometry and equipment rules stay outside the classifier.
Class definitions must remain consistent: neutral open fingers need not mean
the deliberate open shield hand.

Both architectures are compared on the same reviewed splits with two seeds:

| Model | Input | Layers |
|---|---|---|
| FNN | 40 state features / 160 temporal snap features | Linear 128 → ReLU/dropout → Linear 64 → ReLU/dropout → configurable class logits |
| Temporal CNN | Filtered waveform `[8,410]` state / `[8,256]` snap | Conv1d 16/kernel15/stride4 → Conv1d 32/kernel9/stride2 → Conv1d 64/kernel5/stride2 → four-bin average pooling → Linear64 → logits |

FNN features are RMS, mean absolute amplitude, mean absolute first difference,
zero crossings and slope-sign changes. Features use log1p and training-only
standardization. CNN normalization fits training samples only. All samples
precede the output timestamp; there is no future sensor lookahead.
These are standard PyTorch networks trained locally, not pretrained EMG weights.

Training uses weighted cross entropy, AdamW, early stopping on validation loss,
gradient clipping, dropout and training-only global gain augmentation
(log-normal sigma 0.20). Gain augmentation does not simulate wrist rotation.
Thresholds are selected on validation data, with rejects retained in state
accuracy denominators. Softmax scores are not calibrated probabilities.

Start with the FNN as the nonlinear baseline and compare the CNN on waveforms.
Current data do not establish that a CNN, RNN or transformer will be better.
A GRU/LSTM is a later option for longer gesture sequences; a transformer is
lower priority until there is considerably more varied training data.

To add a sustained gesture, add its name to `tasks.state.classes`, collect with
`--kind NAME --instruction "..."`, and retrain into a new directory with old and
new class examples. Output size and class order derive from the registry.
Map gestures to spells outside the model; `spell_mapping` is metadata only.
There is no automatic incremental learning or guarantee against forgetting.
New event types can use additional registered event heads with reviewed example
manifests. The guided event collector currently handles snap/background.

## Collect twenty snaps without a camera

Start a new raw recording in Kinesis at the supplied path, then run:

```sh
.venv/bin/python scripts/collect_neural_emg.py \
  --kinesis-file data/player-a/raw/neural-new.jsonl \
  --wearing-session wearing-03 --kind snap --repetitions 20
```

Each repetition has a countdown, a three-second interval and a count confirmation.
Twenty snaps means twenty short clips with one requested snap each. Confirm the
actual count, enter `0` for a missed action, or `x` to discard uncertain clips.
Source uptime must be fresh; interrupted recordings are not complete sessions.

Instructions balance **soft/firm × minimal/natural/exaggerated rotation**. Next
collect matching controls using the same command with `--kind negative`:
wrist rotation without snaps, larger wrist movements, finger touch/release,
fist closing/opening, finger curling and natural reaching. Also collect separate
`--kind fist`, `--kind open` and `--kind none` blocks at varied arm angles.
Keep the same wearing-session ID until removing/repositioning the band.

Positive clips train with a multiple-instance loss: at least one snap somewhere
in the clip. No exact onset is fabricated from the countdown. Counts greater
than one remain metadata, not guessed positive windows or an exact-count loss.
Confirmed zero-snap clips supply negative windows. Holds supply participant-
confirmed state training labels. These are weak labels; historical reviewed
examples continue to anchor event localization.

## Train, preserve the fallback and compare

Install optional dependencies with `.venv/bin/python -m pip install -e '.[neural]'`.
Local additions are pinned in `requirements-neural-lock.txt`.

```sh
.venv/bin/python scripts/train_neural_emg.py \
  --output artifacts/player-a/neural-emg-NEXT \
  --review artifacts/player-a/v4-camera-review-221247/reviewed-labels.json \
  --guided-capture data/player-a/neural-guided/CAPTURE_ID
```

`--review` reuses old reviewed labels; it does not run a camera. Omit it to use
only the original reference review. Repeat `--guided-capture` for more blocks.
New guided examples enter training only. `--dataset` reuses a trusted locally
generated `neural-dataset.joblib`. Raw and label hashes are verified; complete
trial/block splits are preserved and overlapping raw windows cannot cross splits.
Training fits normalization; validation selects epochs/thresholds. Recording
never updates models. Every run saves both architectures/seeds, frozen-before-
check hashes, source provenance, backups, baseline comparisons, confusion matrices,
event outcomes and a failure-review queue. Check errors never auto-refit.

For new reviewed classes/heads, `--examples path.json` accepts this schema:

```json
{
  "independently_reviewed": true,
  "source_hashes": {"examples.npz": "SHA256", "source.jsonl": "SHA256"},
  "tasks": {"state": {"arrays": "examples.npz", "rows": [
    {"session": "recording-ID", "group": "original-clip-ID", "trial": "clip-ID", "part": "train", "label": "new_gesture", "start": 1.0, "end": 1.2}
  ]}}
}
```

NPZ keys are `features[N,F]` and `waveforms[N,8,T]`, using saved preprocessing.
Event evaluation rows also need `expected_events` in the same time basis.
Ambiguous supervised event windows use a null label. The manifest's review flag
records a review assertion; software cannot independently certify its truth.

## Count checks without a camera

Freeze the candidate, remove/reapply the band, and collect new blocks with a new
wearing-session ID and `--role evaluation`. Training refuses these reserved
captures. Include snap variants, controls, holds and ordinary movement. Run:

```sh
.venv/bin/python scripts/evaluate_neural_guided.py \
  --model artifacts/player-a/neural-emg-NEXT \
  --capture data/player-a/neural-guided/EVALUATION_CAPTURE \
  --output artifacts/player-a/guided-count-check.json
```

This replays frozen EMG predictions, compares emitted and reported counts, and
reports false events/minute on confirmed zero-snap clips. Training recordings or
the same wearing session require explicit `--development`. Participant counts
are external reports, not independently measured event times: a miss and a false
positive can cancel. Equal counts cannot establish event precision or recall.

99% remains a target. Report per-class recall, event precision/recall when timing
labels exist, false events/minute, rejection coverage and transitions on untouched
wearing sessions/people. Twenty successes provide little evidence for a 99% claim.
Historical checks have already been inspected and are development regressions.

```python
from spelltrain.neural import NeuralEMGPredictor
predictor = NeuralEMGPredictor('artifacts/player-a/neural-emg-NEXT')
outputs = predictor.feed(decoded_emg_packet)
```

Outputs are `neural_scores`, `neural_state` and `neural_event`; game logic handles
spells. Unknown differs from the learned background class. Gaps reset decisions;
event rearming and a 350ms refractory interval suppress duplicate emission.
This is experimental Python inference; headset export/integration remains separate.

References: [PyTorch Conv1d](https://docs.pytorch.org/docs/2.15/generated/torch.nn.Conv1d.html)
and [checkpoint loading](https://docs.pytorch.org/tutorials/beginner/basics/saveloadrun_tutorial.html).
