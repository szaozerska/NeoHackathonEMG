# Neural EMG 04: FNN hand state + CNN snap

EMG-only. 400 ms hand-state windows (`state_window` 820) and 160 ms snap windows (`snap_window` 328), causal
20-450 Hz bandpass + 60 Hz notch, filters reset at stream gaps. Trained on Modal (`scripts/modal_train_neural.py
--windows 820:328 --architectures fnn,cnn`) on Ken's guided captures and Micah's static, dynamic and Animation Gesture
(Infinite Void) holds. Reserved validation recordings and everything marked DO NOT USE were excluded.

Internal development hold-out (newest Ken captures + the last 30% of each of Micah's classes); **not** Micah's
reserved validation set, and only two wearers:

| Task | Model | Hold-out result |
|---|---|---|
| hand state | FNN seed 7 | window accuracy 89.1%, macro-F1 0.875, hold (segment) accuracy 99% |
| snap | CNN seed 7 | 44 of 46 snaps, 0 false snaps in ~7 min of snap-free data (threshold 0.9995) |

Per-class hand-state recall / precision: none 0.88 / 0.97, open 0.85 / 0.89, fist 0.89 / 0.92,
infinite_void 0.98 / 0.69 (relaxed and open windows are sometimes read as void).

Superseded as the hand-client default by neural-emg-05; still selectable with `--neural-model models/neural-emg-04`.
No unseen-wearer generalization is claimed; overlapping windows are not independent trials.
