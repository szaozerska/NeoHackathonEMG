# v5: EMG feedback update and equipment memory

The deployed model is `artifacts/player-a/gestures-v5/model.joblib`. Hand-state and snap classifier weights were updated from the two recorded feedback sessions. Effort weights remain unchanged because these sessions contain no effort-level labels. No webcam pixels, microphone samples or Quest tracking enter the EMG classifier. Video/audio may be used separately to review labels.

## Observation, equipment and commitment

- EMG observes fist, open hand, snap candidates and relative muscle activation.
- A snap primes a candidate. A subsequent confirmed open hand within one second prepares **Fireball ready**. Earlier open-hand memory alone cannot confirm it.
- Ready persists while the stream remains valid; it has no fixed inventory timeout. A confirmed fist cancels it and equips Sword, whether closure is immediate or delayed. Repeated copies of the same snap cannot rearm it.
- The band-only tester cannot commit a fireball. Quest/Unity must confirm continuous forward throwing motion with fresh open-hand evidence after readiness. Movement history resets on tracking loss/recentering and upon readiness, preventing the snap's own motion from throwing.
- Sword equipment is independent of wrist orientation. Quest supplies sword placement, direction, swing speed and game collisions; EMG effort is not a physical damage/force measurement.
- Shield hand/effort is a band-only candidate. Full pose, spatial placement and orientation still require Quest.

These rules do not make a false snap classifier prediction correct. State memory controls equipment and commitment separately from raw detections.

## Evaluation and limits

| Check | v5 result | Meaning |
|---|---|---|
| Feedback held-out steady-state segments | 7/7 correct (3 fist, 3 open, 1 none) | Participant-reported states from the same wearing sessions; not general accuracy |
| Feedback held-out snap-containing clips | 5/8 correct, unchanged from v4 | Two sword clips still flag snap; one older reported snap clip is missed. Marks do not establish exact snap times |
| Known reference snap regression | 5/5 events, 0 false events at ±250 ms matching | Previously inspected reference clips; not a fresh independent test or latency claim |
| Known reference state regression | 14/15 segments | Same existing reference set |
| Effort | Unchanged | No new effort evaluation data |

Fitting/validation/feedback-check partitions and original file hashes are in `training-report.json`. Parameters were saved before checking feedback holdouts. Weak clips use multiple-instance labels instead of guessed snap point timestamps. Overlapping intent windows were truncated. Genuine sequence discontinuities reset signal filtering.

Offline replay of the latest 77.2-second capture processed all 10,194 EMG packets (including pre-roll). There are two genuine source-sequence gaps. The updated runtime produced four raw snap candidates, zero confirmed readiness events and zero commits. The two snap-intended windows lacked a confirmed post-snap open state; readiness is deliberately not fabricated. See `sequence-replay.json`. This is debugging evidence, not a new accuracy estimate.

Next collect snap → hold open → fist sequences, including immediate and delayed closure, plus fist-only and shield transitions as negatives. Confirm performed actions independently of predictions. In particular, a relaxed open hand after snapping may differ from the shield-open training posture; current results do not establish reliable detection of that state. A fresh wearing session should remain untouched for final evaluation.

## Testing and recording

Run `Start Live Model Test.command`, or `.venv/bin/python scripts/start_live_test.py --background --open-browser`.

The Record button saves raw EMG, every hand-state probability, effort prediction, every snap-window score/threshold/rearm flag, emitted events, displayed decisions and readiness/cancellation transitions. Participant marks are separate, approximate labels. While recording, select Fireball before snapping once and holding the hand open; subsequently select Sword before closing the fist. Also test fist-only and shield-only trials. Stop & save preserves the capture directory.

Models remain frozen during recording. The observer endpoint `/api/observe` exposes recent observations; the capture files are the complete recording. Old captures did not store each non-triggering snap score, but preserve original EMG for reproducible scoring. This app has no camera/microphone requirement and no automatic learning from its own predictions.
