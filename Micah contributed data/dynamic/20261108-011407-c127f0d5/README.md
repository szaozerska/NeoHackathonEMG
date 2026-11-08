# Dynamic contribution: 20261108-011407-c127f0d5

Micah described this as dynamic testing with arm movement, wrist rotation,
jerking and ordinary non-intended activity. This is **not a static recording**.

The session lasts **1,198.97 seconds (~20 minutes)** and contains 2,434,096
recorded samples per EMG channel. The primary labels include **150 snap
intervals** and **259 Shield/Sword hold intervals** at participant-reported
low/medium/high effort. No camera, gyro or orientation was captured in this
EMG-file session. Their absence is documented rather than imputed.

## Original data and labels

`original/` preserves the original JSON metadata and labels byte for byte.
`streams.jsonl.gz` is a lossless gzip archive of the original 233.6 MB JSONL
stream; decompression reproduces its recorded SHA-256. See
`original/source-manifest.json` for original and published hashes.

```sh
gzip -dk original/streams.jsonl.gz
```

The decompressed JSONL is for local analysis. Keep the compact gzip archive as
the Git-distributed original rather than adding the >100 MB decompressed file.

**Participant labels are the primary reference. No original label has been
changed, no recording has been deleted, and no model has been retrained.**
These reported intervals still require postprocessing; they are not verified
physical snap onset/offset annotations. This is training/development data from
one wearing session, not an untouched accuracy test.

## Exploratory review

The analysis uses sensor timestamps aligned to host time, not Python file-tail
receipt time. Kinesis→Python delivery lag was approximately **279 ms median /
495 ms p95**, so labeling samples by file-arrival time would be inappropriate.
The timing fit, clock uncertainty and limitations are in `analysis/review-report.json`.
There were 217 sequence discontinuities and an estimated 1,598 missing batches;
filters reset across gaps and no missing samples were manufactured.

Of 150 snap-labeled intervals, 145 supplied usable isolated reference peaks.
A mutually similar core of 116 peaks supplied amplitude-normalized temporal /
channel templates. This is a robust exploratory comparison, not a trained or
validated intent classifier. Lower-agreement examples may be valid soft or
rotated snaps, not necessarily bad labels.

Four original non-intended intervals contained snap-like bursts above the
exploratory template-similarity cutoff:

| Rank | Capture time | Similarity | Distance from nearest key boundary |
|---|---|---|---|
| 1 | 04:09.180 | 0.945 | 1.37 s |
| 2 | 05:37.632 | 0.914 | 2.06 s |
| 3 | 03:31.696 | 0.886 | 1.24 s |
| 4 | 03:41.227 | 0.876 | 10.77 s |

These may be missed keyboard labels, accidental snaps, jerks or other movements.
The first two are relatively isolated bursts; the other two sit within larger
dynamic-motion clusters and are more ambiguous. Ranking includes that context.
**Waveform similarity cannot establish mental intent.** Review them with Micah
before changing a label. Scores are not calibrated probabilities. The key
windows, raw data and original labels remain intact.

`analysis/label-review-queue.json` additionally retains 34 snap-labeled intervals
for inspection: 29 lower-consensus waveforms and five without a usable isolated
peak. This queue does not automatically exclude them from training or relabel
them as non-intended. `analysis/condition-patterns.json` summarizes the repeated
snap and hold conditions without interpreting EMG as measured physical force.

Useful files:

- `analysis/review-candidates.json` / `.csv`: candidate times and review windows.
- `analysis/dynamic-overview.png`: labeled timeline and candidate markers.
- `analysis/candidate-windows.png`: candidate waveforms with original labels.
- `analysis/reference-quality.json`: per-example consensus provenance.
- `analysis/review-report.json`: methods, timing and limitations.
- `analysis/envelope-review.npz`: derived RMS series for further inspection;
  this does not replace the raw stream or original labels.

Reproduce into a **new** directory using the complete original source folder:

```sh
.venv/bin/python scripts/review_micah_dynamic.py \
  --source "Micah data contribution/20261108-011407-c127f0d5" \
  --output ".local/reproduced-dynamic-review"
```

The script requires NumPy, SciPy and Matplotlib. It compares patterns and
publishes a review queue; it never promotes predictions to ground truth.
