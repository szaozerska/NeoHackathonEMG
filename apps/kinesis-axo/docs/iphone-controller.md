# iPhone scrolling and ChatGPT prompts

The intended first version uses the Neural Band to scroll and open voice input in ChatGPT on an iPhone Air. It does not require handwriting or a newly trained EMG decoder: it consumes the band's existing classified gestures.

## USB forwarding with Kinesis

The Mac-assisted version is implemented in local build 6.27. The band stays paired to the Mac. Kinesis forwards its classified gestures over USB UART to the ESP32, which stays paired to the iPhone as a Bluetooth keyboard/mouse. The Mac must remain awake and connected. This does not require an iPhone companion or band re-enrollment.

1. Install the USB-forwarding firmware on the previously identified classic ESP32. An application-only update with the same partition layout preserves NVS and its Bluetooth bonds. Do not flash this image to an S3/C6. Pair the phone using the existing local setup only if it has not been paired already.
2. Close Arduino Serial Monitor. In Kinesis's **phone** page, choose the adapter's USB port and select **connect USB**. The page reports whether the iPhone is authenticated and subscribed to keyboard/mouse reports. Enable AssistiveTouch and Full Keyboard Access on the iPhone. To keep the onscreen keyboard available while this accessory is connected, turn on **Settings → Accessibility → Touch → AssistiveTouch → Show Onscreen Keyboard**, then tap the message field. The adapter presents a hardware keyboard, so the software keyboard may otherwise be hidden.
3. Connect the band to Kinesis, confirm its wrist, and select **enable phone controls**. Use the four **scroll target** arrows to place the iPhone pointer over the article or conversation. The arrows send bounded relative movement without clicking; arming and scrolling never move the pointer automatically. After clicking Stop or Send, move the pointer back over the message/article body before scrolling. A pointer over the keyboard, composer, or toolbar does not target the conversation’s scroll area. This pauses Mac gesture actions without changing their saved assignments. Phone controls can work without Mac Accessibility access. After a band, USB, phone, or sleep transition, explicitly enable them again.
4. Default thumb swipes up/down scroll with easing; left/right move keyboard focus backward/forward. Index double tap sends the configured ChatGPT F13 trigger once setup is confirmed. Middle tap activates the focused item after double-tap arbitration; middle double tap stops scrolling, including pending tap actions. All assignments are editable in the phone page.
5. Adjust **scroll distance** (1–120 wheel units, default 48) and **reverse scroll direction** for the iPhone app. Each swipe starts the configured fixed-distance easing trajectory and replaces unfinished movement; repeated swipes do not accumulate momentum. One-unit scrolling responds on the first normal timer tick. The descriptor sends integer wheel units rather than pixels, so distance and perceived smoothness depend on iOS and the target app. A host stall over 150 milliseconds discards remaining movement.

For ChatGPT, first save and manually run **Open your dot → Dictation** in the iPhone's Shortcuts app. In **Settings → Accessibility → Keyboards & Typing → Full Keyboard Access → Commands**, look for the saved shortcut and assign F13 if it is listed. With the iPhone recording the shortcut key, press Kinesis's **send F13 to iPhone for setup** button. This sends one momentary F13 and returns to disarmed operation. After verifying that F13 opens dictation, turn on **I tested F13…** in Kinesis. The phone's saved-shortcut binding must be validated on the actual handset; Apple documents customizable commands but does not establish every saved-shortcut entry.

The tested iPhone shortcut starts dictation but does not stop it when invoked again. For recording control, position the pointer over ChatGPT’s Stop/checkmark button using the arrows and assign **Click pointer** to another gesture. A suggested layout is middle hold for F13/start, middle double tap for Click pointer/stop, and index double tap for Return/send. Wait for transcription and review the text before sending. **test click** emits one primary-button click at the current pointer position, with a release; it does not reposition the pointer. No Mac Command-6 shortcut or timed stop-and-submit macro is assumed. No message is automatically sent by the Dictation action.

Live checks confirmed classified keyboard navigation and USB wheel-command acceptance. The iPhone pointer was parked at the top-left corner, so the interface now provides explicit target positioning; wheel input needs a scrollable area under the pointer. The firmware accepts versioned bounded commands, acknowledges acceptance, and retains its independent release/watchdog checks. Kinesis never sends PAIR, prints pairing codes, or retries an uncertain input action. Acceptance confirms the adapter consumed a command, not that the iPhone app executed it. See the [firmware guide](../firmware/axo-phone-bridge/README.md) for local setup and protocol details.

## Standalone design, not yet implemented

The standalone design to validate is:

```text
Neural Band → iPhone companion → Bluetooth command → ESP32 adapter
                                                      ↓
                             iPhone ← Bluetooth mouse/keyboard input
```

The adapter presents a real Bluetooth keyboard and mouse. The companion communicates with a custom service on that same accessory; iOS handles its input service. USB supplies power and programming, rather than phone input. This particular combination of system HID and companion access on the same phone connection must be tested on the device.

The connected board was identified by a read-only ROM query as an original ESP32-D0WD-V3 revision 3.1 with 4 MB flash, using a CP210x USB-to-serial port. It was initially described as an S3, but it requires an original-ESP32 build. Bluetooth HID avoids needing a native USB socket or additional USB wiring. Recheck the actual chip before flashing if the board is swapped.

## First controls

The initial operations are bounded mouse-wheel movement, explicit bounded pointer movement, and a momentary keyboard chord. Pointer movement never clicks; wheel reports keep X/Y and buttons at zero. Every keyboard press is followed by an all-keys-released report. Output starts disarmed, and a new connection requires a new armed session. Gesture assignments belong to a separate phone profile; the current Mac assignments are not defaults for the phone. F13 and F14 are available as configurable shortcut triggers, with no predefined action on the phone.

ChatGPT documents an **Open your dot** Shortcuts action with Messaging, Dictation, and Call modes. Dictation is the intended prompt entry point when the action is available on the user's account. The phone must first demonstrate that a physical keyboard binding can launch the saved shortcut; the published Apple Full Keyboard Access guide does not establish that particular Shortcuts binding. Do not substitute the Mac's Command-6 shortcut or assume that rerunning the iPhone action stops dictation. Stopping dictation and sending a reviewed prompt need handset tests before receiving gesture mappings.

## Validation gates

1. Build for the detected ESP32 chip. After reviewing and authorizing replacement of the board's current program, install the firmware and complete authenticated Bluetooth pairing directly on the phone. Enable AssistiveTouch for the mouse path and Full Keyboard Access for keyboard navigation. Use the board's local serial test controls to verify one wheel step and one configured chord. Verify that the phone scrolls, releases all keys, and can open the intended Dictation shortcut before connecting band gestures.
2. Build the native companion using full Xcode and the iOS SDK. Reuse the existing Swift band session and enrollment code, with phone-specific lifecycle, sign-in presentation, and saved identity handling. A fresh phone enrollment can replace the band's Mac ownership, so it must be a deliberate migration after the adapter test rather than an automatic launch action.
3. Verify classified gestures while ChatGPT is in front, then after switching apps, reconnecting, and locking/unlocking. Core Bluetooth background support does not prove that this band's L2CAP stream will continue under those conditions. If it cannot, the standalone design must move band reception to the adapter or another always-running host.

The current Mac has Command Line Tools but no full Xcode/iOS SDK. Shared Swift report generation and input gating passed their focused tests, and the adapter firmware was built and installed after preserving the board's original flash. The adapter starts disarmed. An iPhone companion build and standalone end-to-end band control remain unverified; no phone enrollment has been performed. USB-forwarded phone input is tested separately from this standalone design.

`PhoneBridgeCheck` is a developer check for the custom command service, built with `swift build --product PhoneBridgeCheck`. Its `--help` path does not initialize Bluetooth. Its `status` command sends no input; `scroll` and `key` deliberately arm and send one input action before disarming. The Mac becomes the Bluetooth input host for those checks. It cannot command a different iPhone while that phone owns the adapter's single connection. Initial phone validation instead uses the board's local serial controls while the phone is the paired Bluetooth host.

## Primary references

- [Apple: iPhone Air specifications](https://www.apple.com/iphone-air/specs/).
- [Apple: external pointer devices and AssistiveTouch](https://support.apple.com/en-us/111775).
- [Apple: Full Keyboard Access](https://support.apple.com/en-ie/guide/iphone/ipha4375873f/26/ios/26).
- [OpenAI: iOS shortcuts for your dot](https://learn.chatgpt.com/docs/dots/channels).
- [Espressif: USB device support](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/usb.html) and [keyboard/mouse example](https://github.com/espressif/esp-idf/tree/master/examples/peripherals/usb/device/tusb_hid).
- [Nordic: nRF52840 features](https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/keyfeatures_html5.html) and [nRF Desktop reference](https://nrfconnectdocs.nordicsemi.com/ncs/latest/nrf/applications/nrf_desktop/description.html).
- [Apple: Core Bluetooth](https://developer.apple.com/documentation/corebluetooth).
