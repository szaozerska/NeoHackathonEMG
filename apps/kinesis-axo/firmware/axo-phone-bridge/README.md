# Axo phone bridge for ESP32

This experimental firmware presents a Bluetooth HID keyboard and relative mouse to an iPhone. It accepts bounded navigation commands over USB serial from Kinesis on a Mac, while the iPhone owns the Bluetooth input connection. A custom service on that same Bluetooth connection also supports developer checks and a future iPhone companion. The firmware does not connect to the Neural Band itself. USB supplies power and serial commands; native USB HID, wiring changes, and a board-specific button are not required.

The initial target is the connected **ESP32-D0WD-V3, 4 MB flash**, using the bundled Bluedroid BLE stack in Arduino-ESP32 **3.3.11**. A remembered board name is insufficient to select a flash target; this target came from the chip's ROM identification. Do not flash this classic-ESP32 build onto an ESP32-S3/C6. No flash/upload script is provided.

```sh
arduino-cli compile --fqbn 'esp32:esp32:esp32:PartitionScheme=no_fs' firmware/axo-phone-bridge
c++ -std=c++17 -Wall -Wextra -Werror firmware/axo-phone-bridge/tests/protocol_test.cpp -o /tmp/axo-phone-protocol-test
/tmp/axo-phone-protocol-test
c++ -std=c++17 -Wall -Wextra -Werror firmware/axo-phone-bridge/tests/serial_test.cpp -o /tmp/axo-phone-serial-test
/tmp/axo-phone-serial-test
```

Compile success proves API compatibility, not pairing, successful phone input, or correct board upload settings. Preserve the board's existing flash contents before any separately authorized upload.

## Pair the iPhone and test the hardware

Keep the board attached to the Mac for power. Open its Serial Monitor at 115200 and enter `PAIR` followed by Enter. This explicit local command disconnects the current peer and replaces only this ESP32’s previous Bluetooth pairings and their cached notification subscriptions. It waits until those bond removals have completed, generates a fresh passkey, and opens enrollment for 120 seconds. It does not erase NVS, reset the Neural Band, or change Kinesis’s band pairing. In the iPhone's Bluetooth settings, pair **Axo Phone Bridge** and enter the displayed code in the system dialog. Do not paste that code into chat. Successful authenticated bonding closes the window.

The new passkey and bonds persist across reboot; this firmware never erases NVS or logs identity keys. Input remains unprovisioned until a fresh authenticated pairing in this setup window succeeds and the bridge saves its own provisioning marker. Previous firmware’s Bluetooth bonds cannot authorize the first setup. Normal startup does not print the passkey. Keep the Arduino Core Debug Level at None because the vendor BLE implementation can independently print security diagnostics when debugging is enabled. An unrecognized peer may establish a BLE link, but input remains blocked until encrypted, authenticated, bonded pairing completes; passkey negotiation outside the local enrollment window is rejected. Saved bonds can re-encrypt without displaying a new passkey.

Enable the iPhone's Full Keyboard Access for focus navigation and, if needed for mouse/wheel input, AssistiveTouch. The actual iPhone HID subscriptions and behavior must be checked on the phone; successfully pairing alone does not prove navigation works.

The keyboard/mouse profile can hide the iPhone's software keyboard. Turn on **Settings → Accessibility → Touch → AssistiveTouch → Show Onscreen Keyboard** to keep it available, then tap the message field. For wheel input, position the mouse over the scrollable content rather than its keyboard, composer, or toolbar; clicking a dictation control does not return the pointer to the conversation. [Apple's keyboard/pointer instructions](https://support.apple.com/en-us/111775).

For one local test, enter `ARM` in Serial Monitor, then one of these commands within 30 seconds:

| Command | Single test action |
|---|---|
| `TAB` | Press and release Tab to move keyboard focus |
| `UP` | One upward wheel step |
| `DOWN` | One downward wheel step |
| `F13` | Press and release F13, for an explicitly configured phone shortcut |
| `NUDGE` | Move the pointer 16 relative units right and down once, without clicking |
| `DISARM` | Stop input immediately |

Each test consumes that local authorization and disarms after completion. The firmware requires notification subscriptions for both reports before declaring output ready; the phone may need its accessibility features enabled. No text, PIN entry, arbitrary keyboard input, or held state is available through this console.

`NUDGE` is a bounded mouse-enumeration diagnostic when scrolling is accepted but no pointer appears. Enter `ARM`, then `NUDGE` while watching the phone. Its single five-byte report is `[0, 16, 16, 0, 0]`: no buttons, no wheel, and no held state. It uses the same serialized transmission, timeout, and disarm path as the other manual tests. Its internal command value is rejected by the public USB/BLE decoder. The HID descriptor and saved Bluetooth pairing remain unchanged.

Wheel input must also target scrollable content. If the visible pointer is over Safari's toolbar or a corner, use Kinesis's bounded pointer-positioning arrows to move it into the article before scrolling. Positioning sends one relative mouse report `[0, x, y, 0, 0]`, with each axis between -127 and 127 and at least one nonzero axis. It uses the same explicit arming, session/sequence/freshness checks, and serialized transmission path. It never clicks, holds a button, starts scrolling, or extends the current wheel burst. Moving an onscreen pointer is separate from synthesizing touchscreen gestures.

An explicit pointer-click action sends one primary/left-button report `[1, 0, 0, 0, 0]`, followed by a serialized all-buttons-released report `[0, 0, 0, 0, 0]`. It does not move the pointer. The target is whichever control the phone currently shows under the pointer; this provides a physical click rather than relying on keyboard focus. The release obligation is recorded before submitting the press, and all subsequent input waits until the neutral report completes. An uncertain press is never retried; the existing timeout/disconnect path retains neutral cleanup for reconnection. No held-button or arbitrary-button operation is exposed.

Arming and scrolling send no automatic pointer movement. Wheel reports always contain zero buttons, zero X/Y, and the requested relative wheel values. Nonzero X/Y is emitted only by an explicit public pointer-move command or the manually armed `NUDGE` diagnostic. The firmware has no pointer-wake sequence, deferred-wheel slot, or automatic cursor repositioning. All commands retain the original queue deadline, single-transmission gate, release handling, and no-retry behavior.

Only one BLE central is admitted. During phone input the phone owns that connection, so the Mac forwards commands through USB serial instead of Bluetooth. Close Serial Monitor before connecting Kinesis to the serial port. The pointer-click app requires this firmware's `AXOUSB 3` handshake; older serial/manual-test firmware does not advertise that capability. Updating this firmware does not change the HID descriptor or erase the saved pairing/provisioning state, so an already-paired iPhone can reconnect without another `PAIR` command. A planned standalone iPhone app would use the custom service alongside iOS's HID connection. Whether that shared access and its background behavior work on the actual iPhone remains a separate device-test requirement.

## USB serial envelope, version 3

The serial port runs at 115200 baud, 8-N-1, with newline-delimited ASCII. `HELLO` requests a status reply. The adapter also publishes status changes, coalescing replies when UART output is busy:

```text
AXOUSB 3 <24 lowercase hexadecimal characters>\n
```

The hexadecimal payload remains the same version-1 twelve-byte status packet described below. Envelope version 3 advertises bounded pointer movement and momentary primary-button clicks, so an app requiring those features rejects older firmware before enabling input. Existing command opcodes 1...6 retain their binary layout and behavior; opcode 7 adds a fixed click. Status contains a connection-local session nonce, readiness, accepted sequence, and state; it never includes a Bluetooth passkey or identity key. Normal setup/debug text is outside this framing and must not be displayed or logged by the forwarding client. In particular, first-time enrollment stays in the physical Serial Monitor and system Bluetooth pairing dialog.

To send a command, encode the same twelve-byte packet used by the BLE protocol:

```text
USB <24 hexadecimal characters>\n
```

USB commands pass through the same queue, current-session and strictly increasing sequence checks, explicit arming, 150 ms queue deadline, authenticated iPhone link, HID readiness, serialized report/release path, and 1.5-second idle watchdog as BLE commands. A status acceptance confirms firmware acceptance rather than phone delivery. Do not retry an uncertain input command; disconnect or inspect fresh status instead. A physical USB connection provides access to this console; it does not replace the iPhone's authenticated Bluetooth pairing. No USB command automatically opens pairing, changes bonds, or rearms after a connection boundary.

The parser rejects malformed hexadecimal packets, invalid protocol fields, nonprintable input, and oversized lines. Serial work is bounded per firmware loop so a busy sender cannot starve HID completion or watchdog processing. Manual `PAIR`, `ARM`, `TAB`, `UP`, `DOWN`, `F13`, and `DISARM` commands retain their original behavior; `NUDGE` adds the explicit pointer diagnostic described above. `UP` and `DOWN` remain deliberately single-step hardware tests; smooth scrolling is generated by the host as a bounded sequence of wheel packets.

## BLE protocol, version 1

Service: `A10A0001-5D53-4A18-8F6A-1C173E442001`. Command characteristic: `A10A0002-5D53-4A18-8F6A-1C173E442001`, writes with response requiring encryption and MITM authentication. Status characteristic: `A10A0003-5D53-4A18-8F6A-1C173E442001`, authenticated encrypted read/notify. Reading status can trigger the OS pairing flow. Authentication completion changes the session, so read fresh status afterward before arming. The session nonce is a replay boundary, not an authentication secret; BLE authenticated bonding provides access control.

Every command is exactly 12 bytes: version `1`, opcode, unsigned 16-bit sequence (little endian), unsigned 32-bit session (little endian), two argument bytes, and two zero reserved bytes. Sequence and session must be nonzero. Sequences strictly increase within a session; reconnect before sequence 65535 is exhausted. Retransmitting old commands does not repeat their actions.

| Opcode | Meaning | Arguments |
|---|---|---|
| 1 | Arm | Both zero |
| 2 | Disarm | Both zero |
| 3 | Heartbeat | Both zero |
| 4 | Momentary navigation key | Keyboard/Keypad usage; HID modifier byte |
| 5 | Relative wheel | Signed vertical and horizontal steps, each −127…127; at least one nonzero |
| 6 | Relative pointer positioning, no click | Signed x and y steps, each −127…127; at least one nonzero |
| 7 | Momentary primary/left pointer click | Both zero; no movement, held state, or arbitrary button mask |

Allowed keyboard usages are Enter `28`, Escape `29`, Tab `2b`, Space `2c`, Home `4a`, Page Up `4b`, End `4d`, Page Down `4e`, arrows `4f`…`52`, and F13/F14 `68`/`69` as explicit user-configured shortcut triggers (hexadecimal). HID modifier bits select the left-hand keys: Control=1, Shift=2, Alt/Option=4, GUI/Command=8. The API accepts no text, letter keys, arbitrary reports, mouse-button holds, or key holds. Space can activate the focused item when assigned that function in Full Keyboard Access; this is not direct touchscreen injection. Scroll direction and navigation depend on iPhone settings.

Status is 12 bytes: version, state (`0` disarmed, `1` armed), last accepted sequence, current session, reason byte, output-ready flag (`0`/`1`), and two zero reserved bytes. Integer byte order matches commands. Protocol acceptance is **not confirmation that the iPhone executed an action**. Reasons are defined in `AxoPhoneProtocol.h`; clients should tolerate future reason values. Output ready means authenticated HID subscriptions, supported report protocol, no HID suspend, and no reported congestion; it is not a promise that a phone action succeeded.

The queue holds at most eight commands and rejects work older than 150 milliseconds. BLE reconnection, authentication changes, HID subscription/readiness changes, HID suspend, malformed input, or queue overflow disarms output and changes the session. A 1.5-second command/heartbeat idle timeout also disarms output. No boundary automatically rearms it. Send heartbeats more frequently than that only while controls are intentionally enabled.

Keyboard and pointer-button presses use separate serialized neutral-release transmissions. The pending release is set before attempting a press and is cleared only after the successful ESP-IDF transmit-completion callback for the sole in-flight report, matching its interface, connection, and characteristic. Actual Bluedroid success callbacks omit the payload despite the header documentation, so payload matching is not used. The callback is a stack/transmit result, **not a GATT peer acknowledgement**: HID uses notifications. Any submission failure, transmit failure, or completion timeout leaves neutral release pending and disconnects the link; the ambiguous slot is never reused on that live connection. A new connection must complete neutral cleanup before another action is allowed. Relative wheel movements and uncertain clicks are never retried after ambiguous failure. A disconnected phone cannot receive a release; reconnection requires neutral reports and explicit rearming.

`AxoPhoneReportMap.h` supplies standard keyboard (report-reference ID 1, eight-byte payload) and relative mouse (ID 2, five-byte payload) descriptors. BLE payloads do not prepend those IDs. Mouse buttons remain zero except for the fixed primary-button press of an explicit click. Wheel reports vary only the two wheel fields; explicit pointer-positioning and manual `NUDGE` reports vary only x and y. The device uses Axo branding and experimental Espressif-based metadata, without an Apple vendor identity.

## Verification boundary

The portable C++ fixtures check command bounds, key allowlisting, integer byte order, exact status bytes, USB framing, malformed/oversized line rejection, recovery at newline boundaries, bounded pointer reports, and fixed click acceptance with zero movement/arguments. Before real gestures are enabled, test phone pairing, Tab focus movement, activation, both scroll directions, pointer positioning over content, a click and release on the intended control, F13 only after assigning it, USB disconnect/reconnect, Bluetooth disconnect/reconnect, suspend/resume, heartbeat expiry, and interrupted key/button-output cleanup. The future iPhone application's direct band connection and simultaneous HID/custom-service access remain separate work; this firmware requires a host to receive and forward band gestures.
