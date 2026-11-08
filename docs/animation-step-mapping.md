# Animation Gesture: isolated actions and sequence mapping

Launch a separate collector:

```sh
.venv/bin/python scripts/start_animation_collection.py --port 8815 --steps --open-browser
```

Open `http://127.0.0.1:8815/animation-steps`. Use static testing first to learn
the finger components; the same page also supports dynamic arm movement and
rotation. No camera or classifier supplies training labels.

## Isolated component trials

Click Start, then select one action. Repeat each about five times. Use your
other hand for keyboard reports, and maintain a similar comfortable effort.
There is no mandatory duration or fixed edge trimming.

| Action button | Prepare before Space | Perform while Space is held |
|---|---|---|
| Cross fingers | Relax the fingers | Cross just the two fingers; pause; undo |
| Curl ring + pinky | Have the two fingers already crossed | Curl ring and pinky downward; pause; undo that curl |
| Thumb toward ring + pinky | Have the crossing and ring/pinky curl already prepared | Move only the thumb toward those fingers; pause; undo that thumb movement |

Space down reports the selected movement start; Space up returns to red.
Optionally press **4** when the selected component becomes a stable held pose.
This separates its movement phase from its reported hold. Without that report,
movement and holding may be mixed; no completion time is guessed.

Preparation in red is task context. It may already contain a partial pose and
must not automatically be treated as relaxed-hand or globally clean negative
data. Undo transitions remain in the recorded context and require review.

## Combined sequence

Select Full sequence while red. Keep Space held throughout:

1. Press Space as crossing starts: `cross_fingers` begins.
2. Press **2** as the ring/pinky curl begins: `curl_ring_pinky`.
3. Press **3** as the thumb starts approaching those fingers: `thumb_approach`.
4. Press **4** when the completed pose is held: `combined_hold`.
5. Undo and release Space when finished.

The phase buttons are alternatives to number keys. For early trials, brief
pauses between steps make comparison easier; then repeat at a natural pace.
Keyboard times are aligned with the sensor's host clock using the same clock
probes as the other collectors. They remain participant-reported boundaries,
not verified finger onset/completion. Missing phase reports are flagged, not
invented; earlier or duplicate phase reports are rejected without rewriting
previous labels.

## Saved outputs and comparison

Captures live in `Micah contributed data/animation/steps/<session-id>/`.
`metadata.json` records the static/dynamic condition and the collection protocol.

- `truth-values.json`: unchanged intended/non-intended Spacebar intervals,
  with selected isolated action or full-sequence class.
- `animation-phase-markers.json`: original reported phase times, browser clock
  alignment/uncertainty, trial association and missing-step warnings.
- `animation-phase-intervals.json`: phase intervals derived from those reports,
  marked as weak participant supervision with no verified physical timestamps.
- `streams.jsonl`: complete EMG and available timestamped sensor context, with
  raw phase reports preserved alongside sensor events.
- `guided-manifest.json`: hashes include the phase-marker/interval files.

After saving a completed recording:

```sh
.venv/bin/python scripts/compare_animation_steps.py \
  --source "Micah contributed data/animation/steps/SESSION_ID" \
  --output .local/animation-step-comparison
```

The tool rebuilds native-clock RMS envelopes and compares each isolated step
with the corresponding reported combined-sequence phase. It reports relative
channel-pattern similarity, amplitude, timing integrity, missing phase labels
and overlaid trajectories. Gapped or too-short intervals remain in raw data but
are flagged as unavailable for comparison. Similarity is not detection accuracy.
No labels or existing models are automatically changed. Keep repetitions/clips
together for future validation and reserve a new wearing session for evaluation.
