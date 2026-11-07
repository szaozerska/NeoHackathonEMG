import AppKit
import Foundation
import Testing
import KinesisCore
@testable import Kinesis

@MainActor private final class DuplicateContactControls: MacControls {
    var trusted = true
    private(set) var actions: [MacAction] = []
    private(set) var shortcuts: [KeyboardShortcut] = []
    private(set) var mouseEvents = 0
    var cursorLocation: CGPoint? { .zero }
    var displaySize: CGSize { CGSize(width: 1600, height: 1000) }

    func requestAccess() {}
    func post(_ action: MacAction) throws { actions.append(action) }
    func postShortcut(_ shortcut: KeyboardShortcut) throws { shortcuts.append(shortcut) }
    func moveCursor(to point: CGPoint, dragging button: CGMouseButton?) throws -> CGPoint { point }
    func mouseButton(_ button: CGMouseButton, down: Bool, clicks: Int, at point: CGPoint?) throws {
        mouseEvents += 1
    }
}

@MainActor private final class DuplicateContactClock {
    var now = 100.0
}

/// Raw and derived reports share a contact timestamp but keep distinct message
/// sequences. Every dependency is fake; no input is posted or device opened.
@MainActor private final class DuplicateContactRig {
    let connection = RecordedConnection()
    let controls = DuplicateContactControls()
    private let clock = DuplicateContactClock()
    let model: BandModel
    private var sequence: UInt64 = 0

    init(configuredDictation: Bool = true) {
        let defaults = MemoryDefaults()
        defaults.set(true, forKey: "setupCompleted")
        let clock = clock
        model = BandModel(defaults: defaults, connection: connection, controls: controls,
                          workspaceNotifications: NotificationCenter(), sessionStore: SavedSessionStore(),
                          clock: { clock.now }, cursorPacing: 0, cursorFrames: .manual)
        model.selectedAddress = "duplicate-contact-test-band"
        model.tapMappings[.middleTap] = .dictation
        model.tapMappings[.middleDoubleTap] = .toggleAirCursor
        if configuredDictation {
            model.dictationShortcut = KeyboardShortcut(keyCode: 2, modifiers: [.control, .option], keyLabel: "D")
        }
        model.connect()
        connection.send(.connected, at: clock.now)
        connection.send(.heartbeat, at: clock.now)
        connection.send(.handedness(.right), at: clock.now)
        model.toggleControls()
    }

    func advance(_ seconds: Double) { clock.now += seconds }

    func event(_ action: String = "unknown", derived: String = "unknown", timestampUs: UInt64) {
        sequence += 1
        connection.send(.gesture(BandGesture(sequence: sequence, timestampUs: timestampUs,
                                             finger: "middle", action: action, derivedAction: derived,
                                             receivedAt: clock.now)), at: clock.now)
    }

    func press(_ timestampUs: UInt64) {
        event("press", timestampUs: timestampUs)
        event(derived: "buttonPress", timestampUs: timestampUs)
    }

    func release(_ timestampUs: UInt64) {
        event("release", timestampUs: timestampUs)
        event(derived: "buttonRelease", timestampUs: timestampUs)
        event(derived: "singleTap", timestampUs: timestampUs)
    }

    /// Stops immediately after the second raw press. A test then controls the
    /// duplicate reports and release ordering that cross the ON→OFF boundary.
    @discardableResult
    func beginOffSwitch() -> UInt64 {
        model.setAirCursorEnabled(true)
        press(1_000_000)
        advance(0.14)
        release(1_140_000)
        advance(0.168)
        event("press", timestampUs: 1_308_000)
        return 1_308_000
    }

    func finishOffSwitch() {
        advance(0.14)
        release(1_448_000)
        event(derived: "doubleTap", timestampUs: 1_448_000)
    }

    /// A genuinely new gesture has new contact stamps, including all paired
    /// raw/derived edges and the provisional single classifications.
    func newDoubleTap() {
        press(2_000_000)
        advance(0.14)
        release(2_140_000)
        advance(0.168)
        press(2_308_000)
        advance(0.14)
        release(2_448_000)
        event(derived: "doubleTap", timestampUs: 2_448_000)
    }
}

@Test(arguments: [false, true]) @MainActor
func rawAndDerivedSecondPressCannotUndoAirMouseOff(configuredDictation: Bool) async throws {
    let rig = DuplicateContactRig(configuredDictation: configuredDictation)
    let secondPress = rig.beginOffSwitch()
    #expect(!rig.model.airCursorEnabled)
    // This is the paired report of the very press that switched the mouse
    // off, with the same host and device timestamp, not a new contact.
    rig.event(derived: "buttonPress", timestampUs: secondPress)
    #expect(!rig.model.airCursorEnabled)
    rig.finishOffSwitch()
    #expect(!rig.model.airCursorEnabled && rig.model.error == nil)

    rig.advance(0.4)
    try await Task.sleep(for: .milliseconds(450))
    #expect(!rig.model.airCursorEnabled && rig.model.error == nil)
    #expect(rig.controls.shortcuts.isEmpty && rig.controls.actions.isEmpty && rig.controls.mouseEvents == 0)

    // A fresh press after the release must clear completion immediately,
    // rather than suppressing future valid gestures for this finger.
    rig.newDoubleTap()
    #expect(rig.model.airCursorEnabled)
    #expect(rig.controls.shortcuts.isEmpty && rig.controls.mouseEvents == 0)
    await rig.model.shutdown()
}

@Test(arguments: [Int64(-31), 0, 31]) @MainActor
func aDelayedDuplicatePressAfterReleaseStillBelongsToTheCompletedSwitch(timestampOffsetUs: Int64) async throws {
    let rig = DuplicateContactRig()
    let secondPress = rig.beginOffSwitch()
    #expect(!rig.model.airCursorEnabled)
    rig.advance(0.14)
    rig.event("release", timestampUs: 1_448_000)
    rig.event(derived: "buttonRelease", timestampUs: 1_448_000)
    rig.advance(0.01)
    // Arrival order alone cannot identify a new contact: the device stamp
    // still names the consumed second press, even after a release arrived.
    // Actual raw/derived copies can differ by about 31 microseconds.
    rig.event(derived: "buttonPress", timestampUs: UInt64(Int64(secondPress) + timestampOffsetUs))
    rig.event(derived: "singleTap", timestampUs: 1_448_000)
    rig.event(derived: "doubleTap", timestampUs: 1_448_000)
    #expect(!rig.model.airCursorEnabled)

    rig.advance(0.4)
    try await Task.sleep(for: .milliseconds(450))
    #expect(!rig.model.airCursorEnabled && rig.model.error == nil)
    #expect(rig.controls.shortcuts.isEmpty && rig.controls.mouseEvents == 0)
    rig.newDoubleTap()
    #expect(rig.model.airCursorEnabled)
    await rig.model.shutdown()
}

@Test @MainActor
func aStaleReleaseCannotMakeAPairedPressLookLikeANewContact() async throws {
    let rig = DuplicateContactRig()
    let secondPress = rig.beginOffSwitch()
    #expect(!rig.model.airCursorEnabled)
    rig.advance(0.01)
    // This delayed release belongs to the first pinch, not the consumed
    // second press. Some real raw/derived pairs differ by about 30 microseconds.
    rig.event("release", timestampUs: 1_140_000)
    rig.event(derived: "buttonPress", timestampUs: secondPress + 30)
    rig.finishOffSwitch()
    #expect(!rig.model.airCursorEnabled)

    rig.advance(0.4)
    try await Task.sleep(for: .milliseconds(450))
    #expect(!rig.model.airCursorEnabled && rig.model.error == nil)
    #expect(rig.controls.shortcuts.isEmpty && rig.controls.mouseEvents == 0)
    await rig.model.shutdown()
}

@Test @MainActor
func aFreshContactRecoversFromALostSwitchReleaseAfterTheBoundedWait() async {
    let rig = DuplicateContactRig()
    rig.beginOffSwitch()
    #expect(!rig.model.airCursorEnabled)
    // No release is delivered. The completed contact cannot block a new
    // distinct contact forever when that one radio report was lost.
    rig.advance(0.8)
    rig.newDoubleTap()
    #expect(rig.model.airCursorEnabled && rig.model.error == nil)
    #expect(rig.controls.shortcuts.isEmpty && rig.controls.actions.isEmpty && rig.controls.mouseEvents == 0)
    await rig.model.shutdown()
}
