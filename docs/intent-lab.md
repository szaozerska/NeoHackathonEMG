# Intent lab: collection before retraining

Open http://127.0.0.1:8765 after starting `Start Partner Bench.command`.
For a fresh machine, install the optional local webcam assets with
`bash scripts/setup_partner.sh --with-game --with-camera`. Existing environments
can run `.venv/bin/python scripts/install_camera_observer.py` directly.
The original v4 tester remains at `/live`; its saved weights and tension model
are preserved. The main page now runs guided collection and a separate,
explicitly provisional equipment-rule preview.

## Current behavior being investigated

**For Sophie: build bottom-up.** First collect binary intended/non-intended
activity without gesture labels. After evaluating that gate, independently
validate snaps and open/grip states. Only then learn temporal transitions from
longer sequences. See architecture.md §2.2.1 for the pyramid diagram and full
training contract. No intent gate has been fitted yet.

First detect a real snap. A short subsequent open-hand confirmation equips
Fireball. A confirmed clasp/grip cancels either pending or held Fireball and
selects Sword. A pending snap that never receives open-hand confirmation expires;
the participant must snap again. An already equipped Fireball persists through
open-hand movement or uncertain hand classification. A missing sensor pauses
the visible preview; it does not establish a grip. Quest supplies position,
palm direction and throw confirmation in the eventual game integration.

The preview currently uses a provisional 2-second maximum opening deadline, no minimum snap-to-open delay,
and 150 ms of grip evidence above a provisional 0.85 classifier score. These are
diagnostic starting values, not calibrated confidence or proven optimal timing.
Raw predictions and transition recordings are retained so reviewed action times
can select the actual thresholds/deadline on validation data. Runtime v4
classification is not silently retrained or replaced.

## First collect the intent gate, then the action sets

Start with **A. Continuous intent toggle + live camera**. The single toggle is
red/off for ordinary non-intended activity and green/on for intended
interaction. Select its initial state before starting, or toggle while recording.
The camera keeps observing in both states. Prefer using the non-band hand to
click. No action name or snap count is required.

The default guard excludes **one second before and one second after** every
reported button interaction, keyboard interaction and toggle, plus measured
clock uncertainty. Change it to 0.5–3 seconds before recording if needed. The
export also removes signal gaps and short remnants. This is conservative
clipping, not proof that the remaining interval expresses intention perfectly.
If the movement starts near a click or the guard seems too short, increase it
or discard the affected interval at review.

`intent-toggle-markers.json` retains the original reported boundaries;
`interaction-exclusions.json` retains exclusion windows;
`intent-gate-intervals.json` stores usable weak binary intervals, intersected
with continuous EMG coverage. The current intent-gate dataset is not fitted or
deployed automatically. Separate fitting, validation and evaluation by whole
wearing session. Exclude historical data from new fitting by default; retain
old models as baselines.

**A. Intended vs non-intended — no gesture labels** also offers guided binary
blocks with explicit per-block confirmation. Those produce the separate
`intent-gate-trials.json` export.

After evaluating that gate, collect the action sets:

1. **Snaps:** 20 separately confirmed clips, balancing relaxed/soft, natural and
   comfortable firm snaps. Choose arbitrary angles continuously; do not restrict
   movement to fixed 45/90-degree poses. Vary arm height, hand tilt and wrist
   rotation. Each clip requests one snap; report the actual count, including
   zero for a missed attempt. A count is never an exact event timestamp.
2. **Controls:** relaxed rest, finger fidgeting with a still wrist, continuous
   wrist sweeps, waving/reaching, whole-arm swings, walking, thumb/finger touches,
   grip transitions, and failed snap attempts. Report any actual snap. Keep
   spell intent separate from observed physical action; the software cannot
   infer intention merely from camera shape or EMG amplitude.
3. **Stability:** 10-second open-hand holds and definite grip holds, varying arm
   and wrist angle. Palm-up is not required. The open Fireball hold is saved as
   `open_hold`, separately from the old deliberate open shield class. EMG channel
   variation, camera wrist motion and available band motion are measurements,
   not automatic declarations of stability or intention.
4. **Transitions:** snap→open→grip with slow/natural/quick transitions,
   snap→immediate grip without opening, and snap→open while moving. Preserve
   full time series; review open/grip boundaries before learning transition
   intervals or choosing the opening deadline. Never label the entire clip as
   a snap or use cue time as the action onset.

Every trial has a three-second countdown, a recording window, and a report.
Reports never assume success. Discard/retry preserves the failed attempt. A
failure button bookmarks the preceding eight and following two seconds. Keep
recording long enough to retain that follow-up. Finishing early retains the
interrupted trial as unconfirmed.

Keep the same wearing-session ID for all four sets without moving the band.
Remove/reapply the band and use a new ID for another session. Reserve at least
one complete wearing session for evaluation; keep it out of fitting and
threshold selection. More than one training session is needed to separate
fitting and validation by wearing session.

## Sensors and camera

The raw Kinesis file provides eight-channel EMG only. To record every available
stream, enable Kinesis's **stream → local sensor feed**, copy its URL into
**Sensor connection and orientation**, and verify the EMG/orientation/gyro
indicators. The same connection saves raw events for EMG configuration, decoded
gestures, orientation, gyro and connection status. Unavailable streams are
explicitly marked; no missing sensor values are fabricated. No accelerometer
endpoint is assumed if Kinesis does not expose it.

Quaternions retain the band's frame and original band timestamps; host receipt
uptime is retained separately. Relative quaternion paths are sign-invariant.
They describe wrist orientation, not finger pose or an absolute world-space palm
normal. A camera or Quest can supply independent pose context, with its own
uncertainty. Wrist rotation alone never constitutes a snap.

Face the computer with the band hand visible. Enable the webcam and optional
microphone directly in the browser. The display is mirrored; check the hand
label overlay and target selection. Open/fist estimates come from the existing
MediaPipe hand landmark observer, running in a worker with locally cached
assets. This fits the existing browser pipeline and provides hand keypoints;
generic YOLO person-pose weights are not a hand classifier. An appropriately
trained YOLO hand-keypoint model remains a possible future comparison.

Browser/host alignment uses the lowest-round-trip estimate among five local
clock requests. Each observation carries alignment and uncertainty, and the
video reference retains its recording-start events. This is approximate
software synchronization, not hardware synchronization. Independent visual
classification is fallible under occlusion, edge-on hands, camera delay and
handedness errors. Snap timing still requires review of synchronized video/audio
and EMG; neither a sound peak nor an observer estimate is automatically truth.

## Files and training boundary

All files remain under ignored `data/player-a/live-corrections/CAPTURE_ID/`:

- `streams.jsonl`: raw EMG, available band events, predictions, camera evidence,
  cues, confirmations and failure bookmarks on the host monotonic timeline.
- `intent-trials.json`, `collection-plan.json`, `failure-flags.json`: reports,
  intended instructions and approximate failure review windows.
- `camera/`: reference media and alignment/provenance when camera recording
  succeeds. Browser camera permission is an interactive wearer action.
- `camera-state-proposals.json`: independent visual open/grip interval
  suggestions, split at occlusion or tracking gaps, for review rather than
  automatic supervised labels.
- `guided-trials.json` and `guided-manifest.json`: source-hashed compatible weak
  snap/negative and confirmed grip clips. Open-hold and transition clips remain
  separate for review; they are not silently relabeled as shield or fist.
- `collection-report.json`: coverage, unusable clips, count differences and
  false snap candidates/minute on confirmed zero-snap clips. No invented event
  precision/recall or general accuracy.

An absent/incomplete EMG interval, sequence gap or source switch makes a trial
unusable. Reports and raw evidence remain available for inspection. Predictions
and planned cues never label actual events automatically.

The compatible export can be ingested by the existing guided-data adapter, but
the historical neural training script also requires its original reviewed
dataset or a separately built fresh dataset. A new checkout cannot reconstruct
historical fits from checkpoints. The new collections do not automatically
retrain, activate a candidate, or wire it into the game client. After collection,
review snap timing, open/grip boundaries and failures, then build a versioned
candidate from the new wearing-session splits. Preserve the baseline and
effort/tension model. Compare an EMG-only baseline with an explicitly separate
motion-aware candidate, testing whether motion context improves held-out
rotation performance rather than using orientation as a hard snap veto.

## Pretrained research checked

[Meta generic neuromotor interface](https://github.com/facebookresearch/generic-neuromotor-interface)
provides official pretrained discrete-gesture models. The official checkpoint
and config have been downloaded to ignored `.local/pretrained/meta-neuromotor/`.
The source model expects **16 channels at 2 kHz**, while Kinesis exposes **eight
channels at 2,048 Hz**. Its nine output labels are index/middle press/release and
thumb actions, with no explicit snap/open/grip vocabulary. These differences
block a meaningful direct live comparison: duplicating eight channels or
renaming a thumb tap as a snap would not establish compatibility.

The downloaded config hash is
`8bbe1a2bf2367a6691829ec4468a3a22452a638c829372af2b4f1baccb740379`;
checkpoint hash is
`17ef2ca0c849a59e0a03bfeb5405d1fa6f11cd5de34751d3d770d7809abb2369`.
PyTorch's restricted loader rejects non-tensor serialized model objects in this
checkpoint; it was not loaded with unrestricted pickle. No accuracy result is
claimed. Adaptation would require a justified sensor mapping and labeled data.

[Meta emg2pose](https://github.com/facebookresearch/emg2pose) is another useful
research direction for hand pose, but is not a verified eight-channel snap
detector. The locally supplied FNN snap checkpoint is already compatible with
this project and remains an experimental comparison candidate, not a proven
replacement. No public model found in this search was verified to directly
solve the exact snap/open/grip task on this Kinesis input.

Camera references:
[MediaPipe hand landmarks](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker),
[official implementation](https://github.com/google-ai-edge/mediapipe), and
[Ultralytics hand-keypoint dataset](https://docs.ultralytics.com/datasets/pose/hand-keypoints/).

## Verification

Run `.venv/bin/python -m pytest -q` and `node tests/live-ui.cjs`.
The real browser integration test uses synthetic media and sensor data:

```sh
npm install --prefix .local/browser-check playwright
node tests/intent-browser.cjs
```

It uses the installed Google Chrome binary on macOS and checks camera model
loading, video uploads, explicit count reporting, binary intent-only reports,
sensor context, reserved evaluation roles and session finalization. Synthetic
checks do not measure gesture accuracy on a wearer.
