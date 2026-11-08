# Animation Gesture captures

## BAD DATA — DO NOT USE BY ANYONE

**Session `20261108-021109-c4c1082d` was explicitly rejected by Micah.**

It recorded 0.0 intended seconds and approximately 158.3 non-intended seconds.
Exclude the entire session from training, validation, evaluation, pattern
analysis and non-intended/negative baselines. Do not salvage any portion or
interpret its non-intended labels as usable controls. The raw recording remains
local solely for audit and is not published here.

The shared rejection registry is [`configs/rejected-captures.json`](../../configs/rejected-captures.json).
The local capture also contains `DO_NOT_USE.md`, `DO_NOT_USE.json`, and rejected
metadata. Original metadata/report backups and raw labels are preserved locally.

Future Animation Gesture sessions are separate recordings; this rejection
applies to the exact session above.

## Published valid static recording

[`20261108-021414-fe4063d4`](static/20261108-021414-fe4063d4/README.md)
contains the original EMG stream and unchanged Spacebar classifications:
98.03 intended seconds and 108.46 non-intended seconds. The contributor reports
possible gesture contamination in red; signal-review candidates are separate
from original labels and are not confirmed corrections or certified negatives.

## Disregarded isolated-component attempt

**Session `20261108-024600-0df8f41b` is DO NOT USE.** Micah used the wrong portal for isolated Animation Gesture component trials and explicitly rejected the entire recording (33.4 intended seconds, 62.0 non-intended seconds). Do not use any portion for training, validation, evaluation, analysis or negative baselines. Approximate thirds are not approved component labels. Only the [disregard notice](dynamic/20261108-024600-0df8f41b/DO_NOT_USE.md) is published; raw data stays local for audit.
