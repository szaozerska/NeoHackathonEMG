# Animation Gesture: four choices and Space

Start with `.venv/bin/python scripts/start_animation_collection.py --port 8815 --steps --open-browser`.
Open `http://127.0.0.1:8815/animation-steps`.

The only action choices are:

1. **Cross fingers** (`animation_cross_fingers`).
2. **Last two fingers down** (`animation_curl_ring_pinky`).
3. **Thumb down** (`animation_thumb_approach`).
4. **Each process** (`animation_sequence`): all three motions in order.

Start a session, select an action, and hold Space as you make the motion.
Bring your fingers back out while still holding Space, then release. Repeat
or choose another action. Each process records the whole combined motion and
return under one Space hold. There are no additional phase controls, number-key
requirements, minimum intervals or fixed clipping. Static/dynamic testing and
the wearing-session/evaluation settings remain available.

Captures save under `Micah contributed data/animation/steps/<session-id>/`.
`truth-values.json` records every intended/non-intended Space interval and the
selected action. Raw EMG, surrounding context, and available gyro/orientation
are retained with their native timing. A raw Kinesis recording supplies eight
EMG channels only; the full local sensor feed supplies available gyro XYZ and
orientation quaternion too. Sixteen is the EMG samples per packet, not the
number of recorded channels. The page reports missing sensor context honestly.

New recordings use `animation-component-trials-v2`. They have no internal
component boundaries assigned inside Each process. Historical manually reported
phase files remain readable for older recordings; the current page does not
create or request those annotations. Signal comparisons may investigate internal
changes later, but those are not verified action timestamps.

After saving, `scripts/compare_animation_steps.py --source CAPTURE --output
.local/animation-step-comparison` reports isolated action profiles. For v2,
internal combined-sequence phases remain unsegmented and matching per-step
comparisons are unavailable until independently reviewed. No labels or models
are changed automatically. Preserve reserved evaluation recordings for scoring
only after freezing the model and thresholds.

Every new EMG contribution also saves `gyro-report.json`: availability, sample count, raw XYZ ranges and native-clock rate when available. This is optional context only and never gates collection or becomes a classification input. Zero samples explicitly means unavailable, not no motion. The raw gyro events remain timestamped in `streams.jsonl` when received.
