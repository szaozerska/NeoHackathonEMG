# Combined static/dynamic reserved validation collection

```sh
.venv/bin/python scripts/start_animation_collection.py --port 8835 --validation --open-browser
```

Open `http://127.0.0.1:8835/validation`. This is one page and one session for
both Static and Dynamic. Switch with the two condition buttons between actions
while Space is released/red. Mode changes are blocked during intended holds.

Start the session, then select Snap, Shield, Sword or Animation Gesture.
Shield/Sword show Low, Medium and High requested strength; Snap and Animation
Gesture have no strength category. Press Space at the action start, perform
the motion and return, then release. Space down/up immediately marks
intended/non-intended; full raw transitions and key times are kept. Static means
a comfortably still arm; dynamic means natural arm movements and rotations.
Include comparable non-intended movement, finger activity and partial gestures
as controls. These remain participant reports, not independently verified
physical action times or measured force.

The page is locked to reserved evaluation. Files save under
`Micah contributed data/validation/<session-id>/`, with:

- `metadata.json`: `dataset_role: untouched_guided_count_check`, `do_not_train:
  true`, `do_not_tune_thresholds: true`, `test_condition: mixed`, and
  `evaluation_status: reserved_unscored`.
- `truth-values.json`: every intended/non-intended interval has its own actual
  Static/Dynamic condition, plus the selected gesture and effort on intended
  intervals. The session's mixed condition never replaces those interval labels.
- `condition-markers.json`: initial condition and timestamped mode switches,
  retaining browser clock alignment. A switch splits red context correctly.
- `intent-toggle-markers.json` / `motion-selections.json`: original key
  reports and gesture/effort selections.
- `streams.jsonl`: complete raw EMG and available timestamped sensor context.
- `gyro-report.json`: optional gyro availability/count/ranges/rate. Missing
  gyro does not prevent collection and is not treated as zero movement.
- `collection-report.json`: intended and non-intended seconds for each condition.
- `guided-manifest.json`: checksums include condition markers and gyro report.

Model inference/camera labels are disabled in capture. No score or accuracy is
claimed by collecting the recording. Freeze a model and its thresholds before
scoring these data; keep the validation recordings out of fitting, threshold
tuning and model selection. The fitting adapters reject reserved captures.

Use the actual wearing-session ID. Removing/repositioning the band requires a
new ID; simply changing an ID does not create an independent wearing session.
Keep whole original trials/sessions together in evaluations. Reusing evaluation
results to improve a model makes those examples development data; collect a new
untouched evaluation afterward.

Completed sessions can be published with their original labels and a lossless
gzip of the raw stream, using the existing publication/hash-verification process.
Do not commit active partial captures or private local feed URLs. Rejected session
IDs remain excluded through the shared rejection registry.
