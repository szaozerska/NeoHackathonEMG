# Restored v4 baseline and regression analysis

The active baseline is the original `artifacts/player-a/gestures-v4/model.joblib`, SHA-256 `0b61f7f6a0a307e5d7a834e8a8a30bff9edb3ccb1648f0b58c0bb255cd60077d`. This matches the base-model hash recorded by the v5 trainer. The saved feedback captures before v5 identify their model as v4. v3 used a weak snap model that emitted candidates by default; v4 is the reference-reviewed model associated with the user's early transition complaints.

The rollback restores the original weights and reconstructs the documented v4 live feedback behavior: the existing decision smoother remains; detected snaps briefly display Fireball for 1.25 seconds, then the display returns to Sword, Shield or Nothing. Persistent inventory/readiness rules and manual equipment switching are disabled in this feedback mode. This is classifier testing, not Quest gameplay semantics. The classifier file is unchanged; this is not a newly trained model. Historical app source was not versioned as a complete release, so the restored presentation follows the saved documentation and capture settings rather than claiming a byte-for-byte application rollback.

Camera/reference recording and complete diagnostics remain available independently. Camera is optional in this baseline. Previous recordings and v5/v6 artifacts remain intact. New recordings get unique directories and record both model version and display policy. The launcher now defaults to v4.

## Evidence

`scripts/audit_model_rollback.py` replayed the three existing feedback captures through each frozen model, then independently compared brief feedback with equipment persistence. Results are in `artifacts/player-a/rollback-v4-audit/comparison.json`.

| Capture | v4 raw snap events | v5 | v6 |
|---|---:|---:|---:|
| 20:41:49 | 1 | 1 | 1 |
| 20:56:30 | 6 | 4 | 4 |
| 21:23:04 | 6 | 3 | 3 |

In the latest capture, all three models trigger in 3/6 prospective snap-intent windows, but not the exact same windows. v4 also triggers in two sword-intent windows; v5/v6 trigger in zero of those four non-snap intent windows. These are weak reported-action windows, not verified physical event labels. One additional v4 event is outside the cue windows. This does not establish that v4 has objectively higher accuracy. It remains the user's preferred baseline for a fresh comparison.

Holding classifier weights fixed exposes the runtime effect. For v6 on that capture, packet-time sampled Fireball display duration is approximately 4.38 seconds in brief-feedback mode versus 27.49 seconds in equipment mode. For v4 it is 8.82 versus 28.51 seconds. The calculations include packet sampling/batching and do not measure actual browser exposure or physical latency. Camera footage is absent from these three captures.

## Why the changes could feel worse

1. **Different jobs were mixed together.** Snap observation, displayed feedback and persistent spell inventory were changed together. A brief erroneous snap could become a long-lived equipped fireball until a confirmed fist canceled it. Persistent Fireball also overrode open-hand/Shield feedback.
2. **The labels were weaker than the behavior changes required.** Later fitting used prospective intent windows and delayed reports, not exact verified snap times. A snap-containing clip does not tell us the precise onset or the post-snap hand state. Using these sessions for repeated development checks does not establish independent-session accuracy.
3. **The v5 gate required a state the model was not trained to distinguish well.** Requiring confirmed open hand after snapping missed readiness when the relaxed post-snap hand did not resemble the deliberate shield-open examples. v6 removed that gate but made false detections immediately persistent.
4. **The vocabulary conflates open hand with shield.** A single open-hand class cannot independently identify relaxed open-hand Fireball holding versus the full shield gesture. Adding priority/cancellation rules does not create that missing distinction. Full shield pose and actual throwing require spatial evidence or separately validated labels.
5. **Transient timing remains a genuine classifier issue.** Snap features use 125 ms windows, whereas hand state uses about 200 ms plus smoothing/dwell. Muscle activation during entry/release can resemble a snap before a stable posture is established. v4 therefore still has the original transition false positives.
6. **The snap operating point changed.** v4's score threshold is 0.999; v5/v6 use 0.98 with different weights. The scores are not calibrated probabilities, so threshold values alone do not prove causation. They should have been evaluated together with complete transition behavior before promotion.
7. **The evaluation was too narrow for the deployment claims.** Five reference snaps and short steady-state clips do not validate continuous equip/cancel sequences or cross-session stability. Later held-out feedback checks did not establish a clear snap-classification improvement. The newer models should have remained candidates while a frozen baseline was compared on fresh, independently reviewed recordings.

## Fresh work from this baseline

Keep v4 and its decision policy frozen. Record whole Nothing → Shield → Nothing and Nothing → Sword → Nothing sequences, isolated snaps, and snap → open hold → fist sequences. Include the independent camera/audio reference when practical. Review actions and onset intervals from the media, mark uncertainty, and leave one separately donned session untouched. Compare candidate classifier weights under the same feedback policy; separately compare equipment rules using fixed classifier outputs. Promote only after transition false activations, missed snaps, steady-state stability and latency are all measured on the fresh test set. Do not train from the model's own displayed labels.
