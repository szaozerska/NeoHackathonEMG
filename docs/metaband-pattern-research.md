# Meta wristband signal processing and compatibility review

Checked 2026-11-08 for Micah and Sophie. The local stream is eight unsigned
16-bit channels at 2048 Hz, delivered in 16-sample batches. ADC voltage scaling
and anatomical electrode-to-muscle mapping are unknown. The completed static
capture has EMG only; its manifest does not contain gyro or orientation samples.

## Public implementations worth using

| Source | What is available | Fit to this project |
|---|---|---|
| [Meta generic neuromotor interface](https://github.com/facebookresearch/generic-neuromotor-interface) | Research data, temporal gesture architecture and pretrained checkpoints | Strong architecture reference; not a directly compatible consumer-band snap model |
| [Meta emg2pose](https://github.com/facebookresearch/emg2pose) | EMG-to-joint-angle models and downloadable checkpoints | Useful pose-estimation research; needs input/domain adaptation and joint-angle supervision unavailable in these captures |
| [LibEMG](https://github.com/LibEMG/libemg) | Feature extraction, selection and real-time evaluation tooling, MIT license | Good source of interpretable baselines, force-variation features and independent feature checks |
| [Kinesis](https://github.com/callbacked/kinesis) and [neural-band-poc](https://github.com/callbacked/neural-band-poc) | Consumer-band acquisition and decoded taps/holds/swipes | Already the capture foundation; these event labels are not ground truth for our custom snap/shield/sword classes |
| [McGill device-agnostic sEMG](https://github.com/McGill-AI-Lab/device-agnostic-semg) | Active research on electrode/contact/session/domain variation | Relevant robustness direction; no validated eight-channel snap checkpoint was established by this review |

### Meta checkpoint: concrete compatibility findings

Meta's [constants](https://github.com/facebookresearch/generic-neuromotor-interface/blob/b6bf250e2be5a67b23488104335373cdb87a15c9/generic_neuromotor_interface/constants.py)
specify **16 channels at 2000 Hz**. Its nine outputs are index press/release,
middle press/release and five thumb actions, with **no explicit finger-snap
class**. A thumb click must not be silently treated as a snap. The local band
supplies eight channels at 2048 Hz. Resampling alone cannot recreate missing
electrode measurements or the research hardware's electrode geometry/scaling.
Duplicating eight channels into sixteen is not validated model adaptation.

The [network implementation](https://github.com/facebookresearch/generic-neuromotor-interface/blob/b6bf250e2be5a67b23488104335373cdb87a15c9/generic_neuromotor_interface/networks.py)
uses a 21-sample, stride-10 convolution, 512 channels and a three-layer
512-unit LSTM. Its stride corresponds to 200 output frames/second at 2000 Hz,
not 50. Its wrist model also demonstrates multiband channel covariance and
rotation pooling; these are research candidates, not locally validated upgrades.

The [gesture data configuration](https://github.com/facebookresearch/generic-neuromotor-interface/blob/b6bf250e2be5a67b23488104335373cdb87a15c9/config/data_module/discrete_gestures_data_module.yaml)
uses 40 ms targets 80–120 ms after known events and circular electrode rotation
augmentation. Electrode-placement rotation is different from rotating the hand
or forearm continuously. It does not establish wrist-orientation invariance.
We cannot generate Meta-style exact event targets from our Spacebar intervals
without reviewing actual event times; weak clip supervision remains appropriate.

Downloaded the official 77,834,240-byte discrete-gesture checkpoint archive from
[Meta's endpoint](https://fb-ctrl-oss.s3.amazonaws.com/neuromotor-data/checkpoints/discrete_gestures/discrete_gestures.tar)
and inspected its YAML configuration. SHA-256:
`4f8913eda7871b22bcd7479acc526238bb787a94554484e50f2f13dd6a31279f`.
The reference sources and archive remain under ignored `.local/research/metaband/`.
A `torch.load(weights_only=True)` inspection rejected an embedded custom network
class; unrestricted deserialization was not used. No checkpoint inference or
local accuracy result is claimed. Meta's repository specifies CC-BY-NC-4.0;
emg2pose specifies CC-BY-NC-SA-4.0. These research releases are not unconditionally
available for incorporation into a commercial game.

## Signal processing actually run on Micah's data

`scripts/analyze_micah_patterns.py` implements this exploratory comparison:

1. Rebuild sample time from the native band clock and robust lower-envelope
   mapping to Kinesis host receipts. Python/file delivery lag is not action time.
   Record gaps and reset filtering at each gap; synthesize no missing samples.
   Absolute Bluetooth latency remains uncalibrated, with a documented ~7.3 ms
   uncertainty in within-batch timestamp convention.
2. Subtract ADC midpoint; apply causal 20–450 Hz bandpass and 60 Hz notch.
   These cutoffs are a local baseline choice, not a claim of Meta optimization.
   Reset settling samples are omitted from analysis windows only, not raw data.
3. Form 400-sample (195.3 ms) windows with 100-sample (48.8 ms) hops. Compute
   global RMS, amplitude-normalized eight-channel RMS profile, channel RMS/MAV/
   mean waveform length, relative power in three bands, short-subwindow
   variability and rising/falling activity. Compare feature families separately.
4. Fit shrinkage LDA and ExtraTrees as interpretable baselines. Keep original
   intervals together across folds; balance classes and interval contributions
   so a long hold does not masquerade as many independent trials. Also train on
   dynamic and evaluate on static, then reverse. Neither direction is a
   separate wearing-session test: both recordings have the same wearing ID.
5. Track each hold's amplitude in five-second bins and compare its first,
   middle and last third. Preserve effort drift instead of assigning a new
   strength label from amplitude. Compare full-window labels and a 0.5-second
   interior sensitivity subset; neither supplies verified physical onsets.

[LibEMG feature documentation](https://libemg.github.io/libemg/documentation/features/features.html)
also covers zero crossings, slope changes, autoregressive coefficients,
time-domain power spectral descriptors and wavelets. These are reasonable
additional candidates if they improve held-out performance. They were not all
run here, and adding more features is not evidence of better detection.

## What the findings change

The accompanying static `analysis/REPORT.md` and `pattern-report.json` show
that normalized channel shape transfers better than amplitude alone for shield
versus sword. Strength and pose should be separate outputs. Low sword approaches
the quiet floor; high/medium shield amplitudes overlap. No fixed amplitude
threshold reliably represents all three requested effort levels. A short
high-shield trial has an unusual profile and remains a review item, not an
automatically discarded or relabeled example.

The intent gate is not reliable enough across conditions to suppress actions
in production. A gate can learn tension or collection behavior instead of
purpose. Independently evaluate its missed-snap cost before enabling it. The
methodology pyramid remains the development order; completion of collection
does not mean its first-stage detector has passed validation.

For snaps, the existing dynamic review supplies normalized short-burst matching
and an unchanged-label review queue. The static capture has no snaps and cannot
validate them. A small causal temporal CNN/GRU remains a candidate trained on
our eight-channel signals, with separate snap and held-state objectives. Evaluate
against isolated soft/firm snaps, variable orientation, wrist-only motion,
pinches, finger movements and grip transitions. Positive clip labels support
weak event learning; negative windows and reviewed event timing are needed to
measure false events/minute, precision, recall and detection latency.

Before transition tuning, collect repeated relaxed-open hand baselines (distinct
from tensed shield), grip transitions, and snap-to-open trials. Only then estimate
the maximum snap-to-open deadline. Keep the spell state machine and Quest spatial
checks separate from EMG classification. No minimum opening delay is introduced.

For stronger evidence, interleave several repetitions of every pose/effort
condition rather than one long block each. Then reserve a new recording after
removing and replacing the band. Do not promote whichever model wins this
exploratory comparison without that evaluation.
