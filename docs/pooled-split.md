# Pooled Ken/Micah/Sophie split

`scripts/build_pooled_dataset.py` builds one dataset in which every person's data is shuffled into
train / validation / test (default 70/15/15, seed 7), for `scripts/train_neural_emg.py --dataset`.

- **Split unit:** a whole labelled clip or Space interval. Holds longer than 6 s (Ken's 30 s guided clips, Micah's
  static holds) are cut into 3 s blocks and the blocks are dealt instead. Overlapping windows never cross parts;
  windows straddling a boundary are dropped.
- **Stratified:** units are dealt per (wearer, class), so every person and gesture appears in every part.
- **Balanced training weights:** each class weighs the same; within a class each wearer weighs the same; within
  a wearer each clip weighs the same (`row_weights`).
- **Sources:** `data/ken/guided/*`, `data/micah/{static,dynamic,animation/static}/*`, `data/sophie/*`. Captures in
  `configs/rejected-captures.json` or with `DO_NOT_USE` are refused. Ken's `superseded-infinite-void-v1/` is not
  read. Sophie's capture contributes only intervals marked `train_eligible` in `analysis/training-selection.json`.
- **Snaps:** training-part snap intervals are weak one-snap bags; validation/test snaps are scored against the
  EMG envelope peak (`analysis/reference-quality.json`).

**Limitation:** all parts share each person's single band session, so test results measure held-out clips, not a
new band placement or a new person.
