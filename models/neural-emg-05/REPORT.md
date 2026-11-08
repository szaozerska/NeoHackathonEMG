# neural-emg-05 (pooled Ken/Micah/Sophie split)

Trained with `scripts/build_pooled_dataset.py` (seed 7, 70/15/15, 3 s blocks, 820/328-sample windows) and
`scripts/train_neural_emg.py --dataset` (FNN and CNN, seed 7; selected on validation). Default model of the hand
client (`--neural-model` picks another bundle, `--log-only` sends no signs).

- state: FNN, threshold 0.55. Test: 86.4% of windows, 95.7% of clips.
- snap: CNN, threshold 0.995. Test: 26 TP, 3 FP, 5 FN.

Held-out test clips, per person (majority of each clip):

| | fist | open | crossed fingers | none / movement | snaps (TP/FN, FP) |
|---|---|---|---|---|---|
| Sophie | 10/10 | 14/14 | 3/3 | 9/9 | 5/1, 0 FP |
| Ken | 4/4 | 4/4 | — | 14/15 | 2/1, 0 FP |
| Micah | 22/25 | 24/24 | 4/4 | 45/49 | 19/3, 3 FP |

Limitations: all parts share each person's single band session, so these are held-out clips, not a new band
placement or a new person. Sophie's capture is no longer an untouched check. Ken has no Animation Gesture data in
the agreed form. Labels are weak Spacebar intervals; overlapping windows are not independent trials.
