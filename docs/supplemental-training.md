# Extra gesture collection

This adds a new session. Do not delete or overwrite `band-01` or the existing artifacts.

Start with `Start Extra Training.command`, or:

```sh
.venv/bin/python scripts/start_emg.py --profile supplemental --background
```

Visit http://127.0.0.1:8765. Use the compatible Kinesis app under `data/support/Kinesis-find-again-v11.app`, not the original application in Applications. Stop its earlier raw recording and start a NEW one at the exact path displayed on the dashboard. The launcher chooses the next unused `band-NN` session and raw file.

Click **Enable camera & microphone**, allow the browser to use the Mac devices, and position your right hand in the preview. Recordings start only on **Start Record**. Each trial saves a short local camera/microphone reference alongside EMG, so later review can identify actual snaps and fist transitions. The Quest is not needed for this phase.

There are 40 trials, in two rounds of 20:

- Relaxed arm resting and raised.
- Three fist holds with varying wrist/arm positions. The label is always fist; angle is not a separate class.
- Two close/open transition sequences with visual cues.
- Light, medium and firm open-hand shield effort with gentle arm movement; one changing-effort sequence.
- Five isolated middle-thumb snaps per round, exactly one snap per trial, after the visual cue.
- Pinch, wrist, finger and ordinary movement comparisons without snapping.

Establish steady poses BEFORE Record. For transitions and snaps, start in the initial pose and follow the timed visual cues AFTER Record. Stop after six seconds. Once both EMG and the reference clip are saved, the page shows **Received.** Confirm only if the prompt was performed correctly, your hand remained visible and a snap trial contained exactly one snap. Otherwise retry. Upload failures can be retried while the page stays open; if the browser loses the clip, retry that trial. Earlier confirmed trials are retained.

Raw EMG is in `streams.jsonl`. Reports are in `supplemental-trials-v4.json`; video/audio clips are in `references/`. Downloaded JSON labels alone do not contain the signals or reference media. Keep the entire session directory. Optional replay is available before confirmation under **Review this recording**.

Visual cues specify when to act; they are not labeled as verified physical event times. Browser recorder start and request/response timestamps provide approximate session alignment. Hardware audio/video latency is not calibrated, and later event review must account for alignment uncertainty. The clips are an independent observation of the action, not automatic precise event ground truth.

The new protocol is `spells-supplemental-reference-v4`, separate from the v3 baseline. Stable fist/open/rest and effort labels can be reviewed directly; snap/transition times require the reference. Do not point the old v3-only trainer at these labels or automatically turn cues into snap events. Reference review and multi-session retraining are the next step after collection.

This first extra session is marked **development**. After collecting it, record another separately donned band session for untouched testing. To reserve that next session, close the prior recorder and launch with `--dataset-role test`. Do not remove/reseat the band in the middle of a session.
