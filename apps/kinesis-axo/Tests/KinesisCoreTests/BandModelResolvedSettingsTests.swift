import Foundation
import Testing
@testable import KinesisCore

private enum ResolvedFixtureError: Error { case unexpectedRequest }

private enum ResolvedRequest: Equatable {
    case streams(Bool), claim, describe(Int), read(Int), write(Int, UInt64, boolean: Bool), config
}

/// Parses the wire request independently of the capture's resolved-ID bookkeeping.
private func resolvedRequest(_ request: BandModelCapture.Request) throws -> ResolvedRequest {
    let rpc = try ProtoFields(request.payload(streams: Data()))
    if case .streams(let enabled) = request.operation { return .streams(enabled) }
    if rpc.contains(5) { return .config }
    let control = try ProtoFields(rpc.bytes(14))
    if control.contains(1) { return .claim }
    if control.contains(2) {
        return .describe(Int(try ProtoFields(control.bytes(2)).requiredInteger(2)))
    }
    let setting = try ProtoFields(control.bytes(3))
    let id = Int(try setting.requiredInteger(1))
    if try setting.integer(2) == 0 { return .read(id) }
    let boolean = setting.contains(7)
    guard boolean != setting.contains(10) else { throw ResolvedFixtureError.unexpectedRequest }
    let scalar = try ProtoFields(setting.bytes(boolean ? 7 : 10))
    return .write(id, try scalar.integer(1), boolean: boolean)
}

private struct ResolvedSettingsFixture {
    let count: Int
    let collection: Int
    let model: Int
    var extraNames: [Int: String] = [:]
    var missingDescriptions: Set<Int> = []
    var corruptSnapshot: Int?
    var omittedSnapshot: Int?
    var values: [Int: UInt64]

    init(count: Int, collection: Int, model: Int, originalModel: UInt64 = 3) {
        self.count = count
        self.collection = collection
        self.model = model
        values = [collection: 0, model: originalModel]
    }

    mutating func response(_ request: BandModelCapture.Request, operation: ResolvedRequest) throws -> Data? {
        let body: Data
        switch operation {
        case .streams(let enabled):
            body = BandWire.field(5, [4, 22, 23].reduce(into: Data()) {
                $0 += BandWire.field($1, enabled ? 1 : 0)
            })
        case .claim:
            body = BandWire.field(14, BandWire.field(1, BandWire.field(1, UInt64(count))))
        case .describe(let id):
            if missingDescriptions.contains(id) { return nil }
            let name = extraNames[id] ?? (id == collection ? "data-collection"
                : id == model ? "data-collection-model" : "fixture-setting-\(id)")
            body = BandWire.field(14, BandWire.field(2,
                BandWire.field(4, UInt64(id)) + BandWire.field(3, Data(name.utf8))))
        case .read(let id):
            guard let value = values[id] else { throw ResolvedFixtureError.unexpectedRequest }
            let boolean = id == collection
            let field = id == corruptSnapshot ? (boolean ? 11 : 8) : (boolean ? 8 : 11)
            let scalar = value == 0 ? Data() : BandWire.field(1, value)
            body = BandWire.field(14, BandWire.field(3,
                BandWire.field(1, UInt64(id)) + (id == omittedSnapshot ? Data() : BandWire.field(field, scalar))))
        case .write(let id, let value, let boolean):
            guard id == collection || id == model, boolean == (id == collection) else {
                throw ResolvedFixtureError.unexpectedRequest
            }
            values[id] = value
            body = BandWire.field(14, BandWire.field(3,
                BandWire.field(1, UInt64(id)) + BandWire.field(2, 1)))
        case .config:
            body = BandWire.field(6, BandWire.field(46, BandWire.field(3, 2)))
        }
        return BandWire.field(1, request.id) + BandWire.field(2, 1) + body
    }
}

private func resolveAndRun(_ capture: BandModelCapture, fixture: inout ResolvedSettingsFixture,
                           from start: Double = 0) throws -> [ResolvedRequest] {
    var now = start
    var seen: [ResolvedRequest] = []
    while let request = capture.next(at: now) {
        guard seen.count < 512 else { throw ResolvedFixtureError.unexpectedRequest }
        let operation = try resolvedRequest(request)
        seen.append(operation)
        if let response = try fixture.response(request, operation: operation) {
            #expect(capture.receive(channel: request.channel, payload: response, at: now + 0.001))
            now += 0.01
        } else {
            now = request.deadline + 0.01
        }
    }
    return seen
}

private func settingRequests(_ requests: [ResolvedRequest]) -> [ResolvedRequest] {
    requests.filter {
        switch $0 { case .read, .write: true; default: false }
    }
}

private func writes(_ requests: [ResolvedRequest]) -> [ResolvedRequest] {
    requests.filter { if case .write = $0 { true } else { false } }
}

@Suite("Name-resolved handwriting settings")
struct BandModelResolvedSettingsTests {
    @Test func lowCountControlsUseTheirResolvedTypesAndRestoreTheOriginalModel() throws {
        let capture = BandModelCapture()
        var fixture = ResolvedSettingsFixture(count: 27, collection: 19, model: 20)
        try capture.start(at: 0)
        let prepare = try resolveAndRun(capture, fixture: &fixture)
        #expect(settingRequests(prepare) == [.read(19), .read(20), .write(19, 1, boolean: true),
            .write(20, 5, boolean: false), .read(19), .read(20)])
        let descriptors = prepare.compactMap { if case .describe(let id) = $0 { id } else { nil } }
        #expect(descriptors == Array(1...27))
        #expect(capture.status.problem == nil)
        capture.restore(at: 2)
        let restore = try resolveAndRun(capture, fixture: &fixture, from: 2)
        #expect(settingRequests(restore) == [.write(20, 3, boolean: false), .write(19, 0, boolean: true),
            .read(20), .read(19)])
        #expect(capture.status.restorationVerified)
        #expect(fixture.values[19] == 0 && fixture.values[20] == 3)
    }

    @Test func aCollectionAtTheLegacyModelIndexStillUsesBooleanWireFields() throws {
        let capture = BandModelCapture()
        var fixture = ResolvedSettingsFixture(count: 40, collection: 28, model: 29)
        try capture.start(at: 0)
        let prepare = try resolveAndRun(capture, fixture: &fixture)
        #expect(settingRequests(prepare) == [.read(28), .read(29), .write(28, 1, boolean: true),
            .write(29, 5, boolean: false), .read(28), .read(29)])
        let firstWrite = try #require(prepare.firstIndex { if case .write = $0 { true } else { false } })
        let lastDescriptor = try #require(prepare.lastIndex { if case .describe = $0 { true } else { false } })
        #expect(firstWrite > lastDescriptor)
        capture.restore(at: 2)
        let restore = try resolveAndRun(capture, fixture: &fixture, from: 2)
        #expect(writes(restore) == [.write(29, 3, boolean: false), .write(28, 0, boolean: true)])
        #expect(capture.status.restorationVerified)
    }

    @Test func theLegacyControlTableKeepsItsVerifiedWriteAndRestoreBehavior() throws {
        let capture = BandModelCapture()
        var fixture = ResolvedSettingsFixture(count: 38, collection: 27, model: 28)
        try capture.start(at: 0)
        let prepare = try resolveAndRun(capture, fixture: &fixture)
        #expect(writes(prepare) == [.write(27, 1, boolean: true), .write(28, 5, boolean: false)])
        capture.restore(at: 2)
        let restore = try resolveAndRun(capture, fixture: &fixture, from: 2)
        #expect(writes(restore) == [.write(28, 3, boolean: false), .write(27, 0, boolean: true)])
        #expect(capture.status.restorationVerified)
    }

    @Test(arguments: [19, 20]) func aWrongTypedSnapshotStopsBeforeAnySettingsWrite(setting: Int) throws {
        let capture = BandModelCapture()
        var fixture = ResolvedSettingsFixture(count: 27, collection: 19, model: 20)
        fixture.corruptSnapshot = setting
        try capture.start(at: 0)
        let seen = try resolveAndRun(capture, fixture: &fixture)
        #expect(writes(seen).isEmpty)
        #expect(capture.status.phase == .finished && capture.status.problem != nil)
        #expect(capture.status.restorationVerified)
        #expect(fixture.values[19] == 0 && fixture.values[20] == 3)
    }

    @Test func recoveryOnANewConnectionResolvesItsOwnIdsAndChecksBothTypesBeforeWriting() throws {
        let first = BandModelCapture()
        var previous = ResolvedSettingsFixture(count: 27, collection: 19, model: 20)
        try first.start(at: 0)
        _ = try resolveAndRun(first, fixture: &previous)
        first.restore(at: 2)
        _ = try resolveAndRun(first, fixture: &previous, from: 2)

        let recovery = BandModelCapture()
        var current = ResolvedSettingsFixture(count: 40, collection: 28, model: 29, originalModel: 5)
        current.values[28] = 1
        try recovery.recoverNormalMode(at: 0)
        let seen = try resolveAndRun(recovery, fixture: &current)
        #expect(settingRequests(seen) == [.read(28), .read(29), .write(29, 2, boolean: false),
            .write(28, 0, boolean: true), .read(29), .read(28)])
        #expect(recovery.status.restorationVerified && recovery.status.phase == .finished)
        #expect(current.values[28] == 0 && current.values[29] == 2)
    }

    @Test(arguments: [true, false]) func ambiguousOrIncompleteDescriptionsNeverEnableWriting(ambiguous: Bool) throws {
        let capture = BandModelCapture()
        var fixture = ResolvedSettingsFixture(count: 27, collection: 19, model: 20)
        if ambiguous { fixture.extraNames[18] = "data-collection" }
        else { fixture.missingDescriptions = [7] }
        try capture.start(at: 0)
        let seen = try resolveAndRun(capture, fixture: &fixture)
        #expect(settingRequests(seen).isEmpty)
        #expect(capture.status.phase == .finished && capture.status.problem != nil)
        #expect(capture.status.restorationVerified)
    }

    @Test(arguments: [true, false])
    func recoveryWithAWrongOrMissingTypedSnapshotCannotClaimRestorationOrWriteSettings(missing: Bool) throws {
        let capture = BandModelCapture()
        var fixture = ResolvedSettingsFixture(count: 27, collection: 19, model: 20, originalModel: 5)
        if missing { fixture.omittedSnapshot = 20 } else { fixture.corruptSnapshot = 20 }
        try capture.recoverNormalMode(at: 0)
        let seen = try resolveAndRun(capture, fixture: &fixture)
        #expect(writes(seen).isEmpty)
        #expect(capture.status.phase == .finished && !capture.status.restorationVerified)
        #expect(capture.status.problem != nil)
    }

    @Test(arguments: [true, false]) func anInvalidBooleanSnapshotCannotEnableSettingsWrites(recovery: Bool) throws {
        let capture = BandModelCapture()
        var fixture = ResolvedSettingsFixture(count: 27, collection: 19, model: 20)
        fixture.values[19] = 2
        if recovery { try capture.recoverNormalMode(at: 0) } else { try capture.start(at: 0) }
        let seen = try resolveAndRun(capture, fixture: &fixture)
        #expect(writes(seen).isEmpty)
        #expect(capture.status.phase == .finished && capture.status.problem != nil)
        let expectedVerification = !recovery
        #expect(capture.status.restorationVerified == expectedVerification)
    }
}
