# data/sophie

[Sophie's dynamic session — 20261108-040247-0a14a2cd](dynamic-20261108-040247-0a14a2cd/README.md): 346.7 intended
and 477.7 non-intended seconds, with her unchanged Spacebar labels. Non-intended time was aggressive arm movement,
not rest.

**Role (changed 2026-11-08 at Sophie's request):** part of the pooled Ken/Micah/Sophie train/validation/test split
(`scripts/build_pooled_dataset.py`), no longer a reserved untouched check. Only intervals marked `train_eligible` in
[`analysis/training-selection.json`](dynamic-20261108-040247-0a14a2cd/analysis/training-selection.json) are used
(signal-quality rules only: `python -m spelltrain.training_selection <capture>`).
