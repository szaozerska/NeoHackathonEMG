# band-probe

Throwaway CLI for reverse-engineering the Meta neural band's RPCs, starting with haptics (`hapticsReq`, RpcRequest field 17, schema unknown).

It reuses Kinesis's protocol code (`KinesisCore`) from the patched copy in [`apps/kinesis-axo`](../kinesis-axo). The patch exposes `KinesisCore` as a library and adds `BandSession.sendRPC(field:payload:)` and the `rpcReply` event.

## run

1. Quit Kinesis. Only one app can hold the band, and the probe takes the same lock.
2. Run:

```sh
cd apps/band-probe && swift run BandProbe
```

The probe connects to the band saved in Kinesis and uses Kinesis's stored identity from the keychain. Allow the keychain prompt and the Bluetooth prompt for your terminal the first time. To use a different band, pass its UUID as an argument.

## commands

```
rpc 17                 empty hapticsReq: does the band accept field 17 at all?
pb 17 1=1              hapticsReq { 1: 1 }
pb 17 1=1 2=x:0801     field 2 as bytes (a nested message { 1: 1 })
enc 1=1 2=200          print the hex of a message, for nesting
rpc 5                  empty ConfigReq: reads current config (handedness is field 10). snapshot before/after experiments
quit
```

## haptics findings

`HapticsReq` is RpcRequest field 17. Its reply is in field 18, matching the request N → response N+1 pattern of the other requests.

| Request | Result |
|---|---|
| `rpc 17` (empty) | accepted, no buzz |
| `pb 17 1=1 2=100` | no reply: field 1 and/or 2 is a message, not a varint |
| `rpc 17 0a00` (`1: {}`) | **buzzes continuously until stopped** |
| `rpc 17 1200` (`2: {}`) | **stops the buzz** |

Inside the start message (field 1), from `sweep 1,2,3,4,5,6` with a varint `1`, empty bytes `x:` and a float `f:0.5`:

| Inner field | Type the band accepts | Effect seen |
|---|---|---|
| 1 | varint | **duration in ms** (confirmed: `sweep 1 x` buzzes for x ms; 0 = until stopped, 1 = too short to feel) |
| 2 | float32 | buzzes; 0.05–1.0 feel identical, so not strength on a 0–1 scale |
| 3 | varint | any value tried (1, 2, …) → no buzz at all (actuator or pattern index?) |
| 4–6 | any (ignored) | normal buzz: probably not fields |

For a self-stopping buzz with no stop message, send `pb 17 1=x:08c801`, which is `1: { 1: 200 }`: a 200 ms buzz.

Haptics also went silent band-wide once while gestures still worked, including the pinch buzz in Kinesis. Restarting the band (8-second hold, then a double middle-finger pinch to wake it) brought them back, and resending the same requests didn't break them again. The cause is unknown.

Field 1 is "start", holding the parameters above. Field 2 is "stop". The haptics commands below always send a stop after each buzz:

```
play 1                 1-second default buzz
play 2 1=100           start message { 1: 100 } for 2 seconds
sweep 1,2,3,4 1 100    each field × value for 1.5 s; prints "no reply" if the band couldn't decode it
sweep 1 f:0.5          float32 values
stop                   stop buzzing and cancel a sweep
```

## if the band goes quiet: wake it with a double middle-finger pinch

The band can fall asleep while still connected. Bluetooth, battery, gyro and raw EMG keep working, but its gesture recognizer stops: no gesture events, no pinch buzz, and `rpc 17 0a00` does not buzz either. Reconnecting and restarting the band (8-second button hold) do not wake it.

**A double middle-finger pinch wakes it**, and gestures and haptics come back. Do this before concluding that a probe broke something. Haptics results recorded while it was asleep are not valid; an asleep band showed no change in `rpc 5`.

Replies are printed as raw hex plus a schema-less protobuf tree. Type `0x02000315` is an RpcResponse: field 1 is the request ID and field 2 the status (1 = success). Type `0x0300c001` is the band rejecting the request.

Each probe opens its own channel (`0x8009`), so replies never get mixed up with Kinesis's own requests. Unknown writes may change settings that persist on the band. Read the config with `rpc 5` before and after experimenting.
