import Foundation
import Testing
import KinesisCore
@testable import Kinesis

@MainActor
private final class PhoneUSBEndToEndClock {
    var now = 100.0
}

/// Models only the adapter's serial framing, session/sequence acceptance, and
/// asynchronous status replies. It never opens a device or posts real input.
@MainActor
private final class PhoneUSBEndToEndFirmware: PhoneUSBSerialPort {
    struct Accepted {
        let opcode: UInt8
        let sequence: UInt16
        let argument: UInt8
        let secondArgument: UInt8
    }
    private let clock: PhoneUSBEndToEndClock
    private var line = Data()
    private var replies: [(due: Double, bytes: Data)] = []
    private var sequence: UInt16 = 0
    private var armed = false
    private let session: UInt32 = 0x12345678
    private(set) var accepted: [Accepted] = []
    private(set) var closed = false
    var statusRepliesEnabled = true

    init(clock: PhoneUSBEndToEndClock) { self.clock = clock }

    var wheelUnits: [Int] {
        accepted.filter { $0.opcode == 5 }.map { Int(Int8(bitPattern: $0.argument)) }
    }

    var pointerMoves: [(dx: Int, dy: Int)] {
        accepted.filter { $0.opcode == 6 }.map {
            (Int(Int8(bitPattern: $0.argument)), Int(Int8(bitPattern: $0.secondArgument)))
        }
    }

    func reopen() {
        closed = false
        line.removeAll()
        replies.removeAll()
    }

    func readAvailable() throws -> Data {
        guard !closed else { throw CocoaError(.fileReadUnknown) }
        let due = replies.prefix { $0.due <= clock.now }
        let bytes = due.reduce(into: Data()) { $0.append($1.bytes) }
        replies.removeFirst(due.count)
        return bytes
    }

    func write(_ data: Data) throws -> Int {
        guard !closed else { throw CocoaError(.fileWriteUnknown) }
        for byte in data {
            if byte == 10 {
                acceptLine(String(decoding: line, as: UTF8.self))
                line.removeAll(keepingCapacity: true)
            } else {
                line.append(byte)
            }
        }
        return data.count
    }

    func close() { closed = true }

    private func acceptLine(_ text: String) {
        if text == "HELLO" { scheduleStatus(); return }
        guard text.hasPrefix("USB ") else { return }
        let hex = Array(text.dropFirst(4).utf8)
        guard hex.count == 24 else { return }
        var bytes = [UInt8]()
        for offset in stride(from: 0, to: hex.count, by: 2) {
            guard let value = UInt8(String(decoding: hex[offset...offset + 1], as: UTF8.self), radix: 16) else { return }
            bytes.append(value)
        }
        let commandSequence = UInt16(bytes[2]) | UInt16(bytes[3]) << 8
        let commandSession = UInt32(bytes[4]) | UInt32(bytes[5]) << 8
            | UInt32(bytes[6]) << 16 | UInt32(bytes[7]) << 24
        guard bytes[0] == 1, bytes[10] == 0, bytes[11] == 0,
              commandSession == session, commandSequence > sequence else { return }
        sequence = commandSequence
        switch bytes[1] {
        case 1: armed = true
        case 2: armed = false
        case 3: guard armed else { return }
        case 4, 5, 6: guard armed else { return }
        case 7: guard armed, bytes[8] == 0, bytes[9] == 0 else { return }
        default: return
        }
        accepted.append(Accepted(opcode: bytes[1], sequence: sequence,
            argument: bytes[8], secondArgument: bytes[9]))
        scheduleStatus()
    }

    private func scheduleStatus() {
        guard statusRepliesEnabled else { return }
        let bytes: [UInt8] = [1, armed ? 1 : 0,
            UInt8(truncatingIfNeeded: sequence), UInt8(truncatingIfNeeded: sequence >> 8),
            UInt8(truncatingIfNeeded: session), UInt8(truncatingIfNeeded: session >> 8),
            UInt8(truncatingIfNeeded: session >> 16), UInt8(truncatingIfNeeded: session >> 24),
            1, 1, 0, 0]
        let reply = "AXOUSB 3 " + bytes.map { String(format: "%02x", $0) }.joined() + "\n"
        // The status is read on a later bridge tick, as on the physical UART.
        replies.append((clock.now + 0.001, Data(reply.utf8)))
    }
}

@MainActor
private final class PhoneUSBEndToEndRig {
    let clock = PhoneUSBEndToEndClock()
    let firmware: PhoneUSBEndToEndFirmware
    let bridge: PhoneUSBBridge
    let phone: PhoneController
    private var ticks = 0
    private var gestureSequence: UInt64 = 0

    init() {
        let clock = clock
        let firmware = PhoneUSBEndToEndFirmware(clock: clock)
        self.firmware = firmware
        let bridge = PhoneUSBBridge(enumeratePorts: { ["/dev/cu.usbtest"] }, openPort: { _ in
            firmware.reopen()
            return firmware
        }, clock: { clock.now }, automaticallyTicks: false)
        self.bridge = bridge
        phone = PhoneController(defaults: MemoryDefaults(), bridge: bridge,
            clock: { clock.now }, automaticallyTicks: false)
        phone.refreshPorts()
        phone.connect()
        advance(0.1)
    }

    func advance(_ seconds: Double, controllerTicks: Bool = true) {
        let count = Int((seconds / 0.01).rounded())
        for _ in 0..<count {
            clock.now += 0.01
            ticks += 1
            bridge.tick()
            if controllerTicks, ticks.isMultiple(of: 2) { phone.tick() }
        }
    }

    func enable() {
        phone.enable()
        advance(0.1)
    }

    @discardableResult
    func swipe(_ direction: String) -> RecognizedGesture? {
        gesture(direction, finger: "thumb")
    }

    @discardableResult
    func gesture(_ action: String, finger: String, derivedAction: String = "unknown") -> RecognizedGesture? {
        gestureSequence += 1
        return phone.receive(BandGesture(sequence: gestureSequence, timestampUs: gestureSequence,
            finger: finger, action: action, derivedAction: derivedAction, receivedAt: clock.now), at: clock.now)
    }
}

@Suite("Phone controller through USB serial", .serialized)
@MainActor
struct PhoneUSBEndToEndTests {
    @Test func recognizedSwipeWritesFullWheelTrajectoryAndHeartbeatThroughRealBridge() {
        let rig = PhoneUSBEndToEndRig()
        #expect(rig.bridge.connected && rig.bridge.ready)
        rig.enable()
        #expect(rig.phone.enabled && rig.bridge.armed)
        rig.advance(0.5)
        #expect(rig.firmware.accepted.contains { $0.opcode == 3 })
        #expect(rig.swipe("down") == .swipe(.down))
        #expect(rig.phone.lastAction == "Scroll down")
        rig.advance(1.3)
        #expect(rig.firmware.wheelUnits.reduce(0, +) == -48)
        #expect(rig.firmware.wheelUnits.count >= 8)
        #expect(rig.firmware.wheelUnits.allSatisfy { (-8 ... -1).contains($0) })
        #expect(rig.firmware.accepted.filter { $0.opcode == 3 }.count >= 2)
        #expect(rig.bridge.connected && rig.bridge.armed && rig.phone.enabled)
        let sequences = rig.firmware.accepted.map(\.sequence)
        #expect(zip(sequences, sequences.dropFirst()).allSatisfy { $0 < $1 })
        rig.phone.disconnect()
    }

    @Test func pauseDuringTrajectoryWritesDisarmAndClearsRemainingWheelInput() {
        let rig = PhoneUSBEndToEndRig()
        rig.enable()
        rig.swipe("down")
        rig.advance(0.12)
        // Drain any command already accepted by the transport before pausing.
        rig.bridge.tick()
        let beforePause = rig.firmware.wheelUnits
        #expect(!beforePause.isEmpty && abs(beforePause.reduce(0, +)) < 48)
        rig.phone.pause()
        rig.advance(0.8)
        #expect(rig.firmware.wheelUnits == beforePause)
        #expect(rig.firmware.accepted.last?.opcode == 2)
        #expect(!rig.phone.enabled && !rig.bridge.armed)
        rig.phone.disconnect()
    }

    @Test func reconnectDiscardsMomentumAndRequiresExplicitRearmBeforeFreshSwipe() {
        let rig = PhoneUSBEndToEndRig()
        rig.enable()
        rig.swipe("down")
        rig.advance(0.12)
        rig.bridge.tick()
        rig.phone.disconnect()
        let beforeReconnect = rig.firmware.wheelUnits
        rig.phone.connect()
        rig.advance(0.5)
        #expect(rig.bridge.ready && !rig.bridge.armed && !rig.phone.enabled)
        rig.swipe("up")
        rig.advance(0.8)
        #expect(rig.firmware.wheelUnits == beforeReconnect)
        rig.enable()
        #expect(rig.phone.enabled)
        rig.swipe("up")
        rig.advance(1.1)
        let afterRearm = Array(rig.firmware.wheelUnits.dropFirst(beforeReconnect.count))
        #expect(afterRearm.reduce(0, +) == 48)
        #expect(afterRearm.allSatisfy { (1...8).contains($0) })
        rig.phone.disconnect()
    }

    @Test func delayedFirstControllerTickCancelsSwipeWithoutWritingStaleWheelInput() {
        let rig = PhoneUSBEndToEndRig()
        rig.enable()
        rig.swipe("down")
        // Keep serial status/heartbeats healthy while the UI motion loop stalls.
        rig.advance(0.2, controllerTicks: false)
        rig.phone.tick()
        rig.advance(0.8)
        #expect(rig.firmware.wheelUnits.isEmpty)
        #expect(rig.phone.lastAction == "Scroll down")
        #expect(rig.phone.enabled && rig.bridge.armed)
        // Cancellation does not disable the profile; a fresh swipe can work.
        rig.swipe("up")
        rig.advance(1.1)
        #expect(rig.firmware.wheelUnits.reduce(0, +) == 48)
        rig.phone.disconnect()
    }

    @Test func pointerButtonRequiresArmedControlsAndWritesOneBoundedMoveWithoutQueuingBusyPress() {
        let rig = PhoneUSBEndToEndRig()
        rig.phone.movePointer(horizontal: 32, vertical: 0)
        rig.advance(0.1)
        #expect(rig.firmware.pointerMoves.isEmpty)
        rig.enable()
        rig.phone.movePointer(horizontal: 0, vertical: 0)
        rig.phone.movePointer(horizontal: 128, vertical: 0)
        rig.phone.movePointer(horizontal: 32, vertical: -32)
        // This second press is deliberately not queued while the first awaits ACK.
        rig.phone.movePointer(horizontal: -32, vertical: 0)
        rig.advance(0.3)
        #expect(rig.firmware.pointerMoves.count == 1)
        #expect(rig.firmware.pointerMoves.first?.dx == 32)
        #expect(rig.firmware.pointerMoves.first?.dy == -32)
        #expect(!rig.firmware.accepted.contains { $0.opcode == 4 || $0.opcode == 5 })
        rig.phone.pause()
        rig.phone.movePointer(horizontal: 0, vertical: 32)
        rig.advance(0.3)
        #expect(rig.firmware.pointerMoves.count == 1)
        rig.phone.disconnect()
    }

    @Test func pointerButtonCancelsWheelMomentumAndDeferredTapBeforeMoving() {
        let rig = PhoneUSBEndToEndRig()
        rig.phone.bindings["tap.indexTap"] = .scrollDown
        rig.enable()
        rig.swipe("down")
        rig.advance(0.08)
        rig.gesture("tap", finger: "index")
        // Let the outstanding wheel ACK arrive without scheduling another wheel.
        rig.advance(0.03, controllerTicks: false)
        #expect(!rig.bridge.busy)
        let wheelsBeforeMove = rig.firmware.wheelUnits
        #expect(!wheelsBeforeMove.isEmpty)
        rig.phone.movePointer(horizontal: 0, vertical: 32)
        rig.advance(0.8)
        #expect(rig.firmware.pointerMoves.count == 1)
        #expect(rig.firmware.pointerMoves.first?.dx == 0)
        #expect(rig.firmware.pointerMoves.first?.dy == 32)
        #expect(rig.firmware.wheelUnits == wheelsBeforeMove)
        #expect(rig.phone.enabled && rig.bridge.armed)
        rig.phone.disconnect()
    }

    @Test func pointerClickRequiresArmedControlsClearsPendingInputAndDoesNotQueueBusyClicks() {
        let rig = PhoneUSBEndToEndRig()
        rig.phone.testPointerClick()
        rig.advance(0.1)
        #expect(!rig.firmware.accepted.contains { $0.opcode == 7 })
        rig.phone.bindings["tap.indexTap"] = .scrollDown
        rig.enable()
        rig.swipe("down")
        rig.advance(0.08)
        rig.gesture("tap", finger: "index")
        rig.advance(0.03, controllerTicks: false)
        #expect(!rig.bridge.busy)
        let wheelsBeforeClick = rig.firmware.wheelUnits
        #expect(!wheelsBeforeClick.isEmpty)
        rig.phone.testPointerClick()
        rig.phone.testPointerClick()
        rig.advance(0.8)
        let clicks = rig.firmware.accepted.filter { $0.opcode == 7 }
        #expect(clicks.count == 1)
        #expect(clicks.first?.argument == 0 && clicks.first?.secondArgument == 0)
        #expect(rig.firmware.wheelUnits == wheelsBeforeClick)
        #expect(!rig.firmware.accepted.contains { $0.opcode == 4 })
        rig.phone.pause()
        rig.phone.testPointerClick()
        rig.advance(0.3)
        #expect(rig.firmware.accepted.filter { $0.opcode == 7 }.count == 1)
        rig.phone.disconnect()
    }

    @Test func unacknowledgedPointerClickIsNeverRetriedAndDisconnects() {
        let rig = PhoneUSBEndToEndRig()
        rig.enable()
        rig.firmware.statusRepliesEnabled = false
        rig.phone.testPointerClick()
        rig.advance(0.8)
        #expect(rig.firmware.accepted.filter { $0.opcode == 7 }.count == 1)
        #expect(!rig.bridge.connected && !rig.bridge.armed && !rig.phone.enabled)
        rig.phone.testPointerClick()
        rig.advance(0.3)
        #expect(rig.firmware.accepted.filter { $0.opcode == 7 }.count == 1)
        rig.phone.disconnect()
    }

    @Test func mappedMiddleDoubleTapWritesOneClickAndSuppressesItsClassifiedDuplicate() {
        let rig = PhoneUSBEndToEndRig()
        rig.phone.bindings["tap.middleDoubleTap"] = .clickPointer
        rig.enable()
        #expect(rig.gesture("doubletap", finger: "middle") == .tap(.middleDoubleTap))
        rig.advance(0.02)
        #expect(rig.gesture("unknown", finger: "middle", derivedAction: "doubleTap") == nil)
        rig.advance(0.5)
        #expect(rig.firmware.accepted.filter { $0.opcode == 7 }.count == 1)
        #expect(!rig.firmware.accepted.contains { [UInt8(4), 5, 6].contains($0.opcode) })
        rig.phone.disconnect()
    }
}
