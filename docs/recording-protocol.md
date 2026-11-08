# Recording protocol and data contracts

The training recorder is a one-player endpoint using the architecture's TCP/NDJSON transport. It is separate from the future multiplayer server. Ports: TCP 9000, UDP discovery beacon `SPELLGAME 9000` to port 47777, local dashboard HTTP 8765. The dashboard binds only to loopback; it does not expose participant data on the LAN.

## Quest handshake and observations

Client sends `{"type":"hello","role":"vr"}`. Recorder returns `{"type":"welcome","player_id":"P1","session_id":"..."}`. A second simultaneous Quest connection is rejected so two subjects cannot mix in one session.

Every pose is one JSON line (maximum 64 KiB):

```json
{
  "type": "pose", "hand_side": "right", "t": 123.45, "t_mac": 4567.89,
  "sync_rtt": 0.012, "seq": 42, "frame_id": "coordinate-epoch-id",
  "hand": {"pos": [0.2,1.3,0.4], "rot": [1,0,0,0], "palm_normal": [0,0,1], "valid": true, "confidence": 1},
  "chest": {"pos": [0,1.4,0], "rot": [1,0,0,0], "valid": true, "confidence": 1},
  "opponent_direction": [0,0,1]
}
```

This training packet contains the subset of the game's `joints` schema needed for right-hand recognition. A game integration should map these fields into the shared game pose packet instead of assuming the training service implements all multiplayer messages. Quaternions use **w,x,y,z**. Positions are in meters in the configured game-origin frame. Directions share that frame.

## Clock exchanges

Quest sends `{"type":"time_ping","t":quest_t0}`; Mac returns `{"type":"time_pong","client_t":quest_t0,"server_recv":mac_t1,"server_send":mac_t2}`. Quest observes `quest_t3` and computes:

```text
RTT = (quest_t3 - quest_t0) - (mac_t2 - mac_t1)
Mac-minus-Quest offset = ((mac_t1 - quest_t0) + (mac_t2 - quest_t3)) / 2
```

The sender uses the lowest-RTT estimate in the connection and repeats exchanges every second. Main-thread scheduling delay is included conservatively in measured RTT. Reconnect resets synchronization. Mac accepts mapped sample times only with bounded RTT and plausible age; otherwise it records receive timing explicitly. Neither timestamp arithmetic nor a low RTT proves perfectly symmetric network delays.

Stored row `t` is the aligned/estimated sample time relative to the recording origin. `received` is Mac receive time relative to that origin. Original source timing is preserved. EMG sample spacing is reconstructed at 2,048 Hz. Kinesis's independent sensor timestamp is never compared directly with Quest or Mac time.

Live and replay processing use receive order for causal availability; Quest derivatives use the saved sample times. Held-state freshness uses receive time. Training labels refer to the aligned sample timeline. For tight parry timing, measure physical-to-availability delay, including Kinesis file buffering, filter/window delay and Unity frame scheduling.

## Files and annotation semantics

- `metadata.json`: schema version, stable subject ID, session ID, side, timing origin, notes, synthetic flag.
- `streams.jsonl`: append-only `emg`, `pose`, and optional live `prediction` rows. Predictions are not labels.
- `annotations.json`: editable verified/unverified labels, trial IDs, start/end seconds, notes and unique annotation IDs. Writes replace the file atomically.

Intervals: `open`, `fist`, `none`, `hard_negative`, `background`, `hip_calibration`, and optional complete `shield`/`sword`/`fireball` intervals. Events: `snap`, `shield_boost`, `sword_cast`, `sword_dismiss`, `fireball_spawn`, `fireball_throw`.

`shield_boost` annotation denotes the observed sharp push, not a claim that a sword struck the shield. Sword-hit/block geometry and damage are outside the training recognizer. Whole-spell intervals provide trial context; model training uses explicit hand-state intervals and snap events.

Only verified intervals entirely containing an EMG feature window label that window. Conflicting hand labels are excluded. Snap positives are causal window endpoints in the 90 ms after annotated onset; nearby ambiguous recovery windows are excluded. Negative snap windows require explicitly labeled non-snap context. One-to-one event matching prevents repeated overlapping positives from counting as multiple successful snaps.

Sessions used for fitting, model/threshold selection, or motion calibration cannot be final test sessions. Keep one physical attempt under one trial ID, and split whole sessions. Real and synthetic recordings and different subjects/sides cannot mix in a model.

## Data integrity and missing observations

Sequence gaps reset filters and require fresh warm-up. Without source sequence data, gap detection is approximate; the recording preserves the timing basis. Invalid Quest poses reset derivative history; tracking jumps/recenters require a new frame ID. Stale inputs cannot increase shield strength, complete a draw, or launch from old positions.

TCP sender queues and Mac processing queues are bounded. A growing Quest queue causes reconnect; a full Mac queue stops recording with an error. Graceful shutdown drains the processing queue before closing the stream file. Check the quality report and dashboard errors after every session.
