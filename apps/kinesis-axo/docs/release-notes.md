# local 0.5.0, build 6.28

adds a stream page and opt-in local sensor API. Python and local browser projects can subscribe to timestamped JSON Server-Sent Events for complete raw EMG batches, gyro, orientation, and the band's decoded gesture messages. The API reads directly from the existing connection before action filtering or display throttling; it needs no recording files or helper process. EMG units remain unsigned ADC counts and gyro calibration is explicitly estimated.

the copyable URL uses a fresh access token each time the feed starts and accepts only local connections. each subscriber receives current status/configuration followed by new observations, with an anonymous connection ID to distinguish band reconnects. queues and subscriber counts are bounded; slow readers are disconnected without delaying band controls. stopping the feed releases only its own EMG request. subscription changes made during handwriting/model operations are deferred safely, including when a connection drops before restoration.

97 focused Swift tests and five Python reader fixtures passed. The new stream page was rendered and visually checked in light and dark mode at the minimum window size. Installed build 6.28 reconnected to band 00W8. A separate local browser received 1,184 EMG batches (18,944 samples per channel), 1,187 gyro events, and 1,158 orientation events during a ten-second counts-only check. No gesture occurred within that check window; gesture serialization and delivery were covered by the focused tests. Accessibility approval and enabled Mac controls were restored afterward.

# local 0.5.0, build 6.27

adds a phone page with an independent gesture profile. Kinesis forwards classified band gestures over USB to the Axo ESP32 adapter while the iPhone remains its Bluetooth keyboard/mouse host. Mac gesture actions pause in the phone profile; phone input does not require Mac Accessibility access. Connection changes, sleep, pausing, and handwriting operations cancel pending phone input and require manual re-enabling.

scroll swipes produce a fixed-distance easing trajectory with adjustable distance and direction. each new swipe replaces unfinished movement without accumulating momentum. the minimum is one wheel unit, dispatched on the first normal timer tick; the maximum remains 120. stalled work is discarded. four explicit pointer buttons place the iPhone cursor over a scrollable article or conversation. arming and scrolling never reposition the pointer automatically. the current adapter firmware advertises USB protocol 3 and supports bounded pointer movement plus a fixed primary-button click while retaining existing keyboard/wheel packet bytes and pairing data. clicks always include a serialized neutral release, including failure cleanup; uncertain clicks are never replayed.

ChatGPT prompting uses a separately configured iPhone F13 shortcut, with a one-shot setup button and an explicit tested-shortcut confirmation. click pointer can stop recording when positioned over ChatGPT’s Stop/checkmark control. a separate Return action sends the reviewed transcription. starting dictation does not automatically send a message. keyboard actions retain their release settling interval; wheel and pointer movement proceed after acknowledgement. local diagnostics distinguish scheduled movement from accepted wheel packets without logging sensor data or raw serial output. the Mac must remain connected and awake.

73 phone regression tests passed with warnings treated as errors, alongside the earlier 37 Mac control regressions. The wearer confirmed that the iPhone shortcut starts dictation, a primary-button gesture stops it and preserves the transcription, and Return sends the reviewed test text. The live profile uses middle hold for start, middle double tap for pointer click/stop, and index double tap for send. The scroll-distance control supports a one-unit minimum.

# local 0.5.0, build 6.22

handwriting settings and configuration reads now share one generic control service. live EMG uses that service as well, rather than opening a separate configuration service. EMG changes cannot interrupt a model operation. model failures name the failed step, and matched service rejections start restoration immediately instead of waiting for a timeout.

54 focused regression tests passed across legacy and modern encryption profiles. on updated band 005M, live EMG configured at 2,048 Hz and delivered samples, and the wearer confirmed correct handwriting text in Kinesis. normal-mode restoration and enabled Mac controls were verified afterward. simultaneous EMG and handwriting under sustained load was not verified.

# local 0.5.0, build 6.20

opens the input channel advertised by the band on each connection, rather than requiring channel 255. after its software update, band 005M advertised channel 129, which the old check rejected before enrollment could begin. the parser accepts only a two-byte little-endian value in the Bluetooth LE dynamic range and retains support for legacy channel 255.

supports the newer band's verified AirShield scheme 26, including its key derivation, authenticated packet prefix, full-block padding and tagged service channels. a peer that offers 27 may reply with 26 or 27 while the app continues to send its verified Enable 26. the peer-27 reply was checked against a live authenticated response from updated band 005M. legacy scheme 3 retains its original packet bytes; mismatched keys, unknown schemes and unauthenticated packets remain rejected.

# local 0.5.0, build 6.17

uses Axo's bundled teal-and-white mark for the macOS app icon.

finds handwriting controls by their exact names instead of assuming the same setting numbers on every firmware. bounded discovery stops for missing, ambiguous or incomplete control descriptions. the band's original typed values are checked before changing its model, and restoration uses the discovered controls and verified readback.

handwriting failures identify the operation that failed. diagnostic logs describe only response field numbers and wire types, without raw payloads, setting values or text.

reads bounded model identifiers from the existing device-info reply. optional or malformed metadata cannot interrupt the normal connection. the new band advertised gesture and wake models but no handwriting model; a band software update must be checked before the alternative handwriting API can be validated.

44 focused handwriting tests passed. on the new band, live discovery found controls 19/20, but reading the model selector returned a different value representation from the supported enum schema. handwriting remains unavailable on that firmware; the app refuses the unsupported operation before changing model settings.

# local 0.5.0, build 6.13

fixes Meta sign-in pop-ups by preserving WebKit's supplied configuration and relationship to the opening page. sign-in windows handle validated return links directly and close when sign-in completes or is cancelled.

rediscovers an unclaimed band before enrollment and after Meta sign-in, so a changed Bluetooth identifier does not leave setup waiting on the old identifier. discovery stays targeted to the remembered band, preserves the saved Meta session, and stops if the target is absent or ambiguous. existing pairing keys are reused when available.

sign-in failures identify the exchange, HTTP status and validated numeric error codes without exposing response bodies, credentials or contact information. the sanitized failure remains visible after closing sign-in. retry starts a fresh session, and cancelled attempts cannot save a session later.

109 focused tests passed, followed by all seven rediscovery tests after the final recovery-message adjustment. live Meta sign-in, new-band enrollment, saved-key reconnect, motion input, gesture reception and Accessibility approval were verified on macOS.

# local 0.5.0, build 6.8

adds Axo Neurotech's original mark and shared brand palette across the sidebar, setup, navigation, controls, hand feedback and sensor plots. light mode uses snow and sage; dark mode uses teal and mint with rose alerts. branding is bundled and static, with no network requests or new animation timers. gesture mappings and connection behavior are unchanged.

# local 0.5.0, build 6.7

adds per-gesture custom keyboard shortcuts, configurable macOS/ChatGPT Dictation, a saved dot-chat destination, and a separate **Send in ChatGPT** action. Dictation and Send have independent shortcuts; Send only acts while ChatGPT is in front and remains an explicit user gesture. shortcuts and chat destinations are local preferences, not bundled account data.

also improves stalled-subscription recovery and air-mouse switching. provisional single taps wait when a double tap or hold has its own assignment, and duplicate raw/classified contact reports cannot immediately undo a completed air-mouse off gesture.

63 focused tests passed with fake connections, input adapters and session stores. live dictation into the selected dot chat was user-verified. the separate Send action has isolated coverage; no automated live message was submitted. the packaged app is the tested Apple Silicon build with a local ad-hoc signature, without Apple notarization.

`scripts/build.sh --local` supports rebuilding on the current Mac with Command Line Tools. `scripts/package-local.sh` archives the built app plus allowlisted sources without rebuilding, re-signing, or including recordings, preferences, pairing material or account sessions.

# kinesis 0.5.0

adds experimental handwriting. write on any surface with your band hand, and kinesis types it into the text field you're in. assign "handwriting on / off" to a gesture to start and stop it. you can find it in dev mode.

also fixes high cpu use while live EMG is on.
