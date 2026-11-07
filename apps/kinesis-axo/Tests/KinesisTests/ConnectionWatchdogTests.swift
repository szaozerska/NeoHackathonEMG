import Foundation
import Testing
import KinesisCore
@testable import Kinesis

@MainActor private final class WatchdogClock {
    var now = 100.0
}

@MainActor private final class WatchdogRig {
    let defaults = MemoryDefaults()
    let connection = RecordedConnection()
    let controls = RecordingControls()
    let clock = WatchdogClock()
    let model: BandModel

    init() {
        defaults.set(true, forKey: "setupCompleted")
        defaults.set("right", forKey: "bandHand")
        let clock = clock
        model = BandModel(defaults: defaults, connection: connection, controls: controls,
                          workspaceNotifications: NotificationCenter(), sessionStore: SavedSessionStore(),
                          clock: { clock.now })
        model.selectedAddress = "watchdog-test-band"
        model.connect()
    }

    func acknowledge() {
        connection.send(.connected, at: clock.now)
        connection.send(.heartbeat, at: clock.now)
    }

    /// Keep link status recent while crossing the ten-second sensor deadline.
    /// The final clock advance leaves the private 500 ms timer to detect it.
    func becomeSensorSilent() {
        clock.now += 9
        connection.send(.heartbeat, at: clock.now)
        clock.now += 2
    }
}

@MainActor private func waitForWatchdog(_ condition: () -> Bool) async throws {
    // Allow the 500 ms watchdog tick and two-second retry to run on the main
    // actor. Count yielded turns so an unrelated machine stall does not consume
    // the test's deadline before its scheduled work gets an opportunity to run.
    var turns = 0
    while !condition(), turns < 1000 {
        try await Task.sleep(for: .milliseconds(5))
        turns += 1
    }
    try #require(condition())
}

@Suite("Connection watchdog")
struct ConnectionWatchdogTests {
    @Test @MainActor func acknowledgedSubscriptionWithoutItsFirstSensorFrameReconnectsOnce() async throws {
        let rig = WatchdogRig()
        rig.acknowledge()
        #expect(rig.model.live)
        #expect(rig.model.gestureCount == 0)

        rig.becomeSensorSilent()
        try await waitForWatchdog { rig.connection.stops == 1 }
        #expect(!rig.model.live)
        try await waitForWatchdog { rig.connection.starts == 2 }
        #expect(rig.connection.requests == ["connect watchdog-test-band", "connect watchdog-test-band"])

        // A second acknowledged-but-silent stream must not spend another
        // recovery until sustained sensor data has replenished the budget.
        rig.acknowledge()
        rig.becomeSensorSilent()
        try await waitForWatchdog { rig.model.streamHint != nil }
        #expect(rig.connection.stops == 1 && rig.connection.starts == 2)
        #expect(rig.model.gestureCount == 0)
        await rig.model.shutdown()
    }

    @Test @MainActor func heartbeatBeforeSubscriptionAcknowledgementDoesNotHideFirstFrameSilence() async throws {
        let rig = WatchdogRig()
        rig.connection.send(.heartbeat, at: rig.clock.now)
        #expect(rig.model.live)
        rig.clock.now += 0.25
        rig.connection.send(.connected, at: rig.clock.now)

        rig.becomeSensorSilent()
        try await waitForWatchdog { rig.connection.stops == 1 }
        try await waitForWatchdog { rig.connection.starts == 2 }
        #expect(rig.connection.requests.last == "connect watchdog-test-band")
        #expect(rig.model.wantsConnection)
        await rig.model.shutdown()
    }

    @Test(arguments: [false, true])
    @MainActor func automaticRecoveryPreservesWristReadbackAndHonorsExplicitPause(pauseDuringRetry: Bool) async throws {
        let rig = WatchdogRig()
        rig.acknowledge()
        // A device readback overrides a stale saved illustration preference.
        rig.connection.send(.handedness(.left), at: rig.clock.now)
        rig.model.toggleControls()
        #expect(rig.model.controlsEnabled && rig.model.handConfirmed)
        #expect(rig.model.bandHand == .left)

        rig.becomeSensorSilent()
        try await waitForWatchdog { rig.connection.stops == 1 }
        #expect(!rig.model.live && !rig.model.handConfirmed)
        #expect(rig.model.controlsEnabled)
        if pauseDuringRetry { rig.model.pause() }
        try await waitForWatchdog { rig.connection.starts == 2 }

        rig.acknowledge()
        #expect(rig.model.bandHand == .left && !rig.model.handConfirmed)
        rig.connection.send(.handedness(.left), at: rig.clock.now)
        rig.connection.send(.dataSeen, at: rig.clock.now)
        #expect(rig.model.live && rig.model.handConfirmed)
        #expect(rig.model.controlsEnabled == !pauseDuringRetry)
        #expect(rig.model.bandHand == .left)
        #expect(rig.defaults.string(forKey: "bandHand") == "left")
        #expect(rig.connection.requestedHands.isEmpty)
        #expect(rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func chargingSubscriptionDoesNotReconnectForFirstFrameSilence() async throws {
        let rig = WatchdogRig()
        rig.acknowledge()
        rig.connection.send(.batteryStatus(BandBatteryStatus(level: 80, charging: true)), at: rig.clock.now)
        rig.becomeSensorSilent()

        // The quiet hint confirms that the timer examined the overdue stream;
        // charging should suppress recovery rather than hide its quiet state.
        try await waitForWatchdog { rig.model.streamHint != nil }
        #expect(rig.connection.stops == 0 && rig.connection.starts == 1)
        #expect(rig.model.live && rig.model.charging == true)
        await rig.model.shutdown()
    }

    @Test @MainActor func continuousMotionWithoutRecognizedGesturesKeepsTheConnection() async throws {
        let rig = WatchdogRig()
        rig.acknowledge()
        for step in 1...80 {
            rig.clock.now += 0.5
            rig.connection.send(.gyro(timestamp: UInt64(step) * 500_000,
                                      values: SIMD3<Double>(12, -4, 3)), at: rig.clock.now)
            rig.connection.send(.dataSeen, at: rig.clock.now)
            rig.connection.send(.heartbeat, at: rig.clock.now)
            await Task.yield()
        }
        // This benign injected accessibility change is an observable timer
        // tick, avoiding an arbitrary sleep to prove the watchdog actually ran.
        rig.controls.trusted = false
        try await waitForWatchdog { !rig.model.accessibilityAllowed }
        #expect(rig.connection.stops == 0 && rig.connection.starts == 1)
        #expect(rig.model.live && rig.model.streamHint == nil)
        #expect(rig.model.gestureCount == 0 && rig.model.totalGestureCount == 0)
        #expect(rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }
}
