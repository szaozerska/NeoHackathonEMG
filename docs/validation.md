# Software validation

This file records software checks, not a device-accuracy claim.

- Python tests exercise raw Kinesis protobuf decoding, SSE multiline parsing/layout, missing-sequence handling, causal feature equivalence across packet boundaries, gaps, annotation validation and split isolation, spell ordering/hold/release, snap deduplication, stale input, tracking reacquisition, TCP handshake/time sync, and dashboard annotation persistence.
- A four-session synthetic CLI demo trains both EMG detectors, calibrates Quest thresholds, and evaluates a separate synthetic session. Its fixture includes shield, sword and fireball sequences. Synthetic recognition scores must not be presented as measured hardware accuracy.
- The portable Unity sender is compiled against the Unity 6000.6.8f1 engine references with `scripts/check_unity_core.py`. The full Unity project also imported and compiled successfully against Meta Core 207.0.1 and the pinned Movement 207.0.0 commit. An Android/device check is still required.
- The local HTTP API is exercised in tests. A browser visual check depends on the host browser connection being available.

Physical checks still required: Kinesis source/build compatibility and buffering latency; band placement changes; Quest body tracking permission and left-hip visibility; calibrated palm convention; fast-movement tracking; physical-action timing labels; actual spell event precision/recall on independently donned sessions.

Verified in this workspace: 18 Python tests passed; the synthetic four-session pipeline produced all three expected spell sequences with no duplicate events in its fixture; NPZ/Quest export completed; full Unity package import and all four SpellTraining assemblies compiled; the scene builder generated `SpellRecorder.unity` and Android XR loader settings. Android Build Support was absent, so no APK/device validation was run. The browser host was unavailable, so dashboard verification used the HTTP tests and JavaScript syntax check rather than a visual browser review.
