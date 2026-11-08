# Neural Band input options

The architecture describes Axo's loopback SSE feed at port 8766. Public-source inspection found `callbacked/kinesis`, whose current upstream revision **5c78485f48c0758e2ce46ee11d3aaa070d827b75** has raw EMG recording but no matching SSE endpoint. Do not assume the current upstream download and the architecture's feed-enabled build have identical interfaces.

## Upstream raw JSONL recording (implemented and source-verified)

Sources:

- [Raw record creation in BandModel.swift](https://github.com/callbacked/kinesis/blob/5c78485f48c0758e2ce46ee11d3aaa070d827b75/Sources/Kinesis/BandModel.swift)
- [EMG configuration and binary layout](https://github.com/callbacked/kinesis/blob/5c78485f48c0758e2ce46ee11d3aaa070d827b75/Sources/KinesisCore/EMGReadings.swift)
- [Protocol notes](https://github.com/callbacked/kinesis/blob/5c78485f48c0758e2ce46ee11d3aaa070d827b75/docs/protocol.md)

Use a Kinesis developer build/raw readings view to enable raw EMG and start a new recording. `spelltrain record --kinesis-file FILE` starts at the file's current EOF and follows new complete lines. Start the Kinesis recording first, then the trainer, then perform actions. The trainer does not pair the band itself or change its Bluetooth settings.

Verified raw record shape:

```json
{"t":"ISO wall time","uptime":12345.0,"channel":5,"kind":"0x0200020a","bytes":265,"payload":"HEX_PROTOBUF_PAYLOAD"}
```

`bytes` varies with protobuf field lengths. The hex payload contains protobuf fields 1 (sequence varint), 2 (sensor timestamp in microseconds), and 3 (256 sample bytes). The sample bytes are 128 little-endian unsigned 16-bit values, reshaped to 16 samples × 8 channels, sample-major. ADC calibration/electrode anatomy are not established; the model uses counts.

The reader validates field lengths and preserves source sequence/timestamp. On macOS the implementation checks that Kinesis boot-relative `uptime` is close to Python's monotonic clock before using it. If that check fails, timing is explicitly marked approximate receive timing and an error appears. Measure any residual offset on the actual machine. Raw file writes can be buffered; original uptime is retained, and live preview timing includes file-delivery latency. For fast parries, prefer the feed-enabled SSE build after measuring latency.

The raw file path is not an IMU/quaternion recording; the implemented models use raw EMG plus Quest spatial observations. Optional band IMU features from the design are not required by this implementation.

## SSE feed-enabled build (configurable adapter)

For a build that exposes the architecture's feed, copy its current URL into an environment variable and inspect the event shapes:

```sh
read -r -s 'KINESIS_URL?Paste current Kinesis feed URL: '
export KINESIS_URL
spelltrain inspect-feed --kinesis-env KINESIS_URL
```

The inspection command prints event names and field types/array dimensions, not payload values or the URL/token. URLs must be HTTP loopback addresses. Feed exceptions are sanitized to avoid revealing the token.

Configure dot-separated field paths using `configs/kinesis-sse.example.json`:

| Key | Meaning |
|---|---|
| `type_path` | Payload event-type field; if absent, use the SSE `event:` name |
| `emg_type` | Exact type/name for EMG events |
| `samples_path` | Numeric samples field |
| `layout` | `sample_major`, `channel_major`, or flattened sample-major `flat` |
| `sequence_path` | Optional sequence field; missing sequence reduces gap-detection certainty |
| `timestamp_path` | Optional original timestamp, preserved in its native clock domain |

The example names are illustrative; verify against the actual feed. The trainer does not guess fields or assume sensor timestamps are Mac timestamps. It reconstructs per-sample spacing at 2,048 Hz and anchors batches to receive time, continuing a sample clock across contiguous sequences. Reconnects/gaps reset filtering and warm-up.

One dedicated SSE reader fans into a bounded processing queue; the dashboard does not open another Kinesis reader. The SSE path currently consumes EMG events, not optional gyro/quaternion events. The classifiers and Quest fusion do not require those optional streams.
