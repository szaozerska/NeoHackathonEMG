# EMG bench handoff

Read `HANDOFF.md` first for new-computer setup. It supersedes machine-specific
paths and older setup advice in historical `docs/` notes.

* Install: `bash scripts/setup_partner.sh` on Apple Silicon macOS 14+; append
  `--with-game` for the existing server/hand-client locked environments.
* Verify: `.venv/bin/python scripts/doctor.py`, then
  `.venv/bin/python -m pytest -q` (tests need localhost sockets).
* Start: `.venv/bin/python scripts/start_partner_bench.py`. The original test
  bench uses `models/gestures-v4/model.joblib`. Neural checkpoints under
  `models/neural-emg-03` are experimental and do not auto-replace v4.
* Kinesis already lives in `apps/kinesis-axo` with a tracked prebuilt archive
  and haptics support. Setup prepares a copy under `.local/apps/`; do not
  overwrite `/Applications`, downgrade this game build or reset pairing.
* Meta sign-in, Bluetooth/app approval and selecting the assigned band are
  interactive wearer steps. Never request or copy credentials/Keychain files.
* The bench tails Kinesis Developer mode → readings → Live EMG → raw record.
  Use the exact filename displayed by the localhost dashboard. Game hand-client
  SSE is a different path; its classifier is still an `EmgLogger` stub.
* New model training/inference uses EMG only. No new camera work is requested.
  Preserve confirmed counts as weak labels; never invent snap timestamps or
  treat predictions/cues as ground truth. Collect soft/firm and varied-rotation
  snaps plus rotation-only/pinch/finger/fist-transition controls.
* Keep recordings, generated artifacts, installed environments and tokens out
  of Git. Historical training data are not distributed; do not claim a fresh
  clone can reproduce that historical fit without separately supplied data.
* Split by original clip/wearing session as appropriate; preserve reserved
  evaluations. Existing development results do not establish 99% accuracy.
* Gesture labels/output dimensions are configurable in `configs/neural-emg.json`.
  Spell rules and Quest spatial confirmation stay separate from classification.
* Preserve the existing game/Unity changes. The bench is additional tooling,
  not a replacement for `apps/server`, `apps/hand-client` or `apps/vr-client`.
