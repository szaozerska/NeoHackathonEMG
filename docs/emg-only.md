# Start collecting EMG without a Quest

The Mac environment is installed in `.venv`. Kinesis is installed at `/Applications/Kinesis.app`.

## Open the tools

Double-click **Start EMG Training.command** at the repository root, or run:

```sh
cd /Users/kyuhyunkim/NeoHackathonEMG
.venv/bin/python scripts/start_emg.py
```

The launcher chooses a new `data/player-a/band-NN` session without overwriting old data. If the dashboard is already running, it prints its current session/path instead of starting a duplicate.

Open **http://127.0.0.1:8765**. The EMG-only mode opens no Quest listener or discovery service. The page displays the exact raw recording filename it is waiting for.

## Connect the band

1. Open Kinesis, wear the band on the right wrist, and complete Pair Band / Meta sign-in.
2. Enable Developer mode on Kinesis's Band page.
3. Open Readings and enable Live EMG.
4. Click record… and save using the **exact path shown on the dashboard**. For the first session:

   `/Users/kyuhyunkim/NeoHackathonEMG/data/player-a/raw/band-01.jsonl`

The recorder can be started before this file exists. It attaches when Kinesis creates the file. It does not generate artificial EMG, pair the band, or collect credentials.

## Collect labels

The default screen is now **Shield training**. Wait for **Band connected · EMG is flowing**.

1. Follow the current prompt with the right hand. For shield conditions, close your fist with the thumb side facing up and use the requested comfortable tension.
2. Press **Start Record**, perform the prompt for about 5 seconds, then **Stop**.
3. **Received.** confirms fresh, varying EMG. Confirm **I did it · Save & Next** only if you performed the requested effort, hand shape and movement. Otherwise choose **Retry this trial**.
4. Relax during the 5-second rest. Continue through three rounds of 12 conditions: light/medium/firm effort × hold/slow push/sharp push, plus rest, open hand and sword-draw comparisons.

Your confirmed reports are stored in `shield-fist-trials.json` and the original EMG remains in `streams.jsonl`. Progress survives page refreshes. Failed and retried attempts remain in the file, excluded by `confirmed != true`. Downloaded trial labels are a manifest, not a replacement for the raw stream.

Band-only examples can support a future personalized effort model. They do not verify forward motion or contact force. Later collect this protocol with the band and Quest together; the recorder marks valid synchronized captures `paired`, otherwise `emg_only` or `paired_incomplete`. No effort model or shield-strength prediction is active yet, and the existing `spelltrain train` command does not consume these effort labels.

Choose **Signal check** for the six-motion reception test. Choose **Advanced tools** for the original open/fist/none and snap annotation workflow below.

Begin with guided open/fist/none trials. None means a relaxed hand. Perform shield thrusts with a thumb-side-up fist and sword draws/holds while clenched. Their spatial sequences distinguish the spells. Review each trial, check Observed and verified only when correct, and save. Collect snap point labels and hard-negative intervals separately; button clicks include reaction delay, so verify/correct snap timing from the observed action.

Aim for at least 20 independent trials per state and 40–60 snaps per session, plus non-snap activities. Do not label an intended failed action as a successful one.

## Finish and repeat

In **Advanced tools**, click **Finish recording** to close and flush the Mac recording, then click stop recording in Kinesis. Alternatively, Ctrl-C stops a foreground launcher. Double-click the launcher again for the next session; use the new raw filename shown on the dashboard. Remove and replace the band between sessions.

Use three sessions for initial training and validation:

```sh
source .venv/bin/activate
spelltrain train \
  --train data/player-a/band-01 data/player-a/band-02 \
  --validation data/player-a/band-03 \
  --output artifacts/player-a/emg-v1
```

This trains the hand-state and snap detectors from one band. Quest motion calibration and full spell testing can be added later using paired recordings.
