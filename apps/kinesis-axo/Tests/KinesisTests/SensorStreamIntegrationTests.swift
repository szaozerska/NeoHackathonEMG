import Foundation
import Testing
import KinesisCore
@testable import Kinesis

@MainActor private final class SensorFeedPhoneTransport: PhoneUSBTransport {
    var ports: [String] = []
    var selectedPort = ""
    var connected = true
    var ready = true
    var armed = false
    var busy = false
    var statusText = "synthetic phone adapter"
    var onBoundary: (() -> Void)?
    func refreshPorts() {}
    func connect() {}
    func disconnect() { connected = false; ready = false; armed = false }
    func arm() { armed = true }
    func disarm() { armed = false }
    func send(action: PhoneNavigationAction) -> Bool { false }
}

@MainActor private final class SensorFeedRig {
    let defaults = MemoryDefaults()
    let connection = RecordedConnection()
    let phoneTransport = SensorFeedPhoneTransport()
    let model: BandModel
    var events: [SensorStreamEvent] = []

    init() {
        defaults.set(true, forKey: "setupCompleted")
        let phone = PhoneController(defaults: defaults, bridge: phoneTransport,
                                    clock: { 100 }, automaticallyTicks: false)
        model = BandModel(defaults: defaults, connection: connection, controls: RecordingControls(),
                          sessionStore: SavedSessionStore(), clock: { 100 }, phone: phone)
        model.selectedAddress = "synthetic-stream-band"
        model.sensorStream.onEvent = { [weak self] in self?.events.append($0) }
        model.connect()
        connection.send(.connected)
        connection.send(.heartbeat)
        connection.send(.handedness(.right))
    }

    func start() async throws {
        model.startSensorStream(port: 0)
        try await waitForFeed { self.model.sensorStream.server.isRunning }
        #expect(model.sensorStreamEnabled)
    }

    func close() async {
        model.stopSensorStream()
        await model.shutdown()
    }

    func sendSensors() throws {
        connection.send(.rawEMGConfiguration(try readingsConfiguration()))
        connection.send(.rawEMGState(true))
        connection.send(.rawEMGFrame(readingsPayload(sequence: 7)), at: 99.975)
        connection.send(.gyro(timestamp: 2_000_000, values: SIMD3(1, -2, 3)), at: 99.98)
        connection.send(.orientation(timestamp: 2_000_001, values: SIMD4(1, 0, 0, 0)), at: 99.985)
        connection.send(.gesture(BandGesture(sequence: 8, timestampUs: 2_000_002,
            finger: "thumb", action: "down", receivedAt: 99.99)), at: 99.99)
    }
}

@MainActor private func waitForFeed(_ condition: () -> Bool) async throws {
    let deadline = ContinuousClock.now + .seconds(5)
    while !condition(), ContinuousClock.now < deadline {
        try await Task.sleep(for: .milliseconds(5))
    }
    try #require(condition())
}

@Suite("Sensor stream model integration", .serialized)
@MainActor struct SensorStreamIntegrationTests {
    @Test func feedReceivesAllSensorTypesWhileControlsArePausedWithoutChangingMappingsOrPreferences() async throws {
        let rig = SensorFeedRig()
        let beforeMappings = rig.model.mappings
        let beforeTaps = rig.model.tapMappings
        let beforePreferences = rig.defaults.contents as NSDictionary
        try await rig.start()
        #expect(rig.model.rawEMGHolders.contains("sensor-stream"))
        #expect(rig.connection.rawEMGMode)
        #expect(!rig.model.rawEMGEnabled && !rig.model.controlsEnabled)
        #expect(rig.connection.motionRequests.last?.orientation == true)
        try rig.sendSensors()
        for type in ["emg_configuration", "emg", "gyro", "orientation", "gesture"] {
            #expect(rig.events.contains { $0.type == type })
        }
        #expect(rig.events.first { $0.type == "emg" }?.receivedAt == 99.975)
        #expect(rig.events.first { $0.type == "gyro" }?.receivedAt == 99.98)
        #expect(rig.model.mappings == beforeMappings && rig.model.tapMappings == beforeTaps)
        // The app's usual gesture counter may change; the feed never changes
        // stream preferences, mappings, or the selected control profile.
        for key in ["rawEMGEnabled", "developerMode", "swipeMappings", "tapMappings", "phoneGestureBindings"] {
            #expect(NSDictionary(dictionary: rig.defaults.contents)[key] as? NSObject == beforePreferences[key] as? NSObject)
        }
        await rig.close()
    }

    @Test func feedReceivesGesturesWhenThePhoneProfileOwnsActionRouting() async throws {
        let rig = SensorFeedRig()
        try await rig.start()
        rig.model.phone.connect()
        rig.model.enablePhoneControls()
        #expect(rig.model.phone.selected)
        let message = BandGesture(sequence: 42, timestampUs: 9_000,
            finger: "middle", action: "doubletap", receivedAt: 100)
        rig.connection.send(.gesture(message))
        rig.connection.send(.gesture(message))
        rig.connection.send(.gesture(BandGesture(sequence: 43, timestampUs: 9_001,
            finger: "middle", action: "release", synthetic: true, receivedAt: 100)))
        #expect(rig.events.contains { event in
            guard case .gesture(let gesture) = event.payload else { return false }
            return gesture.sequence == 42
        })
        #expect(rig.events.filter { $0.type == "gesture" }.count == 3)
        await rig.close()
    }

    @Test func feedAndTheReadingsSwitchShareEMGWithoutTurningEachOtherOff() async throws {
        let rig = SensorFeedRig()
        rig.model.developerMode = true
        rig.model.rawEMGEnabled = true
        rig.connection.send(.rawEMGState(true))
        try await rig.start()
        rig.model.rawEMGEnabled = false
        #expect(rig.connection.rawEMGMode && rig.model.rawEMGWanted)
        rig.model.rawEMGEnabled = true
        rig.model.stopSensorStream()
        #expect(rig.model.rawEMGEnabled && rig.model.rawEMGWanted && rig.connection.rawEMGMode)
        #expect(!rig.model.rawEMGHolders.contains("sensor-stream"))
        #expect(rig.connection.motionRequests.last?.orientation == false)
        rig.model.rawEMGEnabled = false
        #expect(!rig.connection.rawEMGMode)
        await rig.close()
    }

    @Test func reconnectKeepsTheFeedRequestedButChangesTheConnectionEpochAndClearsConfiguration() async throws {
        let rig = SensorFeedRig()
        try await rig.start()
        try rig.sendSensors()
        let firstConnection = try #require(rig.model.sensorStream.currentConnectionID)
        let feedSession = try #require(rig.model.sensorStream.sessionID)
        rig.model.disconnect()
        #expect(rig.model.sensorStreamEnabled)
        #expect(rig.model.rawEMGHolders.contains("sensor-stream"))
        #expect(!rig.model.rawEMGActive)
        let beforeReconnect = rig.events.count
        rig.model.connect()
        // Sensor traffic can precede the subscription acknowledgement. The
        // connection boundary must already be visible when that traffic arrives.
        rig.connection.send(.gyro(timestamp: 1, values: SIMD3(4, 5, 6)))
        let prefix = Array(rig.events.dropFirst(beforeReconnect))
        let epochStatus = try #require(prefix.firstIndex { event in
            guard case .status(let status) = event.payload else { return false }
            return status.bandConnectionID != firstConnection
        })
        let firstGyro = try #require(prefix.firstIndex { $0.type == "gyro" })
        #expect(epochStatus < firstGyro)
        rig.connection.send(.connected)
        rig.connection.send(.heartbeat)
        #expect(rig.model.sensorStream.currentConnectionID != firstConnection)
        #expect(rig.model.sensorStream.sessionID == feedSession)
        #expect(rig.connection.rawEMGMode && !rig.model.rawEMGActive)
        // An old configuration must never decode a new connection's data.
        let count = rig.events.filter { $0.type == "emg" }.count
        rig.connection.send(.rawEMGFrame(readingsPayload(sequence: 0)))
        #expect(rig.events.filter { $0.type == "emg" }.count == count)
        rig.connection.send(.rawEMGConfiguration(try readingsConfiguration()))
        rig.connection.send(.rawEMGState(true))
        rig.connection.send(.rawEMGFrame(readingsPayload(sequence: 1)))
        #expect(rig.events.filter { $0.type == "emg" }.count == count + 1)
        await rig.close()
    }

    @Test func stoppingDuringAModelOperationAndLosingTheLinkDoesNotRestoreAnUnwantedSubscription() async throws {
        let rig = SensorFeedRig()
        try await rig.start()
        rig.connection.send(.rawEMGState(true))
        rig.model.developerMode = true
        try rig.model.setModelCaptureEnabled(true)
        rig.model.stopSensorStream()
        #expect(!rig.model.rawEMGWanted && rig.connection.rawEMGMode)
        rig.connection.finish(error: KinesisError(message: "synthetic link loss during restoration"))
        try await waitForFeed { rig.connection.starts >= 2 }
        #expect(!rig.connection.rawEMGMode)
        #expect(!rig.model.sensorStreamEnabled && !rig.model.rawEMGWanted)
        await rig.close()
    }

    @Test func modelOperationBlocksFeedActivationWithoutLeakingAStreamHold() async throws {
        let rig = SensorFeedRig()
        rig.model.developerMode = true
        try rig.model.setModelCaptureEnabled(true)
        rig.model.startSensorStream(port: 0)
        #expect(!rig.model.sensorStreamEnabled)
        #expect(rig.model.sensorStreamError != nil)
        #expect(!rig.model.rawEMGHolders.contains("sensor-stream"))
        #expect(!rig.connection.rawEMGMode)
        rig.connection.send(.modelCaptureState(.init(phase: .finished, message: "restored", restorationVerified: true)))
        await rig.close()
    }

    @Test func listenerFailureReleasesTheFeedHoldAndReportsTheFailure() async throws {
        let blocker = SensorStreamServer()
        blocker.start(port: 0)
        try await waitForFeed { blocker.isRunning }
        defer { blocker.stop() }
        let port = try #require(blocker.endpointURL?.port)
        let rig = SensorFeedRig()
        rig.model.startSensorStream(port: UInt16(port))
        try await waitForFeed { !rig.model.sensorStreamEnabled }
        #expect(!rig.model.rawEMGHolders.contains("sensor-stream"))
        #expect(!rig.model.rawEMGWanted && !rig.connection.rawEMGMode)
        #expect(!rig.model.sensorStream.server.isRunning)
        #expect(rig.model.sensorStream.server.statusText != "Local stream is off.")
        await rig.close()
    }

    @Test func stoppingDuringAModelOperationDefersTheEMGReleaseUntilItFinishes() async throws {
        let rig = SensorFeedRig()
        try await rig.start()
        rig.connection.send(.rawEMGState(true))
        rig.model.developerMode = true
        try rig.model.setModelCaptureEnabled(true)
        rig.model.stopSensorStream()
        #expect(!rig.model.sensorStreamEnabled && !rig.model.rawEMGWanted)
        #expect(!rig.model.rawEMGHolders.contains("sensor-stream"))
        // The model owns configuration until it publishes its final status.
        #expect(rig.connection.rawEMGMode)
        rig.connection.send(.modelCaptureState(.init(phase: .finished, message: "restored", restorationVerified: true)))
        #expect(!rig.connection.rawEMGMode)
        await rig.close()
    }
}
