import AppKit
import Foundation
import Testing
import KinesisCore
@testable import Kinesis

@MainActor private final class TapArbitrationControls: MacControls {
    var trusted = true
    private(set) var actions: [MacAction] = []
    private(set) var shortcuts: [KeyboardShortcut] = []
    private(set) var shortcutPostedAt: [ContinuousClock.Instant] = []
    var cursorLocation: CGPoint? { .zero }
    var displaySize: CGSize { CGSize(width: 1600, height: 1000) }

    func requestAccess() {}
    func post(_ action: MacAction) throws { actions.append(action) }
    func postShortcut(_ shortcut: KeyboardShortcut) throws {
        shortcuts.append(shortcut)
        shortcutPostedAt.append(ContinuousClock.now)
    }
    func moveCursor(to point: CGPoint, dragging button: CGMouseButton?) throws -> CGPoint { point }
    func mouseButton(_ button: CGMouseButton, down: Bool, clicks: Int, at point: CGPoint?) throws {}
}

@MainActor private final class TapArbitrationClock {
    var now = 100.0
}

/// Only synthetic events and fake adapters are used. The app never accesses
/// Bluetooth, real preferences/session storage, permissions or a display ticker.
@MainActor private final class TapArbitrationRig {
    let connection = RecordedConnection()
    let controls = TapArbitrationControls()
    private let clock = TapArbitrationClock()
    let model: BandModel
    private var sequence: UInt64 = 0

    init(configuredDictation: Bool = true) {
        let defaults = MemoryDefaults()
        defaults.set(true, forKey: "setupCompleted")
        let clock = clock
        model = BandModel(defaults: defaults, connection: connection, controls: controls,
                          workspaceNotifications: NotificationCenter(), sessionStore: SavedSessionStore(),
                          clock: { clock.now }, cursorPacing: 0, cursorFrames: .manual)
        model.selectedAddress = "tap-arbitration-test-band"
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
        clock.now += 1
    }

    func advance(_ seconds: Double) { clock.now += seconds }

    func middle(_ action: String = "unknown", derived: String = "unknown") {
        sequence += 1
        connection.send(.gesture(BandGesture(sequence: sequence,
                                             timestampUs: UInt64((clock.now - 100) * 1_000_000),
                                             finger: "middle", action: action,
                                             derivedAction: derived, receivedAt: clock.now)),
                        at: clock.now)
    }
}

@MainActor private func waitForDeferredTap(_ condition: () -> Bool) async throws {
    var turns = 0
    while !condition() && turns < 200 {
        try await Task.sleep(for: .milliseconds(5))
        turns += 1
    }
    #expect(condition())
}

@Test(arguments: [false, true]) @MainActor
func capturedDoubleTapCancelsItsSinglesAndStartsAirMouse(configuredDictation: Bool) async throws {
    let rig = TapArbitrationRig(configuredDictation: configuredDictation)
    // Relative host timing from an actual capture: the first single is followed
    // by a second pinch; its derived single and double share one callback/time.
    rig.middle(derived: "singleTap")
    #expect(rig.controls.shortcuts.isEmpty && rig.model.error == nil)
    rig.advance(0.1678)
    rig.middle("press")
    rig.advance(0.1241)
    rig.middle("release")
    rig.advance(0.0238)
    rig.middle(derived: "buttonRelease")
    rig.middle(derived: "singleTap")
    rig.middle(derived: "doubleTap")

    #expect(rig.model.airCursorEnabled)
    #expect(rig.controls.shortcuts.isEmpty && rig.controls.actions.isEmpty)
    #expect(rig.model.error == nil)
    // Let every queued single's timer pass while it is still inside the
    // callback freshness budget. Nothing may fire after entering mouse mode.
    rig.advance(0.4)
    try await Task.sleep(for: .milliseconds(450))
    #expect(rig.model.airCursorEnabled && rig.model.error == nil)
    #expect(rig.controls.shortcuts.isEmpty && rig.controls.actions.isEmpty)
    await rig.model.shutdown()
}

@Test @MainActor
func aLoneSingleTapDefersDictationUntilTheDoubleTapWindowEnds() async throws {
    let rig = TapArbitrationRig()
    let shortcut = try #require(rig.model.dictationShortcut)
    let started = ContinuousClock.now
    rig.middle(derived: "singleTap")
    #expect(rig.controls.shortcuts.isEmpty)

    rig.advance(0.4)
    try await waitForDeferredTap { !rig.controls.shortcuts.isEmpty }
    #expect(rig.controls.shortcuts == [shortcut])
    #expect(rig.controls.actions.isEmpty && !rig.model.airCursorEnabled)
    let postedAt = try #require(rig.controls.shortcutPostedAt.first)
    #expect(started.duration(to: postedAt) >= .milliseconds(350))
    try await Task.sleep(for: .milliseconds(50))
    #expect(rig.controls.shortcuts == [shortcut])
    await rig.model.shutdown()
}

@Test(arguments: [false, true]) @MainActor
func capturedAirMouseOffDoubleTapConsumesItsSingleAndDoubleTail(configuredDictation: Bool) async throws {
    let rig = TapArbitrationRig(configuredDictation: configuredDictation)
    rig.model.setAirCursorEnabled(true)
    #expect(rig.model.airCursorEnabled)

    rig.middle("press")
    rig.advance(0.1)
    rig.middle("release")
    rig.advance(0.1)
    rig.middle("press")
    #expect(!rig.model.airCursorEnabled)
    rig.advance(0.1)
    // The second release and both classifications arrive in one callback. The
    // single belongs to the same completed off gesture, so it cannot queue a
    // later Dictation action while the double's tail is being suppressed.
    rig.middle("release")
    rig.middle(derived: "buttonRelease")
    rig.middle(derived: "singleTap")
    rig.middle(derived: "doubleTap")
    #expect(!rig.model.airCursorEnabled && rig.model.error == nil)

    rig.advance(0.4)
    try await Task.sleep(for: .milliseconds(450))
    #expect(!rig.model.airCursorEnabled && rig.model.error == nil)
    #expect(rig.controls.shortcuts.isEmpty && rig.controls.actions.isEmpty)
    await rig.model.shutdown()
}

private enum DeferredTapCancellation: CaseIterable {
    case pause, disconnect, permissionLoss, enableAirMouse, remap
}

@Test(arguments: DeferredTapCancellation.allCases) @MainActor
private func deferredSingleCannotFireAfterItsControlContextChanges(change: DeferredTapCancellation) async throws {
    let rig = TapArbitrationRig()
    rig.middle(derived: "singleTap")
    #expect(rig.controls.shortcuts.isEmpty)
    rig.advance(0.2)
    switch change {
    case .pause: rig.model.pause()
    case .disconnect: rig.model.disconnect()
    case .permissionLoss: rig.controls.trusted = false
    case .enableAirMouse: rig.model.setAirCursorEnabled(true)
    case .remap: rig.model.tapMappings[.middleTap] = MacAction.none
    }
    rig.advance(0.2)
    try await Task.sleep(for: .milliseconds(450))

    #expect(rig.controls.shortcuts.isEmpty && rig.controls.actions.isEmpty)
    #expect(rig.model.error == nil)
    if change == .enableAirMouse { #expect(rig.model.airCursorEnabled) }
    await rig.model.shutdown()
}
