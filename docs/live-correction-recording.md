# Live correction recording

The live tester now has a single **Record / Stop & save** control. It does not require camera or microphone access and no camera-image model is used. The classifiers still consume only EMG.

1. Start the Kinesis raw stream as shown on the tester.
2. Click Record. Try relaxed hand, shield entry/hold/release, isolated snaps and fist hold/release.
3. Under **Label the action**, leave **I’m about to do it** selected. Click the gesture, wait for **Go**, then perform it once or hold the pose during the four-second action window. If reporting an action after doing it, select **I already did it (last 8 seconds)**. Labels report intent and require review; they are not exact physical snap timestamps or labels for every sample. Older captures used two-second retrospective windows and keep that original metadata.
4. Click Stop & save. Tell the assistant the recording is ready; no file upload is needed in this shared workspace.

Captures are under `data/player-a/live-corrections/<timestamp>-<id>/`:

- `streams.jsonl`: original EMG packets (sensor time/sequence and host receipt time), raw model outputs with scores, displayed decision snapshots, and correction reports on one host timeline.
- `corrections.json`: separately saved participant reports and the prediction shown when marked.
- `metadata.json`: frozen-model lineage, runtime decision settings, timing, counts, discontinuities and stop reason.

Two seconds of pre-roll provide context for a mistake that happened just before Record. Each capture has its own directory; earlier recordings, labels and models are never overwritten. Refreshing the browser does not stop an active server-side recording; the page reconnects to its status. The assistant can inspect `/api/observe` or the local files while capture is active. This does not create an autonomous background chat agent or keep the assistant analyzing after its turn ends.

The displayed model remains frozen during capture. Predictions are not ground truth. Reports must be reviewed, ambiguous boundaries trimmed and false positives/negatives paired with verified or participant-reported intended actions. A future model update must use development captures for adjustment and independent untouched data for evaluation, then save a new model version. Fine-tuning on all mistakes and reporting accuracy on those same examples is not a valid success rate.

The earlier sustained-open snap veto has been removed from the runtime. A supervised snap event again takes immediate priority over the open-hand classifier. This restores snap feedback but does not claim to solve the model's shield-entry false positives. The new captures are intended to document that conflict instead of layering more guessed pose rules.
