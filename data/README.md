# data

All EMG recordings, one folder per person. Each capture keeps its raw stream and the contributor's original labels.

| Folder | Who | What |
|---|---|---|
| [`ken/`](ken/README.md) | Ken | guided snaps, open, fist, rest |
| [`micah/`](micah/README.md) | Micah | dynamic + static Shield/Sword/Snap intervals, Animation Gesture holds |
| [`sophie/`](sophie/README.md) | Sophie | one dynamic interval session (snap, shield, sword, Animation Gesture) |

Contributor-rejected captures are listed in `configs/rejected-captures.json` and are refused by every loader.

The pooled train/validation/test split is built by `python scripts/build_pooled_dataset.py` (see
[`docs/pooled-split.md`](../docs/pooled-split.md)).
