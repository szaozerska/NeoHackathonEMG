# Partner setup: start here

This package reproduces the Mac EMG test bench. It includes the Python source,
localhost dashboard, personalized v4 fallback, saved v6 model, experimental FNN
weights, collection scripts, dependency pins, and the repository's existing
Kinesis build with haptics. The newer game/server/Quest files are preserved.

## One-command installation

Use an **Apple Silicon Mac, macOS 14 or newer**, with internet for the initial
dependency downloads. Clone/download this repository and double-click
**Setup Partner Mac.command**, or run from its folder:

```sh
bash scripts/setup_partner.sh
```

Setup downloads a checksum-pinned uv binary, installs managed Python 3.14 into
`.setup/`, creates `.venv`, installs pinned inference/training/test dependencies,
verifies model/app hashes, and unpacks Kinesis to `.local/apps/Kinesis.app`.
No Homebrew, global Python changes, Xcode or administrator password are needed.
The included Kinesis executable is Apple Silicon only. Running setup again
reuses the environment. Windows/Linux can run Python analysis separately, but
cannot run this packaged wristband app.

To install the game server and hand-client environments too:

```sh
bash scripts/setup_partner.sh --with-game
```

Unity/Android SDK and headset deployment remain in `apps/vr-client/README.md`;
the Mac EMG bench does not need Unity. These large, licensed editor/toolchain
installations are not embedded in this repository.

## Start the original bench

The launcher now opens **Micah data contribution** at `/`: an EMG-only page
where the mouse starts a session, buttons select Snap/Shield/Sword effort, and
holding/releasing Space marks intended/non-intended intervals. See
[`docs/micah-contribution.md`](docs/micah-contribution.md). No camera is required
or started. The optional **Intent lab** remains at `/collect`, with its workflow
described in [`docs/intent-lab.md`](docs/intent-lab.md). Use **Original
v4 tester** at `/live` for the original model feedback page described below.
Both pages use the same active sensor connection and preserve the v4 weights.
The training order is documented for Sophie in **Our Methodology for Training
Our Neuroband EMG**, architecture.md §2.2.1: intent gate first, independent action
detectors second, temporal transitions third. The new gate is not yet trained.

1. Quit other Kinesis copies. Double-click **Start Partner Bench.command**.
   It opens the prepared Kinesis app and the localhost test page. It does not
   replace `/Applications/Kinesis.app` or change saved band credentials.
2. On the first launch, approve the downloaded app in macOS if requested. The
   build is ad-hoc signed and not Apple-notarized. Complete Bluetooth approval
   and Meta sign-in yourself. Pair the assigned band, choose the right wrist,
   and wear it snugly. Do not factory-reset or forget a working pairing merely
   to install/update the bench. A new Mac needs its own enrollment/permissions.
3. In Kinesis **band**, enable **Developer mode**. Open **readings**, enable
   **Live EMG**, then **record…**. Save to the exact path shown on the web page
   (use **Copy recording path**). If the save dialog hides the folder, press
   Command-Shift-G and paste the full path.
4. Wait for live EMG. Try relaxed hand, closed fist, open shield hand and snaps.
   v4 shows Nothing/Sword/Shield and brief Fireball feedback with a snap count.
   Camera and microphone are optional historical features; do not enable them
   for this EMG-only handoff.
5. Keep the raw Kinesis recording active. The dashboard's **Record**/**Stop**
   buttons separately save model feedback. Stop the dashboard recording before
   quitting, then stop the raw recording in Kinesis when finished.

Default web port is 8765, with 8766 as fallback. Follow the URL printed by the
launcher rather than assuming a port. Fresh live source timestamps are required;
copying an old recording into place does not simulate live band input.
The partner launcher now automatically follows the raw JSONL file Kinesis has
open, so saving it at a different filename does not require reconfiguring the
tester. The original explicit `--kinesis-file` mode remains available.

For live testing without saving a raw recording, open **Connect without a
recording file** on the dashboard. In Kinesis **stream**, enable **local sensor
feed**, copy its URL, and paste it into the dashboard. The link is saved only in
ignored `.local/kinesis-stream-url` with owner-only permissions. It changes when
the feed restarts; paste the replacement link then. Never publish this link.
This optional tester input is separate from the game's hand-client connection.
The guided neural collector still expects its raw recording file.
Accessibility permission is needed only for Kinesis Mac controls; keep controls
paused if you only want EMG capture.

These are personalized player-a models. New-wearer accuracy is unmeasured.
The FNN development check detected 11/12 reviewed snaps with one false event;
hand-state classification did not improve over v4. No 99% claim is established.
`models/neural-emg-03/REPORT.md` records the limitations. The experimental neural
model does not silently replace v4 or the game's current classifier stub.

## Collect new EMG training examples

The exact protocol is in `docs/neural-emg.md`. For twenty separately confirmed
snaps, start a new Kinesis raw recording at a chosen path, then run:

```sh
.venv/bin/python scripts/collect_neural_emg.py \
  --kinesis-file data/partner/raw/snaps-01.jsonl \
  --output-root data/partner/neural-guided \
  --wearing-session partner-wearing-01 --kind snap --repetitions 20
```

Follow each countdown and confirm the actual count (`0` for a missed snap,
`x` to discard uncertainty). Instructions cover soft/firm snaps with minimal,
natural and exaggerated wrist rotation. Then collect `--kind negative` blocks
with wrist rotation, pinching, finger movement and fist transitions without
snapping. Also collect `--kind fist`, `--kind open`, and `--kind none` holds.
Use a new raw filename for a new Kinesis recording.

Use the same wearing-session ID until removing/repositioning the band. After
that, use a new ID and `--role evaluation` for reserved checks. Counts are
participant reports, not exact snap timestamps. Positive clips support weak
multiple-instance training; their entire duration is never labeled as a snap.

All new captures remain local under ignored `data/`. To hand a completed block
back to the model developer, explicitly share the **whole capture folder**:
`streams.jsonl`, metadata, guided trial labels and hash manifest. Do not send
only the count or predictions. Preserve evaluation folders separately.

Historical raw recordings and the 82 MB waveform dataset are **not in Git**.
The original historical retraining command needs those source files on the
original training machine or an explicitly shared dataset. A fresh clone can
run inference, collect new examples, run tests, and continue development; it
cannot reproduce historical training from weights alone. Use new, reviewed
datasets or return new captures to the developer for the next fitted version.
Changing future gesture classes is documented in `configs/neural-emg.json`.

## Checks and troubleshooting

```sh
.venv/bin/python scripts/doctor.py
.venv/bin/python -m pytest -q
```

The doctor verifies hashes, dependency imports and both inference paths without
connecting to the band. Tests can bind temporary localhost ports. Neither
software check proves a new Mac's Bluetooth pairing or actual gesture accuracy.

* Missing `.venv`: rerun setup. An incompatible existing Python environment is
  reported instead of being silently deleted; move it aside and rerun setup.
* No data: check Developer mode, Live EMG, raw recording path and source freshness.
  The raw file should grow. Existing files are tailed from their current end.
* Port conflict: stop an old bench using Ctrl-C in its terminal, or inspect the
  recorded PID/log under `data/player-a/`; never terminate arbitrary processes.
* Kinesis claim/sign-in failure: use its own pairing UI and the assigned band.
  Do not copy another person's Keychain items or account tokens.
* Dependency downloads fail: retain the printed error and retry with internet.
  Setup needs outbound HTTPS once; normal raw-file inference is local.
* Old docs with `/Users/kyuhyunkim/...` are historical development notes. This
  handoff and the relative paths above are authoritative for a new computer.

## Optional game tools

After `--with-game`, use the repository-local uv:

```sh
.setup/bin/uv run --frozen --project apps/server python -m spellgame
.setup/bin/uv run --frozen --project apps/hand-client python -m handclient
```

The hand-client prompts for Kinesis's current stream URL and game server. Read
the two app READMEs for pairing/server controls. It currently uses `EmgLogger`
as its classifier: wiring the new neural outputs into game messages is future
integration work, not an effect of installing this bench.

## Ask Codex or Claude

Paste this after cloning:

> Read AGENTS.md and HANDOFF.md. Set up this Mac using the packaged partner
> setup, run the doctor and tests, then start the original v4 localhost EMG
> bench with the bundled Kinesis app. Help me pair my own band and start raw
> EMG recording at the displayed path. Next help me collect the twenty-snap
> rotation/intensity protocol and matching no-snap controls. Keep evaluation
> sessions separate; do not use camera inputs or publish my recordings.
