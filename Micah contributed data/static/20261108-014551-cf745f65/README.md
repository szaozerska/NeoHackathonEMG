# Micah static baseline — 2026-11-08

Completed EMG-only static contribution: 602.49 seconds, 77,386 eight-channel EMG batches at 2048 Hz. Participant-reported labels cover shield and sword holds at low, medium and high effort, with non-intended baseline periods. No snaps, camera, gyro or orientation were recorded in this session. Requested effort is not measured force; static is the collection instruction, not verified immobility.

`truth-values.json` contains the unchanged Space-down/Space-up intervals. These are weak participant reports, not verified physiological action onsets. Preserve the short intervals and adjacent context for review. Several conditions have only one sustained trial; overlapping windows are not independent repetitions. Do not randomly split overlapping windows, invent labels or treat this recording as an independent wearing-session evaluation of the dynamic data: both carry `micah-wearing-01`.

`streams.jsonl.gz` losslessly compresses the original raw stream. All other capture JSON files are unchanged. `publication-manifest.json` records original SHA-256 checksums; decompress to reproduce the raw JSONL. Historical unrelated recordings and model-training data are not included.

```sh
python3 -c "import gzip,shutil; shutil.copyfileobj(gzip.open('streams.jsonl.gz','rb'),open('streams.jsonl','wb'))"
```

Exploratory results and strength-drift traces: [analysis/REPORT.md](analysis/REPORT.md). Public model compatibility and signal-processing review: [research note](../../../docs/metaband-pattern-research.md).
