# Sophie’s validation data — 2026-11-08

**Contributor: Sophie. Purpose: reserved validation/evaluation. Do not use for model training, model selection, or threshold tuning.**

- Session: `20261108-040247-0a14a2cd`
- Duration: 824.38 seconds (13 minutes 44 seconds).
- Intended: 346.66 seconds across 301 reported intervals.
- Non-intended: 477.72 seconds across 302 reported intervals.
- Gesture reports: 60 Snap, 98 Shield, 123 Sword, 20 Animation Gesture intervals. Shield/Sword retain low, medium and high requested effort.
- All 603 saved intervals are labeled **dynamic**. The combined collector's session-level setting is `mixed`, but no static interval was recorded. No conditions were relabeled.
- Raw EMG: 105,578 batches, eight channels, 16 samples/batch at nominal 2048 Hz/channel. Gyro and orientation events are included as optional recorded context; classification inputs remain EMG-only.
- Status: reserved and unscored; no model was fitted or evaluated during publication.

## Attribution and files

The collector had a generic hard-coded “Micah” contributor header. The user explicitly confirmed Sophie performed this recording. Canonical [`metadata.json`](metadata.json), [`truth-values.json`](truth-values.json), and [`dataset.json`](dataset.json) identify Sophie. **Only the contributor header is corrected; every action interval, timestamp, intent label, selected gesture, effort, condition and wearing-session ID is unchanged.**

`original/` preserves all 18 original capture files. Its JSON files are byte-identical to the source; `original/streams.jsonl.gz` losslessly compresses the original raw JSONL. Original metadata/label headers retain the generic collector attribution solely for audit. Use canonical files for contributor attribution. `publication-manifest.json` records original and published SHA-256 checksums and documents the correction.

The original collection report, condition markers, motion selections, intent markers, signal coverage and optional gyro report are included. Software checks verify stream counts, numeric ADC ranges, eight-channel packet shape and gzip round-trip integrity. These checks do not establish gesture accuracy or exact event timing.

## Evaluation rules

The original role `untouched_guided_count_check`, `do_not_train: true`, and `do_not_tune_thresholds: true` are preserved. Training adapters reject both the canonical session and its original capture folder. Freeze a model and its thresholds before scoring these data. Do not change labels using predictions or use validation results to tune the model while continuing to call this untouched evaluation.

Space down/up and gesture buttons supply weak participant interval labels, not verified physiological onsets or event counts. Snap-labeled intervals are not exact snap timestamps. Preserve original trial/session groupings; overlapping windows are not independent examples. The source wearing-session ID is retained verbatim and does not itself establish independence from every training recording.

To reconstruct the original stream from this session folder:

```sh
python3 -c "import gzip,shutil; shutil.copyfileobj(gzip.open('original/streams.jsonl.gz','rb'),open('streams.jsonl','wb'))"
```

Verify its decompressed SHA-256 against the `streams.jsonl` entry in `publication-manifest.json`.
