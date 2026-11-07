# band-probe

Throwaway CLI for reverse-engineering the Meta neural band's RPCs, starting with haptics (`hapticsReq`, RpcRequest field 17, schema unknown).

It reuses Kinesis's protocol code (`KinesisCore`) from a local checkout at `~/dev/Kinesis-Axo`. That checkout needs the small patch that exposes `KinesisCore` as a library and adds `BandSession.sendRPC(field:payload:)` and the `rpcReply` event.

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

Replies are printed as raw hex plus a schema-less protobuf tree. Type `0x02000315` is an RpcResponse: field 1 is the request ID and field 2 the status (1 = success). Type `0x0300c001` is the band rejecting the request.

Each probe opens its own channel (`0x8009`), so replies never get mixed up with Kinesis's own requests. Unknown writes may change settings that persist on the band. Read the config with `rpc 5` before and after experimenting.
