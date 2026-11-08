Current active preset: original v4 weights with brief feedback, restored at the user’s request. Camera/reference logging is optional and retained independently. See [rollback analysis](rollback-v4-analysis.md).

# Live EMG model test

Double-click `Start Live Model Test.command`, or run:

```sh
.venv/bin/python scripts/start_live_test.py --background --open-browser
```

The launcher loads `artifacts/player-a/gestures-v4/model.joblib`, starts the local tester and opens its URL. It uses port 8765, falling back to 8766 if another app occupies 8765. It leaves existing training apps and saved sessions unchanged.

In the compatible Kinesis app, start a new live EMG raw recording at the exact path displayed in the tester. The launcher chooses an unused `data/player-a/raw/live-test-NN.jsonl` path. Use **Copy recording path** on the page. Keep Kinesis recording while testing. The page does not need camera or microphone access.

- Relaxed/uncertain hand state displays **Nothing**.
- A predicted closed fist displays **Sword**.
- A predicted open shield hand displays **Shield** and the effort model's winning light/medium/firm class.
- A supervised snap event displays **Fireball** for 1.25 seconds and increments a counter. The display then returns to the current hand state. **Reset count** only resets the displayed counter.

This is direct EMG classifier feedback, not the Quest gameplay state machine. The open-hand result cannot confirm fingers up, outward palm orientation or extended arm. Effort is relative muscle activation, not physical force. Display timing and the snap counter are presentation features; trained parameters are unchanged. The model's known occasional fist misses and extra toggles remain visible.

Input is tailed from the current end of an existing file, never replayed as if it were live. Old packet host timestamps are rejected. Stale/disconnected input clears the gesture rather than leaving a sword/shield displayed. The tester does not append to training streams, labels or model files; Kinesis's new raw recording remains a separate file.

Direct CLI:

```sh
.venv/bin/python -m spelltrain live-test \
  --model artifacts/player-a/gestures-v4/model.joblib \
  --kinesis-file /absolute/path/to/live-emg.jsonl --web-port 8765
```

The tester uses one causal `GesturePredictor` for hand state, effort and reference-supervised snaps. It reads no webcam/microphone reference files and does not retrain during testing.


## Decision memory update

The observed Kinesis file feed writes about every 0.5 seconds. The previous tester expired state after 0.3 seconds, which could repeatedly display Nothing even when packets were not lost. Feed and state freshness now allow 1.25 seconds, while actual sequence loss clears decision memory.

The tester consumes raw state probabilities rather than treating every low-confidence frame as a release. It keeps a rolling 0.8-second evidence history, uses a 0.12-second exponential smoother on the sensor clock, and requires sustained evidence to change the gesture. A fist-to-open change has a shorter confirmation period than a change to relaxed/none. Brief uncertainty holds the current gesture; prolonged ambiguity is bounded rather than latching a sword indefinitely. Effort probabilities have a separate 0.25-second smoother and a small class-change margin/confirmation period.

These changes affect live decision presentation only. The fitted v4 model files and historical evaluation results are unchanged. No new accuracy claim is established by the smoothing tests. Raw-file transport still adds up to roughly half a second of batching latency; this update prevents that normal batch interval from blanking the result. Real stream loss clears the display after the bounded freshness period.


## Superseded snap / shield conflict confirmation

The snap network can react to the initial activation when raising a shield. Its short transient window produces evidence before the hand-state smoother settles; previously any snap event immediately overrode the gesture display and incremented the counter. Conversely, real snaps also produce temporarily high open-hand probabilities, so simply banning every snap near an open hand would reject genuine examples.

This confirmation experiment was removed after live feedback showed it obscured genuine snaps. See [live correction recording](live-correction-recording.md) for the current behavior. The experiment deferred snap candidates. It observes subsequent raw hand-state evidence on the sensor clock: sustained open-shield evidence wins, while recovery from a transient can confirm a snap. Confirmation is typically 0.45–0.8 seconds of additional sensor evidence, plus transport batching. Neither a Fireball label nor the counter updates before confirmation. Insufficient evidence, missing packets and clock discontinuities discard pending candidates. Ambiguous actions ending in a sustained shield hand pose favor Shield.

Unit tests cover the shield-entry false-trigger pattern and genuine transient snaps. Retrospective replay retained one snap in each of the ten existing reference snap clips. That is a regression check on previously used data, not a new independent accuracy result or a guarantee against every possible confusing motion. Fitted model parameters and stored recordings are unchanged; the confirmation rule currently belongs to the live tester.
