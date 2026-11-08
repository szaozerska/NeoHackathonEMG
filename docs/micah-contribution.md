# Micah data contribution: independent EMG capture

Start the partner bench and open http://127.0.0.1:8765. This page captures EMG
and participant-provided intent/motion labels. It does not request camera or
microphone access, run inference during a contribution, or use camera/model
predictions as labels. The advanced camera lab remains separately at `/collect`.

1. Choose a wearing-session ID; retain it until removing/repositioning the band.
2. Click **Start session** with the mouse. Recording starts as **non-intended**.
3. Select **Snap**, **Shield low/medium/high**, or **Sword low/medium/high**.
   Shield and Sword are the participant's selected tensile hold, not a spell
   recognized by a classifier. Effort is relative and not measured force.
4. With the non-band hand, **press and hold Space**. This starts the reported
   intended interval. Keyboard repeat does not create more boundaries.
5. Wait for the displayed keyboard guard to end, perform the selected action,
   and leave a short pause afterward while continuing to hold Space.
6. **Release Space**. This immediately ends the reported intended interval and
   returns to non-intended. Repeat, selecting another motion when needed.
7. Click **Stop & save session**.

The guard defaults to **0.5 seconds before and after each key boundary or UI
interaction**, plus estimated clock uncertainty. It can be increased to three
seconds. Samples around the Start/Stop clicks and motion selection are excluded
too. Sensor gaps and time outside the focused window are removed from the
usable intervals. The original raw EMG and untrimmed reports remain available.
Very short actions close to the key edges can be completely excluded; the
export never invents a usable interval to compensate. For snap capture, hold
Space long enough to perform the snap between the guards. Use the non-band
hand for Space so a prolonged keyboard hold does not contaminate band EMG.

## Local files

Each session gets its own directory under the repository's
**`Micah data contribution/`** folder. This whole directory is Git-ignored.

- `streams.jsonl`: original eight-channel EMG, source timestamps/sequences,
  motion selections, key boundaries and interaction records. Classifier
  predictions, camera observations and other band streams are not saved here.
- `truth-values.json`: participant-provided `intended: true/false` intervals
  after guards and continuity checks, with selected motion/effort attached to
  intended intervals. These are reports, not independently verified physical
  event onsets or proof that the selected motion succeeded.
- `intent-toggle-markers.json`: original key-boundary reports. The filename is
  retained for compatibility; in this page labels follow **key down/up**, not a
  persistent toggle.
- `motion-selections.json`: intended motion/effort selected before each action.
- `interaction-exclusions.json`: trimming windows around keyboard/mouse events
  and focus loss.
- `intent-gate-intervals.json`: binary training intervals, with action metadata
  separate from the binary label. Collapse across selected motions for the
  initial intended/non-intended model; do not use motion names as sensor input.
- `metadata.json`, `collection-report.json`, `guided-manifest.json`: collection
  settings, usable seconds per class, wearing-session/role and source hashes.

Unselected ordinary activity, including relaxed rest, remains non-intended by
participant report. Keep complete wearing sessions separate for training,
validation and reserved evaluation. Recording never fits or activates a model.

## Verify

```sh
.venv/bin/python -m pytest -q
node tests/contribution-browser.cjs
```

The browser test uses synthetic EMG, without camera permissions, and verifies
that key down/up produce the intended/non-intended boundaries, key repeat is
ignored, the selected motion/effort is saved, and no camera or classifier output
enters the recording. Browser tests require the local Playwright install
documented in `docs/intent-lab.md` and Google Chrome on macOS.
