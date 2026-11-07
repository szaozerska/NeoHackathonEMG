# Kinesis Axo hackathon setup — build 6.28

This download is the Apple Silicon Mac app, requiring macOS 14 or later. Intel Macs, Windows, and iPhone cannot run this binary. You do not need Xcode, special drivers, or an ESP board to connect a band and use the Mac app. Python 3 is optional for the supplied stream example.

The repository and its published releases are public. Participants can download the assets without a GitHub account or invitation. The app is experimental and ad-hoc signed, rather than Developer ID signed or Apple-notarized. macOS may require manual approval on first launch; follow [Apple's instructions for opening downloaded apps](https://support.apple.com/102445). Bluetooth and Accessibility approval are separate from opening the app.

## Install and pair

1. Download `Kinesis-0.5.0-build6.28-arm64-local.zip`, unzip it, and move `Kinesis.app` into Applications. Quit an older Kinesis copy before replacing it, then launch the Applications copy. Keep a working band pairing when updating; forgetting or resetting a band is not an app-update step.
2. Allow Bluetooth when prompted. To use assigned gestures for Mac keyboard and mouse actions, enable Kinesis under **System Settings → Privacy & Security → Accessibility**. Reading the local sensor feed does not require this Accessibility permission, and Mac controls can remain paused.
3. Ask the organizer which band is assigned to you. Keep it near the Mac and hold its button for about three seconds, releasing when the light flashes white rapidly. Verify the band name in Kinesis, then choose **Pair band**.
4. Complete Meta sign-in directly in Meta's window, and accept macOS's Bluetooth pairing request. Initial enrollment requires internet and a Meta account. If the band belongs to another Meta account, ask the organizer to resolve its ownership before continuing; forgetting it in Kinesis alone does not release Meta ownership. Do not share passwords, verification codes, or pairing keys with other participants.
5. On **band**, select the wrist you are wearing it on and wait for confirmation. Wear the band snugly with good skin contact. Enable controls if you want Mac actions, then test the assignments shown in Kinesis.

After successful enrollment, Kinesis saves this Mac's pairing identity in Keychain and reconnects without a fresh sign-in. A different Mac needs its own initial pairing. The download contains no organizer account, pairing key, saved chat destination, recordings, calibration, or personal gesture profile. Participant settings stay on their own Mac.

## Read the live sensor stream

The **stream** tab is available without Developer mode. It provides raw eight-channel EMG, gyro, orientation, and decoded band gestures through one read-only local HTTP feed. Your code reads Kinesis's existing connection, so it does not enroll or pair with the band separately.

1. Connect the band, open **stream**, and enable **local sensor feed**. Wait for EMG to become active. Mac gesture controls can remain paused, and you do not need to keep the readings graphs open.
2. Select **copy stream URL**. Keep this link local; its temporary token authorizes reading the feed. The feed starts off on every Kinesis launch, and stopping and starting it generates a new link.
3. Download and unzip `sensor-stream-examples.zip` from the same release. In Terminal, open the extracted folder containing `read-sensor-stream.py`, then run:

   ```sh
   python3 read-sensor-stream.py --url 'COPIED_URL' --seconds 10
   ```

   Replace `COPIED_URL` with the complete link copied from Kinesis, keeping the quotes. The reader needs Python 3 and no third-party packages. It prints event counts and EMG samples per channel, without printing sensor values. To deliberately save received events instead, add `--jsonl > samples.jsonl`.

Browser projects can use `EventSource` with named listeners for `emg`, `gyro`, `orientation`, and `gesture`. Serve the page from `http://localhost` or `http://127.0.0.1`; a `file://` page or remote website is refused. The feed is available only on the same Mac. The examples archive includes the full sensor-stream guide with the event schema and browser example; source users can also read [the API guide](sensor-stream.md).

EMG values are unsigned ADC counts, not calibrated voltage. A supported batch contains 16 rows of eight channels at a configured 2,048 samples per second per channel. Gyro values are raw counts with an estimated physical scale. Host receipt time and band sample time use different clocks; preserve both timestamps and start a new alignment window after the reported band connection ID changes. Decoded gesture messages can include synthetic flags and duplicate descriptions of a physical contact. Slow readers are disconnected, and missed samples are not replayed, so retain batch sequences when building training windows.

## EMG graphs and handwriting

Enable **Developer mode** on **band** to show these experimental pages. On **readings**, enable **Live EMG** for graphs. On **write**, enable **Handwriting**, wait for the ready prompt, and write on a desk or another surface with the band hand's index finger. Stop handwriting and let normal-mode restoration finish before changing activities. Start the sensor feed before a model operation or wait until that operation finishes; feed activation is blocked while the band model is busy. Test EMG and handwriting separately first, because sustained simultaneous operation under load has not been verified for this release.

Participants choose their own gesture mappings. ChatGPT dictation additionally requires their own ChatGPT app/account and matching shortcut settings. Band firmware updates are an organizer preparation step, not part of installing Kinesis. The separate **phone** page requires a supported ESP32 adapter and an awake Mac; this release does not contain a standalone iPhone controller.

## Verify and get help

`SHA256SUMS` lists SHA-256 hashes for the supplied assets. The app executable hash is `0dc3c740cabbf527a3c189aabadb1fdd9b5c5d2dd5d1034849ba204cb7b6557a`. In the folder containing the downloaded assets, verify them with `shasum -a 256 -c SHA256SUMS`.

If connection setup fails, keep the band nearby, close other connections to it, and retry the pairing flow. If the organizer has factory-reset a band and macOS retains its old Bluetooth bond, remove that old band entry in Bluetooth Settings before pairing again. Do not reset a working pairing merely to update Kinesis. A replacement local app build can require fresh Keychain or Accessibility approval; complete those prompts directly in macOS.

Kinesis is based on [callbacked/kinesis](https://github.com/callbacked/kinesis). Its MIT notice is included in `LICENSE` and inside the app. Bundled artwork retains its separate notices.
