import Combine
import Foundation
import KinesisCore

/// A read-only feed of decoded sensor messages, before any control/action filters.
/// No recording files, pairing material, or action mappings enter this path.
@MainActor final class SensorStreamController: ObservableObject {
    let server: SensorStreamServer
    @Published private(set) var enabled = false
    private(set) var sessionID: String?
    private(set) var currentConnectionID: String?
    private var sequence: UInt64 = 0
    private var configuration: EMGConfiguration?
    private var status: SensorStreamStatus?
    private let clock: () -> Double
    private var serverChanges: AnyCancellable?
    var onStopped: (() -> Void)?
    /// In-process observation for consumers/tests; never invokes control actions.
    var onEvent: ((SensorStreamEvent) -> Void)?

    init(server: SensorStreamServer = SensorStreamServer(),
         clock: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime }) {
        self.server = server
        self.clock = clock
        serverChanges = server.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }
        server.onSubscribe = { [weak self] client in self?.subscribe(client) }
        server.onStopped = { [weak self] in self?.stopped() }
    }

    func start(port: UInt16 = 8766, status: SensorStreamStatus, configuration: EMGConfiguration?) {
        guard !enabled else { return }
        self.status = status
        self.configuration = configuration
        sessionID = UUID().uuidString
        sequence = 0
        enabled = true
        server.start(port: port)
    }

    func stop() {
        server.stop()
        stopped()
    }

    private func stopped() {
        guard enabled else { return }
        enabled = false
        configuration = nil
        status = nil
        onStopped?()
    }

    func beginConnection() {
        currentConnectionID = UUID().uuidString
        configuration = nil
    }

    func clearConfiguration() { configuration = nil }

    func updateStatus(_ value: SensorStreamStatus, at time: Double) {
        guard enabled, value != status else { return }
        status = value
        publish(.status(value), at: time)
    }

    func receive(_ event: BandEvent) {
        guard enabled else { return }
        switch event.payload {
        case .rawEMGConfiguration(let value):
            configuration = value
            publish(.emgConfiguration(value), at: event.receivedAt)
        case .rawEMGFrame(let data):
            guard let configuration, let batch = try? EMGBatch(payload: data, configuration: configuration) else { return }
            publish(.emg(batch), at: event.receivedAt)
        case .gyro(let timestamp, let values):
            publish(.gyro(timestamp: timestamp, values: values), at: event.receivedAt)
        case .orientation(let timestamp, let values):
            publish(.orientation(timestamp: timestamp, values: values), at: event.receivedAt)
        case .gesture(let gesture):
            publish(.gesture(gesture), at: event.receivedAt)
        default: break
        }
    }

    private func event(_ payload: SensorStreamEvent.Payload, at time: Double) -> SensorStreamEvent? {
        guard let sessionID else { return nil }
        sequence &+= 1
        return SensorStreamEvent(sessionID: sessionID, sequence: sequence, receivedAt: time, payload: payload)
    }

    private func publish(_ payload: SensorStreamEvent.Payload, at time: Double) {
        guard let event = event(payload, at: time) else { return }
        onEvent?(event)
        // There is no sensor history to replay. Encode only when someone is listening.
        guard server.clientCount > 0, let data = try? event.sseData() else { return }
        server.publish(data)
    }

    private func subscribe(_ client: UUID) {
        guard enabled, let status else { return }
        var initial: [Data] = []
        if let hello = event(.hello(status), at: clock()), let bytes = try? hello.sseData() { initial.append(bytes) }
        if let configuration, let config = event(.emgConfiguration(configuration), at: clock()),
           let bytes = try? config.sseData() { initial.append(bytes) }
        server.sendInitial(initial, to: client)
    }
}
