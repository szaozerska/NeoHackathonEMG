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

Omit `--kinesis-file` to read Kinesis's live stream instead of a raw recording:
enable Live EMG, copy the URL from Kinesis's **stream** tab and paste it when the
collector asks (the token changes per Kinesis launch and is never saved). Its
`host_time_s` is the same Mac uptime clock as the raw file. A reader that falls
more than one second behind is disconnected and reconnects; the lost batches
appear as sequence discontinuities in `metadata.json`. `band_source` records
which path a capture used.

During counted clips (`snap`, `negative` and `--event` gestures), press **space
with the other hand right after every action**. Presses are accepted until one
second after STOP, and the count prompt defaults to the number of presses. Each
trial saves `action_marks` (capture_t seconds), `marks_match_count` and the
press source; streams.jsonl also logs each press as an `action_mark` row. Marks
include human reaction delay (roughly 200–300 ms, variable); they are
participant reports, not verified onsets (`exact_event_times_verified` stays false).

Every capture also records the default microphone to `audio.wav` (48 kHz mono
int16) with `audio-timing.jsonl`. Each timing row gives a block's first frame and
its host timing; the first sample's capture_t is
`callback_capture_t - (stream_current_time - adc_time)`, the same clock as EMG
`capture_t`. Audio is a label-timing reference for refining marks to the action
transient. It is never a model input.
`guided_only_dataset` does this refinement (`spelltrain/snap_onsets.py`): each
mark moves to the sharpest isolated 2–8 kHz transient in the 0.8 s before it, and
a trial is accepted only if every mark finds one (SNR ≥ 10, ≥ 3× any other peak
>100 ms away) and the EMG burst lies within ±150 ms. Accepted trials give snap
windows ending 50 ms before to 125 ms after the onset, negatives clear of a
±0.3 s zone, and `expected_events`; the newest quarter validates snap recall.
Rejected trials stay weak count bags. A held kind with a single capture
validates on the last 20% of each clip.

`guided_only_dataset(..., interval_directories)` (`--interval-capture`, and the
Modal sweep by default) also loads Micah's Space-interval contributions under
`Micah contributed data/{static,dynamic}` (`add_interval_capture`): shield/sword
holds become `open`/`fist`, non-intended time becomes `none` and snap negatives
(0.3 s boundary margin, 1 s clear of published snap-like candidates), and snap
intervals become count bags. Per class, the last 30% of intervals validate;
validation snaps use the published reference peak as their expected event.
Ambiguous windows near an event are replayed for event scoring but never fitted. Grant the terminal microphone access when
macOS asks; collection stops if the microphone delivers pure silence. Both audio
files are hashed in `guided-manifest.json`.

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
