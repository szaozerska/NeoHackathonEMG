# Micah static Animation Gesture — 2026-11-08

Completed static EMG-only recording: 206.49 seconds, with 98.03 intended seconds and 108.46 non-intended seconds. There are three participant-reported green intervals and four red intervals. This is a different session from the rejected `20261108-021109-c4c1082d`, which remains excluded in full.

## Shared classifications

The original files are under `original/`:

- `truth-values.json`: every reported interval, with `intended: true` for Space held/green, `intended: false` for Space released/red, and `test_condition: static`.
- `intent-toggle-markers.json`: each original press/release boundary and saved clock-alignment metadata.
- `motion-selections.json`: participant class `animation_gesture`, with no strength category. Intended intervals also retain that selected motion.
- `metadata.json`: wearing session, EMG-only capture context, timing policy and completeness.
- `streams.jsonl.gz`: lossless original raw EMG/events; decompress to recover the original JSONL.
- Original capture reports and source manifest: retained for audit and hash verification.

All labels and key boundaries are unchanged. Participant reports are weak labels, not independently verified physiological onsets or internal finger-step times. The contributor reports that some red time may contain the gesture. Do not treat all red periods as clean confirmed negatives without review.

## Separate signal review

[Review candidates](analysis/REVIEW.md) and [plot](analysis/animation-review.png) compare red waveforms with the three green references. These are possible gesture-like signals, not confirmed corrections. No red interval was automatically relabeled, removed, or certified as clean. `analysis/animation-review.json` preserves candidate intervals separately from truth labels and includes unverified onset changes. No model was trained on this recording during this review.

Both static and future dynamic Animation Gesture recordings use the same class `animation_gesture`, but remain distinct conditions and original clips for evaluation. Do not split overlapping windows randomly or interpret one long hold as many independent repetitions.
