import Foundation
import OSLog

/// Original inference payload plus its schema fields. Output indices are not character labels.
public struct BandInferenceSample: Sendable {
    public let sequence: UInt64
    public let timestampUs: UInt64
    public let pipeline: UInt64
    public let latencyUs: UInt64?
    public let values: [Float]
    public let payload: Data

    public init(payload: Data) throws {
        let fields = try ProtoFields(payload)
        sequence = try fields.requiredInteger(1)
        timestampUs = try fields.requiredInteger(2)
        pipeline = try fields.requiredInteger(10)
        guard sequence <= UInt32.max, pipeline <= UInt32.max else { throw BandProtocolError("Invalid inference sample identifier") }
        latencyUs = fields.contains(7) ? try fields.integer(7) : nil
        let bytes = try fields.bytes(3)
        guard !bytes.isEmpty, bytes.count % 4 == 0, bytes.count <= 4096 else {
            throw BandProtocolError("Invalid inference sample dimensions")
        }
        values = bytes.withUnsafeBytes { raw in
            stride(from: 0, to: bytes.count, by: 4).map {
                Float(bitPattern: UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: $0, as: UInt32.self)))
            }
        }
        guard values.allSatisfy(\.isFinite) else { throw BandProtocolError("Nonfinite inference sample") }
        self.payload = payload
    }

    public var isTextDistribution: Bool {
        pipeline == 3 && values.count == 100 && values.allSatisfy { $0 <= 0.000001 }
            && abs(values.reduce(0.0) { $0 + exp(Double($1)) } - 1) < 0.0001
    }
}

public struct BandModelCaptureStatus: Equatable, Sendable {
    public enum Phase: Sendable { case idle, preparing, ready, restoring, finished }
    public let phase: Phase
    public let message: String
    public let problem: String?
    public let restorationVerified: Bool
    public init(phase: Phase, message: String, problem: String? = nil, restorationVerified: Bool = false) {
        self.phase = phase; self.message = message; self.problem = problem; self.restorationVerified = restorationVerified
    }
    public var active: Bool { phase == .preparing || phase == .ready || phase == .restoring }
    public static let idle = Self(phase: .idle, message: "", problem: nil, restorationVerified: false)
}

/// Matched RPCs and independent readbacks for one temporary built-in-model recording.
/// It owns no transport: BandSession sends these requests on its existing connection.
final class BandModelCapture {
    enum Operation: Equatable {
        /// `snapshot` reads a setting's value before the recording changes it.
        case streams(Bool), claim, info(Int), inspect(Int), snapshot(Int), write(Int, UInt64), read(Int, UInt64), config
    }
    struct Request {
        let id: UInt64
        let operation: Operation
        let deadline: Double
        /// The boolean setting's resolved ID; the model setting uses the enum fields.
        let collectionID: Int
        init(id: UInt64, operation: Operation, deadline: Double, collectionID: Int = 27) {
            self.id = id; self.operation = operation; self.deadline = deadline; self.collectionID = collectionID
        }
        var channel: UInt16 {
            // Settings and configuration are arms of the same generic RPC
            // service. Reuse it instead of opening another service for Config.
            switch operation { case .streams: 0x8005; default: 0x8001 }
        }
        var diagnosticStage: String {
            switch operation {
            case .streams(let enabled): enabled ? "starting model streams" : "stopping model streams"
            case .claim: "claiming model controls"
            case .info, .inspect: "describing model setting"
            case .snapshot(let id): id == collectionID ? "reading collection setting" : "reading model setting"
            case .write(let id, _): id == collectionID ? "writing collection setting" : "writing model setting"
            case .read(let id, _): id == collectionID ? "checking collection setting" : "checking model setting"
            case .config: "reading model configuration"
            }
        }
        func payload(streams: Data) -> Data {
            let arm: Int
            let body: Data
            switch operation {
            case .streams: arm = 4; body = streams
            case .config: arm = 5; body = Data()
            case .claim: arm = 14; body = BandWire.field(1, BandWire.field(1, 2))
            case .info(let id), .inspect(let id): arm = 14; body = BandWire.field(2, BandWire.field(1, 2) + BandWire.field(2, UInt64(id)))
            case .write(let id, let value):
                arm = 14
                body = BandWire.field(3, BandWire.field(1, UInt64(id)) + BandWire.field(2, 1) + BandWire.field(id == collectionID ? 7 : 10, BandWire.field(1, value)))
            case .read(let id, _), .snapshot(let id): arm = 14; body = BandWire.field(3, BandWire.field(1, UInt64(id)) + BandWire.field(2, 0))
            }
            return BandWire.field(1, id) + BandWire.field(arm, body)
        }
    }
    private(set) var status = BandModelCaptureStatus.idle
    private(set) var streamWanted = false
    private(set) var streamTouched = false
    private(set) var pending: Request?
    private var operations: [Operation] = []
    private var nextID: UInt64 = 0x10000000
    private var mutated = false
    private var restoreErrors: [String] = []
    private var problem: String?
    private var samples = 0
    private var lastSample = 0.0
    private var deadline = Double.infinity
    private var events: [BandEvent] = []
    private var checkingRecoverySchema = false
    /// The band's own values at the resolved collection and model settings.
    private var original: [Int: UInt64] = [:]
    /// One retry for a restore step whose answer went missing.
    private var retriedRestore = false
    /// Unfamiliar settings are identified by name before their values can be changed.
    private var inspectionCount: Int?
    private var inspected = 0
    private var inspectedNames: [String: Set<Int>] = [:]
    private var settingCount: Int?
    private var collectionID = 27
    private var modelID = 28
    private var settingsValidated = false
    private static let log = Logger(subsystem: "local.callbacked.kinesis", category: "model")

    /// A bounded, pure summary of reply structure. The request supplies the fixed stage
    /// and numeric setting ID; no response values or arbitrary descriptions enter it.
    static func replyDiagnostic(_ request: Request, payload: Data) -> String {
        let rpc = try? ProtoFields(payload)
        let wrapper = rpc.flatMap { try? ProtoFields($0.bytes(14)) }
        let arm: Int?
        let setting: Int?
        switch request.operation {
        case .claim: arm = 1; setting = nil
        case .info(let id), .inspect(let id): arm = 2; setting = id
        case .snapshot(let id), .read(let id, _), .write(let id, _): arm = 3; setting = id
        case .streams, .config: arm = nil; setting = nil
        }
        var parts = ["Model reply metadata: " + request.diagnosticStage]
        if let setting { parts.append("setting=\(setting)") }
        parts.append("rpc=[\(rpc?.wireShape ?? "invalid")]")
        if let arm {
            parts.append("wrapper14=[\(wrapper?.wireShape ?? "unavailable")]")
            let response = wrapper.flatMap { try? ProtoFields($0.bytes(arm)) }
            parts.append("response14.\(arm)=[\(response?.wireShape ?? "unavailable")]")
        } else if case .config = request.operation {
            let config = rpc.flatMap { try? ProtoFields($0.bytes(6)) }
            parts.append("config6=[\(config?.wireShape ?? "unavailable")]")
        }
        return String(parts.joined(separator: " ").prefix(512))
    }

    /// What a restore writes back: the band's own values, unless they look like an unfinished
    /// recording (collection on, or the handwriting model), then the known normal ones.
    private var normalCollection: UInt64 { original[collectionID].flatMap { $0 == 0 ? $0 : nil } ?? 0 }
    private var normalModel: UInt64 { original[modelID].flatMap { $0 == 5 ? nil : $0 } ?? 2 }

    func start(at time: Double) throws {
        guard !status.active else { throw BandProtocolError("A band model recording is already running") }
        problem = nil; restoreErrors = []; mutated = false; samples = 0; lastSample = time
        pending = nil; original = [:]; retriedRestore = false
        resetInspection()
        resetSettings()
        checkingRecoverySchema = false
        operations = [.streams(true), .claim]
        deadline = time + 40
        publish(.preparing, "checking the band model…", at: time)
    }

    func recoverNormalMode(at time: Double) throws {
        guard !status.active else { throw BandProtocolError("A band model operation is already running") }
        problem = nil; restoreErrors = []; pending = nil; original = [:]; retriedRestore = false
        resetInspection()
        resetSettings()
        mutated = true
        checkingRecoverySchema = true
        operations = [.claim]
        deadline = time + 50
        publish(.restoring, "recovering the band’s normal mode…", at: time)
    }

    func restore(at time: Double) {
        guard status.active, status.phase != .restoring else { return }
        resetInspection()
        pending = nil
        operations = (mutated && settingsValidated ? [.write(modelID, normalModel), .write(collectionID, normalCollection), .read(modelID, normalModel),
                                                      .read(collectionID, normalCollection), .config] : []) + [.streams(false)]
        deadline = time + 35
        publish(.restoring, "restoring the band’s normal mode…", at: time)
    }

    func next(at time: Double) -> Request? {
        guard status.active else { return nil }
        if time >= deadline {
            // The whole operation ran out of time: never a retry, and never verified.
            fail("the band model operation timed out", at: time, retry: false)
            if status.phase == .restoring, time >= deadline {
                operations = []; pending = nil; complete(at: time)
            }
        }
        if let pending, time >= pending.deadline {
            Self.log.error("Model request timed out: \(pending.diagnosticStage, privacy: .public)")
            if case .inspect = pending.operation { self.pending = nil }
            else {
                fail(pending.diagnosticStage + ": the band did not answer a model request", at: time)
            }
        }
        guard pending == nil, status.active else { return nil }
        if !operations.isEmpty {
            let operation = operations.removeFirst()
            if case .streams(let wanted) = operation { streamTouched = true; streamWanted = wanted }
            if case .write = operation { mutated = true }
            nextID += 1
            let lookup: Bool
            if case .inspect = operation { lookup = true } else { lookup = false }
            let request = Request(id: nextID, operation: operation, deadline: time + (lookup ? 1 : 5), collectionID: collectionID)
            pending = request
            return request
        }
        if inspectionCount != nil {
            finishInspection(at: time)
            return next(at: time)
        }
        if status.phase == .restoring { complete(at: time) }
        else if status.phase == .preparing, samples >= 5, time - lastSample < 2 {
            deadline = time + 360
            publish(.ready, "band model ready", at: time)
        } else if status.phase == .ready, time - lastSample > 3 {
            fail("the band model stopped sending samples", at: time)
        }
        return nil
    }

    /// A service rejection carries no RPC ID, so only the outstanding model
    /// request's canonical channel can identify it. Unrelated services retain
    /// their normal rejection handling in BandSession.
    @discardableResult
    func reject(channel: UInt16, at time: Double) -> Bool {
        guard let pending, channel & 0x7fff == pending.channel & 0x7fff else { return false }
        Self.log.error("Model request rejected: \(pending.diagnosticStage, privacy: .public)")
        if case .inspect = pending.operation { self.pending = nil }
        else { fail(pending.diagnosticStage + ": the band rejected a model request", at: time) }
        return true
    }

    @discardableResult
    func receive(channel: UInt16, payload: Data, at time: Double) -> Bool {
        guard let pending, channel & 0x7fff == pending.channel & 0x7fff else { return false }
        do {
            let fields = try ProtoFields(payload)
            guard try fields.integer(1) == pending.id else { return false }
            guard time < pending.deadline, try fields.integer(2) == 1 else {
                throw BandProtocolError("the band rejected or timed out a model request")
            }
            switch pending.operation {
            case .streams(let enabled):
                let flags = try ProtoFields(fields.bytes(5))
                guard try [4, 22, 23].allSatisfy({ try flags.integer($0) == (enabled ? 1 : 0) }) else {
                    throw BandProtocolError("the band did not confirm model streams")
                }
            case .claim:
                let available: UInt64
                do {
                    let count = try ProtoFields(ProtoFields(fields.bytes(14)).bytes(1))
                    available = try count.requiredInteger(1)
                } catch { throw BandProtocolError("the band returned an unsupported model settings schema") }
                guard (1...128).contains(available) else {
                    throw BandProtocolError("the band returned an unsupported model settings schema")
                }
                settingCount = Int(available)
                if available < 28 {
                    beginInspection(count: Int(available))
                } else { operations = [.info(27), .info(28)] }
            case .info(let id):
                let info = try ProtoFields(ProtoFields(fields.bytes(14)).bytes(2))
                let name = id == collectionID ? "data-collection" : "data-collection-model"
                guard try info.integer(4) == UInt64(id), try info.bytes(3) == Data(name.utf8) else {
                    guard let settingCount else { throw BandProtocolError("the band returned an unsupported model settings schema") }
                    beginInspection(count: settingCount)
                    break
                }
                if id == modelID { prepareSnapshots() }
            case .inspect(let id):
                let info = try ProtoFields(ProtoFields(fields.bytes(14)).bytes(2))
                guard try info.requiredInteger(4) == UInt64(id) else {
                    throw BandProtocolError("mismatched setting description")
                }
                let name = try info.bytes(3)
                guard !name.isEmpty, name.count <= 64,
                      name.allSatisfy({ (0x20...0x7e).contains($0) }) else {
                    throw BandProtocolError("invalid setting description")
                }
                inspected += 1
                for known in ["data-collection", "data-collection-model"] where name == Data(known.utf8) {
                    inspectedNames[known, default: []].insert(id)
                }
            case .write(let id, _), .read(let id, _), .snapshot(let id):
                let response = try ProtoFields(ProtoFields(fields.bytes(14)).bytes(3))
                let writing: Bool
                if case .write = pending.operation { writing = true } else { writing = false }
                guard try response.integer(1) == UInt64(id), try response.integer(2) == (writing ? 1 : 0), try response.integer(3) == 0 else {
                    throw BandProtocolError("the band refused a model setting")
                }
                let scalarField = id == pending.collectionID ? 8 : 11
                if case .read(_, let expected) = pending.operation {
                    let value = try ProtoFields(response.bytes(scalarField))
                    guard !response.contains(scalarField == 8 ? 11 : 8) else { throw BandProtocolError("model setting readback had the wrong type") }
                    guard try value.integer(1) == expected else { throw BandProtocolError("model setting readback did not match") }
                }
                if case .snapshot = pending.operation {
                    let value = try ProtoFields(response.bytes(scalarField)).integer(1)
                    guard !response.contains(scalarField == 8 ? 11 : 8),
                          id == pending.collectionID ? value <= 1 : value <= UInt32.max else {
                        throw BandProtocolError("the band’s model setting had the wrong type")
                    }
                    original[id] = value
                    if original[collectionID] != nil, original[modelID] != nil { prepareWrites() }
                }
            case .config:
                _ = try ProtoFields(fields.bytes(6))
                events.append(BandEvent(.inferenceConfiguration(payload), at: time))
            }
            self.pending = nil
        } catch {
            Self.log.error("\(Self.replyDiagnostic(pending, payload: payload), privacy: .public)")
            if case .inspect = pending.operation { self.pending = nil }
            else if case .info = pending.operation, let settingCount {
                self.pending = nil
                beginInspection(count: settingCount)
            }
            else { fail(pending.diagnosticStage + ": " + error.localizedDescription, at: time) }
        }
        return true
    }

    func receive(_ sample: BandInferenceSample, at time: Double) {
        guard status.active, sample.pipeline == 3, status.phase != .restoring, inspectionCount == nil else { return }
        guard sample.isTextDistribution else { fail("the band model output has an unsupported shape", at: time); return }
        samples += 1; lastSample = time
        // A session runs as long as samples keep coming. Silence ends it within seconds.
        if status.phase == .ready { deadline = time + 360 }
    }

    func drainEvents() -> [BandEvent] { defer { events = [] }; return events }

    private func resetInspection() {
        inspectionCount = nil
        inspected = 0
        inspectedNames = [:]
    }

    private func resetSettings() {
        settingCount = nil
        collectionID = 27
        modelID = 28
        settingsValidated = false
    }

    private func beginInspection(count: Int) {
        resetInspection()
        inspectionCount = count
        operations = (1...count).map(Operation.inspect)
    }

    private func prepareSnapshots() {
        operations = [.snapshot(collectionID), .snapshot(modelID)]
    }

    private func prepareWrites() {
        settingsValidated = true
        if checkingRecoverySchema {
            checkingRecoverySchema = false
            operations = [.write(modelID, normalModel), .write(collectionID, normalCollection),
                          .read(modelID, normalModel), .read(collectionID, normalCollection), .config, .streams(false)]
        } else {
            operations = [.write(collectionID, 1), .write(modelID, 5),
                          .read(collectionID, 1), .read(modelID, 5), .config]
        }
    }

    private func finishInspection(at time: Double) {
        guard let count = inspectionCount else { return }
        inspectionCount = nil
        let names = ["data-collection", "data-collection-model"]
        let ambiguous = names.contains { inspectedNames[$0, default: []].count > 1 }
        let bothFound = names.allSatisfy { inspectedNames[$0, default: []].count == 1 }
        if inspected == count, bothFound,
           let collection = inspectedNames[names[0]]?.first,
           let model = inspectedNames[names[1]]?.first, collection != model,
           (1...count).contains(collection), (1...count).contains(model) {
            collectionID = collection
            modelID = model
            prepareSnapshots()
            return
        }
        let summary: String
        if inspected < count {
            summary = "the band’s model settings could not be fully identified (\(inspected) of \(count) descriptions checked)."
        } else if ambiguous {
            summary = "the band returned an ambiguous model settings table (\(count) settings checked)."
        } else if bothFound {
            summary = "handwriting controls use a different settings table (\(count) settings checked)."
        } else {
            summary = "handwriting controls are not exposed by this band’s settings table (\(count) settings checked)."
        }
        let known = names.compactMap { name -> String? in
            let ids = inspectedNames[name, default: []]
            if ids.count > 1 { return name + ": ambiguous" }
            return ids.first.map { name + ": setting \($0)" }
        }
        fail(summary + (known.isEmpty ? "" : " " + known.joined(separator: "; ") + "."), at: time, retry: false)
    }

    private func fail(_ message: String, at time: Double, retry: Bool = true) {
        let failed = pending?.operation
        pending = nil
        if retry, status.phase == .restoring, !checkingRecoverySchema, !retriedRestore, let failed, failed != .claim {
            // One dropped packet must not leave the band in the recording's mode.
            retriedRestore = true
            operations.insert(failed, at: 0)
            return
        }
        if status.phase == .restoring {
            restoreErrors.append(message)
            // A restarted app must validate the control schema again before
            // writing values remembered from an earlier connection.
            if checkingRecoverySchema { operations = []; checkingRecoverySchema = false }
        }
        else { problem = message; restore(at: time) }
    }

    private func complete(at time: Double) {
        let verified = restoreErrors.isEmpty
        if !verified { problem = ([problem].compactMap { $0 } + restoreErrors).joined(separator: "; ") }
        let message = verified ? (mutated ? "normal band mode restored" : "model unchanged; recording stopped") : "restoration could not be verified"
        publish(.finished, message, verified: verified, at: time)
    }

    private func publish(_ phase: BandModelCaptureStatus.Phase, _ message: String, verified: Bool = false, at time: Double) {
        status = .init(phase: phase, message: message, problem: problem, restorationVerified: verified)
        events.append(BandEvent(.modelCaptureState(status), at: time))
    }
}
