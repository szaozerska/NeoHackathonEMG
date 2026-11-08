# Animation Gesture collection

Launch a separate collector without restarting the dynamic/static benches:

```sh
.venv/bin/python scripts/start_animation_collection.py --open-browser
```

Default URL: `http://127.0.0.1:8795/animation`. It follows the existing Kinesis
recording automatically, or accepts the local sensor feed through the page.
An occupied port is left untouched; choose another using `--port` if needed.

For dynamic arm movement and continuous rotation testing:

```sh
.venv/bin/python scripts/start_animation_collection.py --port 8805 --condition dynamic --open-browser
```

The page also offers a static/dynamic selector before starting. Dynamic saves
go under `data/micah/animation/dynamic/<session-id>/`; their metadata
and every truth interval are labeled `test_condition: dynamic`. Static examples
keep their static label. The Animation Gesture class remains `animation_gesture`
in both conditions, and Space down/up still supplies intended/non-intended labels.

Press Space at the first finger interaction, cross the two fingers, then tap
thumb to pinky and maintain the gesture while moving/rotating the arm naturally.
Keep the entire transition green. Undo the gesture before releasing Space. In
red, perform similar arm movements/rotations without forming the gesture. A
30-second maintained hold is a guide, not a minimum or truncation rule. Camera
and live gesture predictions are disabled. Available native sensor context is
retained, but EMG-only raw files do not provide measured wrist orientation.

The planned sequence is saved as protocol metadata. Space marks only the
participant-reported beginning/end; it does not establish the exact crossing or
thumb-tap time. No fixed onset trimming is applied to this collection, and
substep labels are not invented from signal change points.

1. Click **Start session**.
   Animation Gesture is selected automatically. Recording begins in red,
   non-intended mode.
2. Hold **Space** and maintain the new gesture for roughly 30 seconds. Green
   starts immediately. The timer is guidance; it does not end or truncate a hold.
3. Release Space to return immediately to red. Rest between repetitions and
   repeat as needed. Prefer the other hand for Space.
4. Click **Stop & save session**.

Completed sessions are stored in `data/micah/animation/<session-id>/`.
They are separate from the original shield/sword static and dynamic datasets. Static metadata uses
`test_condition: static`, `collection_variant: animation`, and
`gesture_label: Animation Gesture`; selected-motion labels use
`animation_gesture` with no strength category. All key boundaries, raw EMG,
baseline and available sensor context are retained, with no fixed keyboard-edge
clipping. Losing window focus ends an active intended hold and records the
focus-loss interaction.

These are participant-reported training examples. This page does not train or
enable a new classifier output, and does not modify existing model weights.
Keep the same wearing-session ID until the band is removed/repositioned; update
it afterward. The 30-second suggested hold is not an independent repetition
every time a new overlapping window is extracted.

The launcher accepts `--output-root` to choose the capture folder and
`--source-state` to reuse a local Kinesis feed URL file without exposing its
contents. Recordings are not automatically committed while capture is running.
