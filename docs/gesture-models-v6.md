# v6: immediate Fireball equipment and independent camera review

The active band bundle is `artifacts/player-a/gestures-v6/model.joblib`. The EMG hand-state and snap weights were updated using the latest completed capture `20261107-212304-5dbb9730`, previous feedback captures, and prior reference-reviewed examples. The effort model is unchanged because feedback does not label effort levels. No camera/audio features enter band inference.

## Equipment rules

A detected snap immediately equips Fireball. It does not require subsequent open-hand confirmation. Keeping or opening the hand preserves Fireball equipment and takes priority over the shield candidate. A subsequent confirmed fist cancels Fireball and equips Sword, immediately or after a long open hold. Quest must later confirm a forward open-hand throw before deployment. The band-only tester never commits a throw. Stream loss resets availability; duplicate snap IDs cannot re-equip a canceled fireball.

This replaces v5's snap-candidate/open-confirmation step. Raw detector errors remain errors: changing equipment semantics does not establish better snap classification.

## Model checks

The new 82.1-second capture contains 10,784 EMG rows including pre-roll, 8,564 prediction rows, 1,691 decision rows, ten intent marks, and no sequence discontinuities. Six marks request snaps; v5 emitted three snap events. There is no video in that capture, so these reported actions cannot be retrospectively certified with a camera.

The new session uses predetermined fitting/validation/check clips: four reported snap clips for fitting, one for validation, one for checking; its first sword/shield clips fit, final sword/shield clips check. Previous model weights and feedback mean these are development checks, not a new independent-session benchmark.

| Evaluation | v6 result | Limitation |
|---|---|---|
| Combined feedback check, steady hand-state clips | 8/9 (88.9%) | Weak participant intent labels, same wearing sessions |
| Combined feedback check, snap-containing clips | 7/11 (63.6%) | Two sword false positives and two missed reported snap clips; not exact event accuracy |
| Newest capture alone, snap-containing check clips | 2/3 | Sword and shield negative clips correct; reported snap clip missed |
| Known reference-reviewed snap regression | 5/5, zero false events, ±250 ms tolerance | Previously examined reference data, not fresh validation or measured latency |
| Effort | Unchanged | New effort accuracy not measured |

Parameters were saved before feedback checks. See `training-report.json` for sources, file hashes, split manifest, candidate selection and individual outcomes. Do not interpret these figures as a solved detector. In particular, shield release is a separate transition problem requiring review evidence.

## Independent camera observer

The localhost has an **Enable camera validation** button. Browser permission is required for webcam and microphone. Keep the right hand visible. The observer uses locally cached MediaPipe hand landmarks in a worker and a separate, rotation-invariant finger-angle check for open/fist. It takes no EMG inputs and cannot modify band predictions. It reports unknown when evidence is ambiguous. This geometric estimate is fallible and uncalibrated; handedness, occlusion and camera perspective can cause errors. It cannot measure muscle effort or certify the full Quest shield pose.

MediaPipe's [official Hand Landmarker documentation](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker?tab=Web) describes its camera landmarks and video interface. Assets are pinned to tasks-vision 0.10.21 and hand_landmarker float16 model revision 1; their hashes and sources are cached in `data/support/vision/manifest.json`. The camera is a training/reference observer, not an image model being transferred to Quest.

**Record** starts synchronized local EMG and camera/audio capture. Camera preview is not saved until Record. Media chunks are uploaded to localhost as recording proceeds, with index/hash checks and retries. Stop saves the media before closing EMG recording. If saving fails, retry Stop; an explicit recovery button can save EMG with the camera marked incomplete. Reloading/closing the tab during recording can leave incomplete media. No workflow can promise data that the devices did not deliver; gaps and unknown observations are retained rather than fabricated.

Recorded evidence includes:

- Raw decoded EMG packets, sensor timestamps and sequence numbers.
- Every state probability, effort output, snap-window score, threshold/rearm status, and emitted snap.
- Decision-memory history, smoothed probabilities, pending changes, displayed equipment and cancellation events.
- Actual browser display changes with browser/server clock alignment.
- Camera landmarks/handedness at roughly 10 Hz, independent open/fist estimates and disagreements, including unknown observations. The video/audio reference is recorded continuously at negotiated device rates.
- Clock alignment and round-trip uncertainty, media start callback, chunk completeness, source gaps and participant marks.

The browser/server mapping is approximate; camera exposure and audio/EMG hardware latency are not calibrated. Full video/audio permit detailed timing review. A sound transient or finger release is not automatically a verified snap.

Use **Shield → Nothing**, **Sword → Nothing**, and **Fireball → Sword** cues to deliberately record transitions. Hold the initial gesture before selecting the cue, then change on Go. Marks establish intended actions, not verified onsets. The complete reference and logs stay in the capture directory; `external-review.json` is a disagreement queue, not an accuracy report. A link to the saved camera/audio recording appears after Stop.

For post-processing:

```sh
.venv/bin/python scripts/review_live_camera.py data/player-a/live-corrections/CAPTURE_ID
```

This exports video overview sheets, audio and transient hints while retaining original hashes. Review original full-rate media for exact actions, create reviewed intervals/event labels, then fit a candidate and evaluate on untouched recordings. Camera estimates and the model's own predictions never automatically become ground truth. Models stay frozen during recording.

## Validation performed

Python checks cover equipment persistence/cancellation, forward-only Quest commitment gates, independent camera geometry, timestamp/capture ownership, chunk retry/finalization, and disagreement reporting. Browser integration uses Chrome's synthetic camera/audio, executes the real landmark worker, records media, checks video/audio streams with ffprobe, and verifies browser/camera logs. This verifies plumbing, not real gesture accuracy on the user's camera or Quest.


Fireball-to-Shield update: a confirmed full Quest shield pose cancels equipped Fireball and activates Shield. Merely detecting an open hand does not cancel it. The current EMG bundle has one open-hand class, so the band-only tester offers an explicit Switch to Shield command while open; this is logged as participant input, not a model prediction or verified training label. Classifier weights are unchanged by this equipment-rule update.
