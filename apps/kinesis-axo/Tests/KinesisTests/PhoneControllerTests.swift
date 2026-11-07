import Foundation
import Testing
import KinesisCore
@testable import Kinesis

@MainActor private final class PhoneTestTransport: PhoneUSBTransport {
    var ports = ["/dev/cu.usbtest"]
    var selectedPort = ""
    var connected = false
    var ready = false
    var armed = false
    var busy = false
    var statusText = "test adapter"
    var onBoundary: (() -> Void)?
    var actions: [PhoneNavigationAction] = []
    var arms = 0
    func refreshPorts() {}
    func connect() { connected = true; ready = true; onBoundary?() }
    func disconnect() { connected = false; ready = false; armed = false; onBoundary?() }
    func arm() { guard !busy else { return }; arms += 1; armed = true }
    func disarm() { armed = false; onBoundary?() }
    func send(action: PhoneNavigationAction) -> Bool {
        guard armed, ready, !busy else { return false }
        actions.append(action)
        return true
    }
}

@MainActor private final class PhoneTestClock { var now = 100.0 }

@MainActor private final class PhoneRig {
    let defaults = MemoryDefaults()
    let transport = PhoneTestTransport()
    let clock = PhoneTestClock()
    let phone: PhoneController
    init() {
        let clock = clock
        phone = PhoneController(defaults: defaults, bridge: transport, clock: { clock.now }, automaticallyTicks: false)
        phone.refreshPorts()
        phone.connect()
    }
    func enable() {
        phone.enable()
        phone.tick()
        clock.now += 0.01
    }
    @discardableResult func gesture(_ action: String, finger: String = "thumb", derived: String = "unknown",
                                   at time: Double? = nil) -> RecognizedGesture? {
        phone.receive(BandGesture(sequence: UInt64(clock.now * 1_000_000), timestampUs: UInt64(clock.now * 1_000_000),
            finger: finger, action: action, derivedAction: derived, receivedAt: time ?? clock.now), at: clock.now)
    }
    func advance(_ seconds: Double) { clock.now += seconds; phone.tick() }
}

@Suite("Phone gesture profile", .serialized)
@MainActor struct PhoneControllerTests {
    @Test func phoneSwipeProducesEasedWheelReportsAndDeduplicatesClassifiedTail() {
        let rig = PhoneRig()
        rig.enable()
        rig.gesture("down")
        rig.clock.now += 0.02
        rig.gesture("unknown", derived: "buttonDown")
        for _ in 0..<40 { rig.advance(0.025) }
        let wheels = rig.transport.actions.compactMap { action -> Int? in
            if case .scroll(let value) = action { return Int(value.vertical) }; return nil
        }
        #expect(wheels.reduce(0, +) == -48)
        #expect(wheels.count > 12)
        #expect(wheels.allSatisfy { (-8 ... -1).contains($0) })
    }

    @Test func stalePausedAndPreArmGesturesNeverSend() {
        let rig = PhoneRig()
        rig.enable()
        rig.gesture("down", at: rig.clock.now - 1)
        rig.gesture("down", at: 99.99)
        rig.phone.pause()
        rig.gesture("down")
        for _ in 0..<20 { rig.advance(0.025) }
        #expect(rig.transport.actions.isEmpty)
    }

    @Test func connectionChangeCancelsMomentumAndDoesNotRearm() {
        let rig = PhoneRig()
        rig.enable()
        rig.gesture("down")
        rig.advance(0.025)
        let sent = rig.transport.actions.count
        rig.transport.armed = false
        rig.transport.onBoundary?()
        rig.transport.armed = true
        for _ in 0..<25 { rig.advance(0.025) }
        #expect(!rig.phone.enabled)
        #expect(rig.transport.actions.count == sent)
        #expect(rig.transport.arms == 1)
    }

    @Test func dictationRequiresConfirmationAndSendsOnlyOneF13() {
        let rig = PhoneRig()
        rig.enable()
        rig.gesture("doubletap", finger: "index")
        #expect(rig.transport.actions.isEmpty)
        rig.phone.dictationShortcutReady = true
        rig.clock.now += 1
        rig.gesture("doubletap", finger: "index")
        rig.clock.now += 0.02
        rig.gesture("unknown", finger: "index", derived: "doubleTap")
        #expect(rig.transport.actions == [.key(PhoneKeyboardChord(.f13))])
    }

    @Test func setupKeyWaitsForBusyDisarmAndDoesNotResumeGestureControls() {
        let rig = PhoneRig()
        rig.transport.busy = true
        rig.phone.sendDictationSetupKey()
        #expect(rig.transport.arms == 0)
        rig.advance(0.1)
        rig.transport.busy = false
        rig.advance(0.1)
        #expect(rig.transport.arms == 1)
        rig.advance(0.02)
        #expect(rig.transport.actions == [.key(PhoneKeyboardChord(.f13))])
        rig.advance(0.3)
        #expect(!rig.transport.armed && !rig.phone.enabled)
    }

    @Test func singleTapWaitsForDoubleTapAndHold() {
        let rig = PhoneRig()
        rig.phone.bindings["tap.indexTap"] = .nextItem
        rig.phone.bindings["tap.indexDoubleTap"] = .dismiss
        rig.enable()
        rig.gesture("tap", finger: "index")
        #expect(rig.transport.actions.isEmpty)
        rig.advance(0.2)
        rig.gesture("press", finger: "index")
        rig.gesture("doubletap", finger: "index")
        rig.advance(0.3)
        #expect(rig.transport.actions == [.key(PhoneKeyboardChord(.escape))])
    }

    @Test func stopGestureAlsoCancelsAnotherFingersPendingScroll() {
        let rig = PhoneRig()
        rig.phone.bindings["tap.indexTap"] = .scrollDown
        rig.enable()
        rig.gesture("tap", finger: "index")
        rig.advance(0.1)
        rig.gesture("doubletap", finger: "middle")
        for _ in 0..<25 { rig.advance(0.025) }
        #expect(rig.transport.actions.isEmpty)
    }

    @Test func profilePersistsPreferencesWithoutAutomaticallyEnablingOutput() {
        let rig = PhoneRig()
        rig.phone.scrollDistance = 72
        rig.phone.reverseScroll = true
        rig.phone.dictationShortcutReady = true
        rig.phone.bindings["swipe.left"] = .dismiss
        let reopened = PhoneController(defaults: rig.defaults, bridge: PhoneTestTransport(), automaticallyTicks: false)
        #expect(reopened.scrollDistance == 72 && reopened.reverseScroll && reopened.dictationShortcutReady)
        #expect(reopened.bindings["swipe.left"] == .dismiss)
        #expect(!reopened.selected && !reopened.enabled && !reopened.connected)
    }

    @Test func phoneProfileRoutesBandInputWithoutMacAccessibilityAndPreservesMacMappings() async {
        let rig = PhoneRig()
        let connection = RecordedConnection()
        let controls = RecordingControls()
        controls.trusted = false
        rig.defaults.set(true, forKey: "setupCompleted")
        let model = BandModel(defaults: rig.defaults, connection: connection, controls: controls,
            workspaceNotifications: NotificationCenter(), sessionStore: SavedSessionStore(),
            bandIdentityExists: { _ in true }, clock: { rig.clock.now }, cursorFrames: .manual, phone: rig.phone)
        model.mappings[.down] = .volumeUp
        model.selectedAddress = "phone-test-band"
        model.connect()
        connection.send(.connected, at: rig.clock.now)
        connection.send(.heartbeat, at: rig.clock.now)
        connection.send(.handedness(.right), at: rig.clock.now)
        model.enablePhoneControls()
        rig.phone.tick()
        rig.clock.now += 0.01
        connection.send(.gesture(BandGesture(sequence: 1, timestampUs: 1, finger: "thumb", action: "down",
            receivedAt: rig.clock.now)), at: rig.clock.now)
        for _ in 0..<35 { rig.advance(0.025) }
        #expect(!rig.transport.actions.isEmpty)
        #expect(controls.actions.isEmpty && !model.controlsEnabled)
        #expect(model.mappings[.down] == .volumeUp)
        model.disconnect()
        #expect(!rig.phone.enabled)
        #expect(rig.transport.armed == false)
        await model.shutdown()
    }
}
