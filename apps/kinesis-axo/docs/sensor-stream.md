# Real-time sensor stream

Kinesis provides a local HTTP feed of raw EMG, gyro, orientation, and decoded band gestures, plus a [haptics request](#haptics). Your code reads the existing Kinesis connection; it does not pair with the band separately or compete for its Bluetooth connection. No Python packages, SDK, recording file, or Mac Accessibility permission is required to read the feed.

## Start reading

1. Connect the band in Kinesis. Open the **stream** tab and enable **local sensor feed**. This requests raw EMG and motion even when their graphs are closed. Gesture controls can remain paused.
2. Select **copy stream URL**. It has the form `http://127.0.0.1:8766/events?token=…`. The feed starts off on every app launch; stopping and starting it generates a new token and stream session.
3. From the source repository, run the included standard-library reader with the copied URL:

   ```sh
   python3 scripts/read-sensor-stream.py --url 'COPIED_URL' --seconds 10
   ```

The reader prints event counts and EMG samples per channel, without printing sensor values. It has a two-second socket timeout, so a stalled server cannot leave it waiting indefinitely. To explicitly export received events as JSONL, use:

```sh
python3 scripts/read-sensor-stream.py --url 'COPIED_URL' --seconds 10 --jsonl > samples.jsonl
```

With `--jsonl`, the summary goes to standard error and the file contains sensor events only. The reader bypasses HTTP proxies, refuses remote URLs and redirects, and never includes the copied token in its errors. Keep the copied URL local: its token authorizes access to the feed until you stop it.

The **stream** page shows whether EMG is active, pending, or unavailable. EMG remains subject to the connected band's supported format and model-operation availability. Starting the feed is blocked during an active handwriting/model operation. `emg_requested` is an intention; `emg_active` reports the band's acknowledged state. A connected status alone does not establish that new samples are arriving.

## Browser projects

The endpoint is **Server-Sent Events (SSE)**, with one compact JSON object per event. It works with Python HTTP readers, `curl --no-buffer`, or the browser's built-in `EventSource`. There are no API calls for sending keys, changing mappings, writing band settings, enrolling a band, or accessing pairing credentials.

Serve your browser project from an `http://localhost` or `http://127.0.0.1` origin, for example with `python3 -m http.server 8000`. A `file://` page has a null origin and is refused, as are remote website origins. The endpoint listens on IPv4 loopback only; it is not reachable from another computer or the iPhone.

```js
const source = new EventSource(prompt("Paste Kinesis's copied stream URL"));
const latest = {};
const counts = {};
const types = ["hello", "status", "emg_configuration", "emg", "gyro", "orientation", "gesture"];

for (const type of types) {
  source.addEventListener(type, event => {
    latest[type] = JSON.parse(event.data);
    counts[type] = (counts[type] || 0) + 1;
  });
}
const summary = setInterval(() => console.log({ ...counts }), 1000);
// Read latest.emg.payload.values, latest.gyro.payload.values, etc. in your app.
// When finished:
// clearInterval(summary); source.close();
```

Use named listeners: these events have explicit types, so `source.onmessage` does not receive them. `EventSource` attempts to reconnect after interruption, but Kinesis does not replay missed events. When the feed is stopped and restarted, close the old reader and supply the new URL.

## Schema version 1

Every JSON event has these fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1`. |
| `type` | `hello`, `status`, `emg_configuration`, `emg`, `gyro`, `orientation`, or `gesture`. |
| `stream_session_id` | Random ID for one start of the local feed. |
| `event_sequence` | Increasing counter across that feed, including metadata sent to other readers. |
| `host_time_s` | Mac monotonic uptime in seconds when Kinesis received the event; metadata uses its creation time. |
| `band_timestamp_us` | Band timestamp in microseconds, present on EMG, gyro, orientation, and gestures. |
| `payload` | Event-specific fields below. |

Host uptime and band timestamps are different clocks. Do not subtract them directly or interpret either as Unix time. `hello.payload.status.band_connection_id` and later status events provide an anonymous connection epoch. Start a new synchronization/alignment window when that value changes; neither a stable feed session nor a continuing host clock proves continuity across a band reconnect. Band timestamps are exposed as received, without a fabricated clock conversion.

A new reader receives `hello` with current status and clock/delivery descriptions, then the current `emg_configuration` when known, followed by new events. `status` reports `connected`, `hand` (`left`, `right`, or null), `emg_requested`, `emg_active`, `emg_changing`, `gyro_requested`, `orientation_requested`, `band_connection_id`, and `model_capture_active`. Requested motion flags describe subscriptions, rather than fresh sample delivery. Status and configuration can change while the reader remains connected.

`emg_configuration` contains `sample_rate_hz`, `channels`, `adc_bits`, `samples_per_batch`, `encoding`, `supported`, `units`, and `calibration`. The currently supported observed format is 2,048 Hz per channel, eight channels, 16-bit unsigned counts, 16 samples per batch, encoding zero. Voltage calibration is unknown.

`emg` carries the original decoded `sequence` and a `values` array of **16 rows × 8 channels**, in sample-major order. It also includes `sample_rate_hz: 2048`, `sample_interval_us: 488.28125`, `channels: 8`, `samples_per_batch: 16`, `layout: "sample_major"`, and `units: "unsigned_adc_counts"`. These are ADC counts, without centering, filtering, normalization, or voltage conversion. Preserve the raw sequence and timestamp when building training windows.

`gyro` includes `values: [x, y, z]`, `axes`, and `units: "raw_counts"`. Its `observed_degrees_per_second_per_count: 0.07` is an observed estimate, explicitly marked as uncalibrated. `orientation` contains the received quaternion as `values: [w, x, y, z]`, with the same order listed in `components`; no coordinate transform is applied. Motion is normally received at 128 Hz per enabled stream. Those configured/observed rates do not promise a particular Bluetooth or end-to-end latency.

`gesture` exposes the band's decoded messages before Kinesis's control filtering: `sequence`, `timestamp_us`, `received_at_s`, `finger`, `action`, `derived_action`, `synthetic`, and nullable human-readable `label`. This includes press/release messages and synthetic flags, rather than only the limited list of assignable actions. A raw action and a derived action may describe the same physical contact; consumers must apply their own deduplication and interpretation. A gesture event does not establish that Kinesis executed a mapped keyboard or mouse action.

## Haptics

`POST /haptics?token=<feed token>&ms=<1–2000>`, with an empty body, buzzes the band once for that many milliseconds. It uses the token from the stream URL, so it works only while the feed is enabled. Requests that carry an `Origin` header are refused, so web pages can't trigger it. The reply is `202 Accepted` before the band is reached: if the band is not connected, nothing happens and Kinesis logs the failure.

```sh
curl -X POST "http://127.0.0.1:8766/haptics?token=$TOKEN&ms=200"
```

The band receives HapticsReq (RpcRequest field 17) `{ 1: { 1: ms } }`. Durations are fixed-strength; no strength or pattern control was found.

## Delivery and limits

The feed sends complete incoming batches without waiting for graphs to redraw or recording files to flush. There is no deliberate averaging or sample-rate reduction. The server supports at most four readers and bounds queues to 512 KiB and 1,024 packets. A reader that falls behind is disconnected instead of accumulating delayed sensor history; queued age and stalled-send checks also close stale readers. There is no lossless-recording guarantee, backfill, or `Last-Event-ID` replay.

`event_sequence` gaps alone do not prove sample loss, because other readers' initial metadata uses the same global counter. For EMG continuity, compare `payload.sequence` and band timestamps within a single connection epoch. Sensor gaps can also originate in Bluetooth or the band before the API receives them. Use the recording workflow when you need a saved session, and retain continuity information when excluding gaps from model training.

The older outer Python/log-tail bridge belongs to the earlier studio workflow. This native endpoint exposes the running Kinesis app directly and does not require that bridge or a second band process.

Synthetic reader fixtures can be run with `python3 scripts/test-read-sensor-stream.py`. Swift schema, controller, and transport tests cover the native side without loading saved pairing credentials.
