# Shield effort model: open-hand protocol v3

The prior fist-shield dataset and model were deleted. No accuracy result from them applies to the new gesture.

Collect the 48-trial flow in [the current training plan](../training-plan.md). The effort trainer uses only the 27 open-hand shield trials: three subjective effort levels × three positions × three rounds. Sword, snap and comparison clips are not effort targets.

Close the recording, then run:

```sh
.venv/bin/python -m spelltrain train-effort \
  --session data/player-a/band-01 \
  --output artifacts/player-a/shield-effort-v3
```

The trainer requires confirmed `spells-open-shield-effort-v3` reports in `gesture-trials-v3.json` and the matching raw `streams.jsonl`. It rejects old protocols and existing output directories. It fits log-transformed RMS/amplitude features and a regularized classifier. Sensor timestamps preserve sample spacing; sequence gaps reset filtering. Per-trial median receive offset approximately aligns recording buttons, and 0.75 seconds is trimmed from each edge.

Round 1 fits candidates, round 2 selects features, and round 3 evaluates once. The saved artifact stays fitted on training data only. Output contains `effort-model.joblib`, `training-report.json`, `REPORT.md`, and `test-predictions.csv`. Read trial confusion and uncertainty before trusting the model. Three rounds from one wearing session are not independent sessions.

`EffortPredictor` returns light/medium/firm probabilities and an ordinal 0–1 effort index. This is not a calibrated percentage of maximum activation, measured pushing force, or an established proportional shield-strength function. The model always returns an effort level, including on non-shield movements. Gate its output on valid open-hand shield pose, then calibrate the protection mapping. The combined v3 gesture bundle now includes this frozen model and feeds effort into the recorder’s shield gate. Actual protection mapping and headset gameplay still require validation. See [all gesture models](gesture-models-v3.md).
