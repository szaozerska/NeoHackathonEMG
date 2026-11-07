import AppKit
import Foundation
import Testing
import KinesisCore
@testable import Kinesis

@MainActor private final class AirMouseTestClock {
    var now = 100.0
}

/// Gesture actions use fake Bluetooth, Mac controls, preferences and session
/// storage. Manual cursor frames avoid touching the display or moving a pointer.
@MainActor private final class AirMouseActionRig {
    let connection = RecordedConnection()
    let controls = RecordingControls()
    private let clock = AirMouseTestClock()
    let model: BandModel
    private var sequence: UInt64 = 0

    init(confirmHand: Bool = true) {
        let defaults = MemoryDefaults()
        defaults.set(true, forKey: "setupCompleted")
        let clock = clock
        model = BandModel(defaults: defaults, connection: connection, controls: controls,
                          sessionStore: SavedSessionStore(), clock: { clock.now },
                          cursorPacing: 0, cursorFrames: .manual)
        model.selectedAddress = "air-mouse-test-band"
        model.connect()
        connection.send(.connected, at: clock.now)
        connection.send(.heartbeat, at: clock.now)
        if confirmHand { connection.send(.handedness(.right), at: clock.now) }
        model.toggleControls()
    }

    func advance(_ seconds: Double) { clock.now += seconds }

    func gesture(_ finger: String, _ action: String, derived: String = "unknown") {
        clock.now += 0.01
        sequence += 1
        connection.send(.gesture(BandGesture(sequence: sequence, timestampUs: sequence * 10_000,
                                             finger: finger, action: action, derivedAction: derived, receivedAt: clock.now)),
                        at: clock.now)
    }
}

@MainActor private func waitForAirMouseOff(_ model: BandModel) async throws {
    var turns = 0
    while model.airCursorEnabled && turns < 100 {
        try await Task.sleep(for: .milliseconds(10))
        turns += 1
    }
    #expect(!model.airCursorEnabled)
}

@Test(arguments: [false, true]) @MainActor
func airMouseDisablingCancelsAPendingSwitchWithoutLaterClick(reenable: Bool) async throws {
    let rig = AirMouseActionRig()
    let model = rig.model
    model.tapMappings[.indexDoubleTap] = .toggleAirCursor
    model.setAirCursorEnabled(true)
    #expect(model.airCursorEnabled && !model.developerMode)

    // This pinch would become a mouse-down after 350 ms if the pending switch
    // were allowed to survive Escape or a manual off action.
    rig.gesture("index", "press")
    #expect(rig.controls.buttonEvents.isEmpty)
    model.setAirCursorEnabled(false)
    if reenable { model.setAirCursorEnabled(true) }
    try await Task.sleep(for: .milliseconds(450))

    #expect(model.airCursorEnabled == reenable)
    #expect(rig.controls.buttonEvents.isEmpty)
    #expect(rig.controls.clicks.isEmpty)
    await model.shutdown()
}

@Test @MainActor
func airMouseDoubleTapSwitchWorksForEachAssignedFinger() async throws {
    let rig = AirMouseActionRig()
    let model = rig.model
    model.tapMappings[.indexDoubleTap] = .toggleAirCursor
    model.tapMappings[.middleDoubleTap] = .toggleAirCursor
    // Exercise both fingers against the same dictionary so a lookup that only
    // considers its first matching entry cannot pass by a lucky hash order.
    for finger in ["index", "middle"] {
        model.setAirCursorEnabled(true)
        #expect(model.airCursorEnabled && !model.developerMode)
        rig.gesture(finger, "press")
        rig.gesture(finger, "release")
        rig.gesture(finger, "press")
        #expect(!model.airCursorEnabled)
        rig.gesture(finger, "release")
        // The band reports the classified gesture after the raw pinches. Both
        // forms belong to the switch just completed, not to another toggle.
        rig.gesture(finger, "doubletap")
        #expect(!model.airCursorEnabled)
        rig.gesture(finger, "unknown", derived: "doubleTap")
        #expect(!model.airCursorEnabled)
        try await Task.sleep(for: .milliseconds(450))

        // Suppression must expire: a later deliberate gesture can start the
        // mouse again, including the index finger's existing dial cooldown.
        rig.advance(1.2)
        rig.gesture(finger, "doubletap")
        #expect(model.airCursorEnabled)
        model.setAirCursorEnabled(false)
    }

    #expect(rig.controls.buttonEvents.isEmpty)
    #expect(rig.controls.actions.isEmpty)
    await model.shutdown()
}

@Test @MainActor
func airMouseMiddleHoldSwitchIgnoresItsClassifiedTailAndAllowsANewHold() async throws {
    let rig = AirMouseActionRig()
    let model = rig.model
    model.tapMappings[.middleHold] = .toggleAirCursor
    model.setAirCursorEnabled(true)
    rig.gesture("middle", "press")
    rig.advance(0.4)
    try await waitForAirMouseOff(model)

    rig.gesture("middle", "unknown", derived: "buttonHold")
    #expect(!model.airCursorEnabled)
    rig.gesture("middle", "release")
    rig.gesture("middle", "hold")
    #expect(!model.airCursorEnabled)
    #expect(rig.controls.buttonEvents.isEmpty)

    // A fresh contact and later classification are a genuinely new gesture.
    rig.advance(1.2)
    rig.gesture("middle", "press")
    rig.advance(0.4)
    rig.gesture("middle", "unknown", derived: "buttonHold")
    #expect(model.airCursorEnabled)
    rig.gesture("middle", "release")
    #expect(rig.controls.buttonEvents.isEmpty && rig.controls.actions.isEmpty)
    await model.shutdown()
}

@Test @MainActor
func airMouseManualOffIgnoresAPendingHoldClassificationWithoutBlockingTheNextHold() async throws {
    let rig = AirMouseActionRig()
    let model = rig.model
    model.tapMappings[.middleHold] = .toggleAirCursor
    model.setAirCursorEnabled(true)
    rig.gesture("middle", "press")
    model.setAirCursorEnabled(false)
    rig.advance(0.4)
    try await Task.sleep(for: .milliseconds(450))

    rig.gesture("middle", "unknown", derived: "buttonHold")
    #expect(!model.airCursorEnabled)
    rig.gesture("middle", "release")
    rig.gesture("middle", "hold")
    #expect(!model.airCursorEnabled)
    #expect(rig.controls.buttonEvents.isEmpty)

    rig.advance(1.2)
    rig.gesture("middle", "press")
    rig.advance(0.4)
    rig.gesture("middle", "unknown", derived: "buttonHold")
    #expect(model.airCursorEnabled)
    rig.gesture("middle", "release")
    #expect(rig.controls.buttonEvents.isEmpty && rig.controls.actions.isEmpty)
    await model.shutdown()
}

private enum AirMouseStartBlock: CaseIterable {
    case paused, permissionRevoked, unconfirmedHand
}

@Test(arguments: AirMouseStartBlock.allCases) @MainActor
private func airMouseActionRequiresControlsPermissionAndConfirmedHand(block: AirMouseStartBlock) async {
    let rig = AirMouseActionRig(confirmHand: block != .unconfirmedHand)
    let model = rig.model
    model.mappings[.left] = .toggleAirCursor
    switch block {
    case .paused: model.pause()
    case .permissionRevoked: rig.controls.trusted = false
    case .unconfirmedHand: break
    }

    rig.gesture("thumb", "left")
    #expect(!model.airCursorEnabled)
    #expect(rig.controls.actions.isEmpty && rig.controls.buttonEvents.isEmpty)
    await model.shutdown()
}
