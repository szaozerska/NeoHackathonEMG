# Spell Training Lab

**New computer / teammate handoff:** start with [HANDOFF.md](HANDOFF.md), or
double-click **Setup Partner Mac.command**, then **Start Partner Bench.command**.
The setup installs pinned Python dependencies, prepares the included Kinesis
app, and verifies bundled classical/neural model files. Agents should read
[AGENTS.md](AGENTS.md). The rest of this README includes historical development
instructions; the handoff is authoritative for a fresh clone.

Experimental **EMG-only neural models** (FNN/CNN comparison, guided twenty-snap
collection, rotation/intensity variants, hard negatives and extensible gesture
classes): [development workflow](docs/neural-emg.md). Existing live models remain
available as backups.

Record **one right-arm Neural Band plus one Quest 3 per player**, label their paired streams, train personalized EMG detectors, calibrate Quest motion detection, and replay complete shield/sword/fireball actions.

- **Mac tools:** Python CLI, browser-based recording/annotation screen, raw capture, quality reports, LDA/logistic hand-state model, transient snap model, motion calibration, live recognition preview, held-out evaluation, and portable exports.
- **Quest:** Unity project scaffold and reusable sender package with Meta tracking adapter, TCP discovery/manual IP, clock-offset estimation, palm calibration, and reconnect handling. Quest sends observations; spell recognition runs on the Mac/server.
- **Spells (v3):** open palm outward with fingers up holds a shield; relative forearm tension controls strength. A fist at any angle summons a sword; opening dismisses it. A middle-thumb snap creates a held fireball; a later throw releases it.

The bench is training/recognition tooling alongside the existing game apps.
Personalized v4/v6 and experimental neural models are bundled under `models/`;
their accuracy on another wearer is unmeasured. Raw training recordings are not bundled.

For **band-only collection now**, follow [EMG-only setup](docs/emg-only.md), or double-click `Start EMG Training.command`. The dashboard waits for Kinesis and opens no Quest services.

For a simple real-time check, double-click **`Start Live Model Test.command`**. See [live testing instructions](docs/live-model-test.md) and [Record/Stop with correction markers](docs/live-correction-recording.md).

## 1. Install the Mac tools

From this repository, using Python 3.11 or later:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
spelltrain --help
```

The current workspace already has a `.venv` with the package installed. Generated recordings/models are ignored by Git.

## 2. Try the full pipeline without hardware

```sh
spelltrain demo --output demo-output
spelltrain review --session demo-output/session-4
```

Open **http://127.0.0.1:8765**. The legacy demo uses the earlier hip/push calibration workflow and must be updated before use with v3. For v3 use the tests below; the demo is not evidence of the new gesture behavior. Inspect `demo-output/model/training-report.json` and `demo-output/evaluation/evaluation.json`.

**Synthetic results verify software behavior, not real EMG accuracy or Quest tracking.** The review page can display saved signal/trajectory intervals and edit annotation timestamps.

## 3. Prepare the Quest

Follow [Quest setup](docs/quest-setup.md). Open `apps/vr-client` with Unity, allow its pinned SDK packages to resolve, configure the tracking rig, and build/install on the Quest. Both devices must share a LAN that permits device-to-device traffic. Use the Mac LAN address in the sender if broadcast discovery is blocked.

The sender defaults to TCP 9000 and approximately 60 observations/second. Hand/chest validity is explicit; no fabricated hand or chest position is used when tracking is missing. The Mac dashboard has **Calibrate palm facing target** and **Reset coordinate history** controls.

## 4. Connect Kinesis

There are two supported input paths; [feed details and source evidence](docs/kinesis-feed.md) explain the distinction.

**Verified upstream raw recorder:** enable Kinesis developer/raw EMG recording, start a new JSONL recording, then tail that file:

```sh
spelltrain record --subject player-a --session data/player-a/session-01 \
  --kinesis-file /absolute/path/to/current-kinesis-emg.jsonl
```

**SSE variant described in the architecture:** set the current loopback URL without placing its secret token in shell history:

```sh
read -r -s 'KINESIS_URL?Paste current Kinesis feed URL: '
export KINESIS_URL
spelltrain inspect-feed --kinesis-env KINESIS_URL
```

Copy `configs/kinesis-sse.example.json` to a local mapping and match the printed payload field names/shapes. The example is a configurable contract, **not a claim that every Kinesis build exposes those keys**.

```sh
spelltrain record --subject player-a --session data/player-a/session-01 \
  --kinesis-env KINESIS_URL --adapter configs/kinesis-sse.example.json
```

A band source is optional for testing Quest capture, but both streams are needed for full training. Input threads are separate from model inference; queue overflow stops recording and is displayed as an error. Do not use an incomplete session for evaluation.

## 5. Collect the new gestures

The dashboard opens **Spell training**: 48 prompted trials, comprising three rounds of open-hand shield effort/position combinations, sword fists at varied angles, relaxed baseline, middle-thumb snaps and non-snap comparisons. Establish steady poses before Record; start recording before snapping or doing comparison motions. Record about five seconds, Stop, then confirm or retry.

Confirmed reports are saved in `gesture-trials-v3.json`, beside raw `streams.jsonl`. “Received” confirms capture, not recognized intent. The old dataset, labels and initial shield model were deleted. No model is trained automatically.

Read [the current training plan](training-plan.md) for exact gestures, label review, model commands and held-out evaluation. In particular, snap clips still need exact event-time review before the primitive trainer can use them. Band-only collection cannot verify palm direction or spatial pose. The new protocol rejects old fist-shield effort labels.

## 6. Train and test

The latest reference-reviewed update is **`artifacts/player-a/gestures-v4`**. See [updated results, reference review and reproducibility](docs/gesture-models-v4.md). The earlier v3 models are retained for comparison.

The initial models for all three gestures are now saved in `artifacts/player-a/gestures-v3`. See [the complete model results and inference instructions](docs/gesture-models-v3.md). Sword/open-hand models use confirmed steady holds; the fireball model learns from snap-containing clips and remains experimental. Individual snap-event accuracy is unknown.

To train the combined bundle from the completed protocol and frozen effort model:

```sh
.venv/bin/python -m spelltrain train-gestures \
  --session data/player-a/band-01 \
  --effort-model artifacts/player-a/shield-effort-v3/effort-model.joblib \
  --output artifacts/player-a/gestures-v3-new-version
```


Close the completed recording, then create an initial open-hand effort model:

```sh
.venv/bin/python -m spelltrain train-effort \
  --session data/player-a/band-01 \
  --output artifacts/player-a/shield-effort-v3
```

See [effort model details](docs/shield-effort-model.md). This command fits only relative shield effort, not sword or snap detection, and does not automatically connect the result to gameplay.

For annotated hand-state/snap datasets, use independent sessions:

```sh
spelltrain train --train data/player-a/session-01 \
  --validation data/player-a/session-02 --output artifacts/player-a/primitives-v3
spelltrain evaluate --sessions data/player-a/session-03 \
  --model artifacts/player-a/primitives-v3 --output artifacts/player-a/evaluation-v3
```

The primitive trainer needs verified hand-state intervals and snap point events; guided collection reports alone do not meet that requirement. Its legacy receive-timing path still needs validation with Bluetooth batching. Do not use the previous hip/push `calibrate` workflow for v3.

## 7. Implementation and checks

`SpellEngine` implements the revised spell gates. The Unity sender includes finger direction for the shield pose. Quest deployment, hardware evaluation, continuous effort calibration, spell visuals and collision mechanics remain to be completed. The combined v3 model now feeds effort into the recorder’s shield gate; weak snap candidates require an explicit experimental flag to cast. An ordinal light/medium/firm score is not measured force or a validated proportional protection curve.

```sh
.venv/bin/python -m pytest -q
node tests/dashboard-ui.cjs
.venv/bin/python scripts/check_unity_core.py
```

The tests cover recording quality, confirmation/retry, protocol isolation, training splits, stationary shield pose/tension, fist summoning/release, snap deduplication and throwing. Source compilation does not build an Android APK or validate headset tracking.
