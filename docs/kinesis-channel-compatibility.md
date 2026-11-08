# Kinesis claim failure: unsupported band input channel

Observed on the user's Kinesis 0.5.0 pairing screen after discovery and Meta sign-in. The training recorder is not involved in this failure; it occurs before the Bluetooth input stream and ownership handshake open.

Source inspection at upstream commit `5c78485f48c0758e2ce46ee11d3aaa070d827b75` found that `BandConnection.swift` accepts only characteristic bytes `ff 00`, then hardcodes L2CAP channel 255. The original log does not expose which value the band returned, so a firmware/channel mismatch is a hypothesis until the retry's diagnostics are observed.

A local compatibility build:

- Reads the advertised little-endian channel from the same band characteristic instead of requiring 255.
- Rejects missing, malformed, zero, or invalid LE channel values.
- Logs only channel bytes/value for diagnosis; it does not change sign-in, ownership authentication, stored keys, or EMG decoding.
- Adds parser tests; eight standalone parser checks passed and the production Swift app compiled successfully. The full upstream Swift test suite could not run because this Mac's Command Line Tools lack the `Testing` module.

The reproducible source patch is `patches/kinesis-advertised-input-channel.patch`. The built app is stored locally (ignored by Git) at:

`data/support/Kinesis-channel-compat.app`

macOS prevented replacing `/Applications/Kinesis.app`. Its binary hash still matches the original backup at `data/support/Kinesis-0.5.0-original.app`; the installed application was left intact. Use the separate compatibility app for this retry, and avoid running both simultaneously.

Open it with:

```sh
open /Users/kyuhyunkim/NeoHackathonEMG/data/support/Kinesis-channel-compat.app
```

Retry pairing/claim in the app. New Bluetooth/Keychain permission prompts, if any, must be completed by the user. No factory reset or clearing saved credentials is part of this change.

To inspect only the relevant local diagnostics:

```sh
/usr/bin/log show --last 5m --style compact --info --debug \
  --predicate 'subsystem == "local.callbacked.kinesis" AND (eventMessage CONTAINS[c] "Advertised input channel" OR eventMessage CONTAINS[c] "Opening advertised native L2CAP" OR eventMessage CONTAINS[c] "Native connection error")'
```

The original app can be reopened from Applications if this build does not help. Hardware compatibility is not established by the build/parser checks; a successful claim and real EMG samples are still needed.

## Second failure: unsupported band encryption parameters

The user's retry confirmed an advertised channel of **129** and a successfully opened L2CAP stream. The next failure occurred at Kinesis's scheme-3-only encryption negotiation check.

A second local build, `data/support/Kinesis-firmware-compat.app` (bundle build 8), implements the documented newer-firmware differences:

- Scheme 26 key derivation: HKDF-SHA256 over the raw P-256 shared secret with salt SHA256(challenge || seed), retaining AES-256-CBC and authenticated packets.
- Scheme 26 MAC prefix `02 02 00 00`, using the derived encryption key as MAC key.
- Full-block padding for aligned records, with record padding removed before fragmented frame reassembly.
- Routing tagged reply channels through `channel & 0x80ff`, while preserving the raw channel for protocol acknowledgements.
- Explicit negotiated-scheme validation; unknown schemes and invalid packet authentication still fail closed. Existing Meta enrollment and identity-proof logic is unchanged.

Sources are the hardware findings in [air-gestures, commit 6cad0d42d76b7d4b6c5572ed5c52213d95d1be28](https://gitlab.com/896kb/air-gestures/-/blob/6cad0d42d76b7d4b6c5572ed5c52213d95d1be28/docs/hardware-day.md) and [rokid-lumen's protocol core](https://github.com/beyondlevi/rokid-lumen/tree/4fe237668683cbe7e613e3c0121723a9f176102a/rust/band-core). MIT notices are preserved under `patches/licenses` and in the local app's resources.

The cumulative source patch is `patches/kinesis-new-firmware.patch`. A standalone check harness is in `scripts/kinesis-compat/ProtocolChecks.swift`. It compiles alongside the actual KinesisCore sources without requiring Swift Testing:

```sh
swiftc -parse-as-library /private/tmp/emg-kinesis-compat/Sources/KinesisCore/*.swift \
  scripts/kinesis-compat/ProtocolChecks.swift -o /private/tmp/kinesis-protocol-checks
/private/tmp/kinesis-protocol-checks
```

Checks passed for the existing scheme-3 key vector, independent Node crypto scheme-26 key/ciphertext/MAC vectors, rejection of tampered packets without advancing counters, unsupported schemes, aligned legacy payloads ending in padding-like bytes, padded split-frame reassembly, tagged routing, and a synthetic scheme-26 P-256 handshake. The production app compiled and its bundle signature verified. Real hardware claim and EMG streaming still require the user's retry; those have not been established by these checks.

### Actual EnableEncryption response observed

On the user's retry, the initial capability offer was 27, followed by EnableEncryption parameter 27 (not 26); the peer public key matched the initial request. Build 10 (`data/support/Kinesis-firmware-compat-v10.app`) accepts this exact 27 response in the documented scheme-26 family, using the same documented keying. It still requires every packet MAC to verify and the peer key to remain bound; no unauthenticated payload is exposed. This response-family mapping is an interoperability attempt pending actual packet authentication, not a claim that this particular firmware has been verified. The synthetic handshake check now exercises response 27 and still passes, alongside the independent crypto vectors and tamper rejection checks.

## Return to discovery after a reset

Build 11 (`data/support/Kinesis-find-again-v11.app`) adds **Find band again** / **Find nearby bands** to the pairing view. It stops the current connection, clears only the remembered band selection and stale UI state, preserves Meta sign-in and stored identity records, and starts a fresh scan. The scan pauses when a band is found; only an explicit **Pair Band** continues to connection/claim. The optional `--find-band` launch argument runs this path immediately, replacing automatic reconnect for that launch.

The build compiled and its app signature verified. A Swift Testing regression case was added for scan-only routing and credential preservation; execution of the upstream test suite is still limited by this Mac's missing Swift Testing module. Real-app discovery is checked through the `Fresh band discovery requested` and `Native band scan started/finished` log events.
