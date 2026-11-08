# Micah EMG pattern analysis — 2026-11-08

Exploratory development results using unchanged participant reports. No live model was replaced.

## Shield versus sword: what information helps?

Train on dynamic holds; evaluate on static holds. Equal weight per class and per original interval. This is cross-condition transfer within a shared wearing-session identifier, not independent session validation.

| Features (ExtraTrees) | Mean interval-balanced recall | Shield recall | Sword recall |
|---|---:|---:|---:|
| energy_only | 58.1% | 80.1% | 36.1% |
| channel_profile_only | 83.0% | 66.7% | 99.3% |
| full_time_spectral | 84.8% | 69.6% | 99.9% |

The relative channel pattern is much more useful than total amplitude alone. These are electrode measurements; no anatomical muscle or causal intent attribution is established.

## Effort drift

| Original interval | Participant selection | Median RMS (ADC) | Last/first-third amplitude |
|---|---|---:|---:|
| 1 | shield_hold low | 63.6 | 0.90 |
| 3 | shield_hold medium | 133.6 | 0.69 |
| 5 | shield_hold high | 128.7 | 0.80 |
| 7 | shield_hold high | 61.3 | 1.00 |
| 15 | sword_hold low | 10.3 | 0.85 |
| 17 | sword_hold low | 10.5 | 1.00 |
| 19 | sword_hold medium | 118.0 | 1.07 |
| 21 | sword_hold medium | 125.7 | 0.63 |
| 23 | sword_hold high | 157.7 | 1.11 |
| 25 | sword_hold high | 176.0 | 0.70 |

Strength drift is preserved, not automatically relabeled. Medium and high shield amplitude overlap; the short high-shield interval #7 has a different profile and merits review without changing its label. Low sword is close to the quiet signal floor. Three subsecond intended intervals have no 0.5-second interior and remain in the raw dataset and untrimmed sensitivity analysis.

## Intent gate and boundary sensitivity

The full-feature ExtraTrees dynamic-to-static intent model achieves 51.3% mean interval-balanced recall on interior windows; fitting/evaluating with all complete untrimmed windows gives 70.1%. This difference shows dependence on window selection and weak label boundaries. It does not establish the true event boundary or justify cleaning labels with model predictions. A hard intent gate is not ready.

## Validation limits

- Both recordings share a wearing-session identifier; transfer is across conditions, not independent wearing sessions.
- Static holds are sequentially blocked by class/effort; elapsed-time/contact drift can confound classification.
- Interior windows are a sensitivity subset, not automatic boundary correction. Raw labels remain unchanged.
- No static snaps or relaxed open-fireball trials; shield tension is not a verified relaxed-open baseline.
- Requested effort can drift. ADC amplitude is not calibrated force or a measurement of individual muscles.
- No gyro/orientation was recorded; continuous orientation invariance cannot be evaluated here.
- Multiple model comparisons are exploratory development, not reserved final evaluation.
- Binary intent predicts report-associated patterns; a hard gate may suppress subtle true snaps.

Six-way motion/strength validation lacks repeated shield-low and shield-medium trials. Collect interleaved repetitions across strengths and poses, including low sword, relaxed-open holds and hard negative movements. Keep new wearing sessions separate.

## Reproduce

```sh
.venv/bin/python scripts/analyze_micah_patterns.py \
  --static "Micah contributed data/static/20261108-014551-cf745f65" \
  --dynamic "Micah contributed data/dynamic/20261108-011407-c127f0d5/original" \
  --output .local/micah-pattern-analysis
```

Reads raw JSONL or its lossless gzip form. Caches are hash-keyed and stay in the requested output folder. Matplotlib is needed for the plot. Full scores, fold membership, timing and five-second drift trajectories are in `pattern-report.json`.
