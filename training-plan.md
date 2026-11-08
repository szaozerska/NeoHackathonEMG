# Training plan: gesture protocol v3

This replaces all earlier fist-shield, push/jerk, and sword-draw training requirements. Old recordings and the initial effort artifact were deleted at the user's request on November 7, 2026. Initial v3 models are now trained; see [model results and use](docs/gesture-models-v3.md). The saved recordings are retained.

## Confirmed gestures and detection split

| Spell | Band detects | Quest supplies | Behavior |
|---|---|---|---|
| Shield | Open hand and calibrated relative forearm effort | Palm normal, upward finger direction, hand pose, torso-relative reach, tracking quality | Extended arm, open palm toward opponent, fingers up. Hold pose to maintain. Strength follows effort continuously; moving changes shield pose. Stop pose to dismiss. No thrust/jerk requirement. |
| Sword | Sustained fist at any wrist angle; release | Sword position and rotation | Closing summons immediately; opening dismisses. No hip position or drawing sequence. |
| Fireball | Middle-finger/thumb snap event | Hand position and subsequent throwing trajectory | Snap immediately equips Fireball. Subsequent opening keeps it equipped. Keep ready while open. A fist cancels it and equips Sword. Only a fresh Quest-confirmed forward open-hand throw commits it. |

One band on the right arm per player. EMG effort is a relative muscle-activation control, not measured physical force. The initial light/medium/firm model provides an ordinal effort index; a continuous proportional protection curve still needs calibration and gameplay testing. Hand rotation is not a reason to dismiss a sword.

## Band collection now

Run `scripts/start_emg.py --background` with the repository's `.venv/bin/python`, then visit http://127.0.0.1:8765. Start Kinesis raw EMG recording at the exact path displayed on the page.

The new guided flow is **48 trials: three rounds of 16 conditions**:

- Nine shield conditions: light, medium and firm effort at center, left and right positions. Keep fingers open and pointing up, palm outward. These are steady holds, not pushes.
- Three sword conditions: thumb side up, knuckles up and knuckles down. These provide varied angles, not three separate spells. Vary arm position between rounds.
- Relaxed baseline, isolated middle-thumb snaps, finger/thumb touches without snapping, and ordinary hand/wrist movement.

Establish the requested steady pose and tension **before** pressing Start Record. Hold for about five seconds, then Stop. For snaps and comparison movements, press Record first, wait one second, then perform the requested actions. Use comfortable effort; firm is not a maximum contraction. Rest five seconds between attempts. Save only if the prompt was performed correctly; otherwise retry. “Received” confirms EMG capture, not recognized intent.

Labels are in `gesture-trials-v3.json`, protocol `spells-open-shield-effort-v3`; raw samples remain in `streams.jsonl`. Keep both. Signal check recordings remain separate. Capture quality, intended effort and participant confirmation are retained; no exact snap times or verified pose labels are invented.

## Training and evaluation

For the first effort baseline, close the session and run:

```sh
.venv/bin/python -m spelltrain train-effort \
  --session data/player-a/band-01 \
  --output artifacts/player-a/shield-effort-v3
```

This trains only on the 27 open-hand shield effort trials. Round 1 trains, round 2 selects the feature set, and round 3 tests once. Comparisons are diagnostics. The model is not refitted on test data. It never reads the old fist-shield labels. Adjacent overlapping windows cannot cross round/trial splits. Report whole-trial accuracy and confusion, not only window accuracy.

For hand-state and snap detectors, review recordings in Advanced tools first:

1. Verify stable `open`, `fist`, and `none` intervals. Trim transitions and recording-button edges. Record extra varied open-hand and fist holds if needed.
2. Mark each actual snap as a `snap` point event after inspecting timing against a synchronized reference. A five-second clip with several snaps is not a five-second snap event. The guided labels are deliberately not auto-converted to precise event ground truth.
3. Verify non-snap `hard_negative` intervals, including pinches, wrist movements, clenching and ordinary activities. A random hand motion is not automatically a verified `none` hand state.
4. Collect independent sessions with the band removed/replaced. Use different complete sessions for training, validation and untouched testing. Evaluate false activations, missed snaps and activation/dismissal latency. Multiple trials in one session do not establish cross-session accuracy.

The new `train-gestures` command also supports these guided reports directly: it trains steady hand states and a weakly supervised snap-clip model, with no invented event times. Its individual-event accuracy remains unknown. See [results and limitations](docs/gesture-models-v3.md).

The existing `train --train ... --validation ... --output ...` primitive trainer consumes these verified annotations, not guided trial reports. It is separate from `train-effort`. Neither command automatically activates a model or renders a spell. Validate sensor-time handling before relying on the legacy primitive trainer with live Bluetooth batching; the effort trainer already uses sensor timestamps and sequence continuity.

## Quest and fusion later

Collect fresh simultaneous band and Quest sessions to validate the combined behavior. Quest must supply calibrated palm direction and middle-finger direction plus valid hand/chest tracking. A missing or zero finger direction cannot establish shield pose. Hand position relative to the chest currently checks reach; it does not measure elbow straightness. Add shoulder/elbow joints if strict arm-extension verification is required.

Snap and posture remain distinct observations. A detected snap immediately equips Fireball; a subsequent open hand preserves it. A confirmed fist cancels pending or ready fireball immediately and equips Sword. Band-only operation never commits a fireball. Continuous Quest tracking must confirm a forward throw with a fresh open-hand observation.

The server-side `SpellEngine` now supports stationary shield activation, pose updates, dismissal, effort updates, immediate fist swords and snap-then-throw fireballs. `effort(value, t)` accepts a relative 0–1 effort control. The new combined v3 bundle feeds its ordinal effort index into that method. The protection mapping and live shield-strength behavior still need calibration and headset evaluation.

The Unity sender transmits tracking observations; the Mac/server decides spell state. Unity rendering, held-fireball visuals, sword orientation and collision/protection effects remain game integration work. Fingers-up uses game-space up and palm facing uses the opponent direction, with configurable tolerances. A lateral movement remains valid as long as the pose still meets these conditions. Throwing needs fresh continuous tracking; a reacquisition jump must not throw a held fireball.

Do not use the older hip/push `calibrate` workflow for this protocol. The current default pose/throw thresholds are starting values; calibrating them and evaluating paired positive/negative recordings is required before gameplay claims. Headset deployment and physical accuracy have not been tested for v3.


Current live tester: [v5 update and limitations](docs/gesture-models-v5.md). The EMG classifier uses EMG only. Webcam/audio are optional training-label references, never image-model inputs. Quest supplies spatial motion, sword speed/direction, collisions and fireball throw confirmation; effort is relative activation, not measured force or damage. Shield world placement/orientation and full spatial pose verification also require Quest.


The current tester/model is [v6 with immediate snap equipment and independent camera review](docs/gesture-models-v6.md). This supersedes v5 open-confirmation semantics. Webcam/audio observations are independently logged and reviewed; they do not enter band inference. Shield-release and other transitions have explicit collection cues.


Fireball-to-Shield update: a confirmed full Quest shield pose cancels equipped Fireball and activates Shield. Merely detecting an open hand does not cancel it. The current EMG bundle has one open-hand class, so the band-only tester offers an explicit Switch to Shield command while open; this is logged as participant input, not a model prediction or verified training label. Classifier weights are unchanged by this equipment-rule update.
