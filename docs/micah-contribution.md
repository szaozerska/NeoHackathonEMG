# Micah data contribution: immediate intent labels and synchronized band capture

Start the partner bench and open http://127.0.0.1:8765. This page captures EMG, available band motion/context,
and participant-provided intent/motion labels. It does not request camera or
microphone access, run inference during a contribution, or use camera/model
predictions as labels. The advanced camera lab remains separately at `/collect`.

1. Choose a wearing-session ID; retain it until removing/repositioning the band.
2. Click **Start session** with the mouse. Recording starts as **non-intended**.
3. Select **Snap**, **Shield low/medium/high**, or **Sword low/medium/high**.
   Shield and Sword are the participant's selected tensile hold, not a spell
   recognized by a classifier. Effort is relative and not measured force.
4. With the non-band hand, **press and hold Space**. This starts the reported
   intended interval **immediately**. Keyboard repeat does not create more boundaries.
5. Perform the selected motion while holding Space. No waiting period is required.
6. **Release Space**. This immediately ends the reported intended interval and
   returns to non-intended. Repeat, selecting another motion when needed.
7. Click **Stop & save session**.

There is **no activation delay, fixed trimming, or minimum interval length** in
this mode. The green/red display changes on the keyboard event; the saved
boundary uses the browser event time mapped into the Python host clock, not
HTTP receipt time. Keep the non-intended periods before/after each action as
baseline. Every reported interval remains intact, including short ones.

Cleanup is deferred: use the preceding and following non-intended baseline to
propose actual motion onset/offset after recording. Keep original reports
immutable and save reviewed/refined labels as a separate version. Muscle
activation or deviation from baseline is evidence to review, not proof of
mental intent. Use the other hand for Space where practical, and retain
keyboard/mouse events so their effects can be considered later.

## Synchronization and full sensor context

Enable **Kinesis → stream → local sensor feed**, paste its current URL into the
page, and select your wrist in Kinesis. Start waits for fresh EMG, gyro,
orientation and a known wrist for angle calculations. Raw recording files
contain EMG only, so they cannot meet this full-context requirement.

The page shows measured gyro/orientation Hz, forearm elevation, relative
forearm compass, estimated excess arrival delay, Kinesis→Python delivery lag,
and browser/host clock uncertainty. Original native band microseconds, Kinesis
receipt uptime and Python receipt uptime remain separate. Native event/session
and band connection identifiers are retained. Clock epochs reset on source or
connection changes and band-clock rollback.

The clock bridge uses five localhost round trips and the lowest-RTT midpoint
estimate at session start, with recalibration every 30 seconds. Every keyboard
marker retains its browser event time, mapped host time, server receipt time,
clock offset and uncertainty. Recalibration events are saved in the stream.
No wall-clock date is used to align EMG with key presses.

Arrival delay follows Kinesis's own `ArrivalDelay` algorithm: excess over the
lowest observed band/host offset, with a small drift allowance. It is **not an
absolute Bluetooth transit-time measurement**. Forearm angles follow Kinesis's
`ForearmAim` wxyz/+z-up convention with the left/right wrist sign correction.
Compass is relative, not geographic north, and is undefined for a vertical arm.
These are forearm angles, not exact finger or palm orientation.

EMG's original batch timestamp, sequence and 16×8 samples are retained without
shifting them. Within-batch timestamp semantics have not been hardware
calibrated here; 16 samples at 2,048 Hz span about 7.3 ms from first to last.
Software sync and measured uncertainty do not establish exact physiological
onset or zero hardware latency. Postprocessing must account for clock estimates,
sample/batch timing and missing data rather than labeling by receipt time alone.

## Local files

Each session gets its own directory under the repository's
**`Micah data contribution/`** folder. This whole directory is Git-ignored.

- `streams.jsonl`: original eight-channel EMG, source timestamps/sequences,
  motion selections, key boundaries and interaction records, plus available
  band gyro/orientation/configuration/status/gesture events with timing metadata.
  Classifier predictions and camera observations are not saved here.
- `truth-values.json`: participant-provided `intended: true/false` intervals
  without capture-time clipping, with selected motion/effort and preceding/
  following non-intended baseline references attached to intended intervals. These are reports, not independently verified physical
  event onsets or proof that the selected motion succeeded.
- `intent-toggle-markers.json`: original key-boundary reports. The filename is
  retained for compatibility; in this page labels follow **key down/up**, not a
  persistent toggle.
- `motion-selections.json`: intended motion/effort selected before each action.
- `interaction-exclusions.json`: legacy filename for keyboard/mouse/focus
  event records; entries are marked unapplied in this mode. Nothing is trimmed.
- `signal-coverage.json`: actual continuous EMG segments. Reported labels are
  preserved across missing data; do not invent or interpolate absent samples.
- `intent-gate-intervals.json`: binary training intervals, with action metadata
  separate from the binary label. Collapse across selected motions for the
  initial intended/non-intended model; do not use motion names as sensor input.
  `postprocessing_required` remains true until a separate reviewed export exists.
- `metadata.json`, `collection-report.json`, `guided-manifest.json`: collection
  settings, reported seconds per class, wearing-session/role and source hashes.

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
ignored, motion/effort and sensor timing are saved, and no camera or classifier
output enters the recording. Browser tests require the local Playwright install
documented in `docs/intent-lab.md` and Google Chrome on macOS.
