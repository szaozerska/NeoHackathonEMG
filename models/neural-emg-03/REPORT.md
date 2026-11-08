# Neural EMG experiment

Known development regression checks; not independent-session accuracy.

| Task | Selected architecture | Check | v4 fallback |
|---|---|---|---|
| state | fnn (seed 7) | window 90.8%, segment 92.0% | window 91.1%, segment 96.0% |
| snap | fnn (seed 7) | TP 11, FP 1, FN 1 | TP 5, FP 0, FN 7 |

Both classical models were copied and hash-checked. Neural models are experimental and were not activated.

Historical check clips were examined in earlier development; these are regression checks, not fresh independent benchmarks.
Train/validation/check share wearing sessions. No 99% accuracy claim or unseen-person generalization.
Repeated overlapping windows are not independent trials. Segment averages do not measure live response accuracy.
Approximate reviewed snap times use 250ms event matching, not measured hardware latency.
Softmax confidence is uncalibrated; unknown rejection is not a guarantee of out-of-distribution detection.
Gain augmentation does not simulate real wrist rotation, electrode repositioning or all soft/firm snap variation.
Effort remains in the preserved classical model and is not retrained by this experiment.
