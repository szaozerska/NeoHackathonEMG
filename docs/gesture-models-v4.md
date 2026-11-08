# Reference-reviewed gesture model update

The completed 40-trial `band-02` session was verified against its exported manifest and 40 reference-media hashes. The original data and prior models are retained. The recorder was safely closed before feature extraction.

Current models are under `artifacts/player-a/gestures-v4/`. Read `REPORT.md` for results and limits, `training-report.json` for exact splits, validation settings and predictions, and `reviewed-labels.json` for reference timing provenance. All three components are retrained; the effort component is no longer merely copied from v3.

Reference review used overview frames for all clips, audio transients cross-checked against visible middle-thumb release for ten isolated snaps, and 10 fps inspection of four fist transition clips. Ambiguous transition boundaries were excluded from stable-state classification. These are assistant-reviewed reference labels, not participant button times and not laboratory-calibrated acquisition timestamps. Video does not independently measure muscle effort.

## Evaluation design

- Training: older `band-01` rounds 1 and 3 plus supplemental round 1, with whole-clip exceptions for validation below.
- Validation: `band-01` round 2; supplemental round-1 snap-4, snap-5, pinch, fingers and open-close clips validate the snap model; supplemental round-1 open-close validates hand state.
- Test: all supplemental round-2 clips, completely excluded from fitting, scaling, model selection and threshold selection.

Clip and segment identities are recorded separately; all segments/windows from one original clip remain in one split per task. The old round-3 test was already inspected earlier and is now explicitly development data. The new test is held out by round, not by independently donned session.

The fit uses causal sensor-time windows mapped to the Mac session with per-trial median Kinesis source-uptime offsets. Host delivery jitter is not interpreted as sample loss; true sequence discontinuities reset filtering. Edge margins are 0.75 seconds. Offset residuals and quality checks are in the report. Hardware latency is uncalibrated, so approximate event timing must not be advertised as measured physical response latency.

## Updated results

- Sword: 14/15 reviewed stable segments correct (93.3%); 5/6 fist segments recognized and 9/9 non-fist segments rejected. Whole steady clips alone: 8/9 correct, including only 2/3 fists. The missed trial was the fist near the side.
- Shield hand shape: 15/15 binary open-hand decisions correct; this is four positive open-hand segments, not fifteen independent shield gestures. Quest still needs to validate shield pose.
- Shield effort: 2/3 correct (66.7%); medium was mistaken for light. This small new test is not directly comparable to the older 7/9 headline. Both old and new models score 2/3 on these same three clips.
- Fireball: 5/5 reference-reviewed snaps found with no false events at ±250 ms event matching. Zero false events in 79.1 seconds of trimmed non-snap test clips. Only five positive events were tested. At ±100 ms, only 2/5 matches are found, illustrating alignment uncertainty and why this is not a latency claim.
- Sword transitions: all four intended changes matched within ±750 ms, but there were four extra toggles. Transition precision is 50%; the hold/release behavior still needs work.

The source model parameters are saved in `frozen-before-test.joblib` before test scoring. Hashes, source identity and component comparisons confirm the deployed bundle contains those exact coefficients, scalers and threshold, with no post-test tuning.

## Reproduce the fit

Only load trusted local joblib files. Use a new output directory:

```sh
.venv/bin/python -m spelltrain retrain-reviewed \
  --features artifacts/player-a/reference-review-v4/features.joblib \
  --reviewed-labels artifacts/player-a/reference-review-v4/reviewed-labels.json \
  --previous-model artifacts/player-a/gestures-v3/model.joblib \
  --output artifacts/player-a/gestures-v4-reproduction
```

The cached features retain raw-data hashes and the independent reviewed labels retain reference-media hashes. The trainer verifies raw streams, labels, metadata and reference media against those hashes. Reproduction is not a fresh independent test.

For causal inference, `GesturePredictor` accepts `artifacts/player-a/gestures-v4/model.joblib`. Its snap component is now reference-supervised and emits snap events by default; the older weakly supervised v3 component remains candidate-only unless explicitly enabled. `--model artifacts/player-a/gestures-v4/model.joblib` loads the updated bundle in a new recorder session. No recording session or live preview was started during this update.

## Remaining work

Prioritize fist/relaxation separation near the side, state stability during release, and light/medium effort calibration. Any debounce/hysteresis change needs development-only selection followed by a fresh untouched test. Longer natural-activity recordings and another separately donned session are required before general reliability claims. Quest pose, throwing, rendered effects and collisions remain separate from these EMG rates.
