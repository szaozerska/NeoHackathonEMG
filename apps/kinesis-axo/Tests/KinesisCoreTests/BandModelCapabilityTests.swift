import Foundation
import Testing
@testable import KinesisCore

private enum CapabilityFixtureError: Error { case unexpectedSettingOperation }

private func capabilityReply(_ request: BandModelCapture.Request, count: UInt64? = 27,
                             name: Data = Data("other-setting".utf8), returnedID: Int? = nil) throws -> Data {
    let body: Data
    switch request.operation {
    case .streams(let enabled):
        body = BandWire.field(5, [4, 22, 23].reduce(into: Data()) { $0 += BandWire.field($1, enabled ? 1 : 0) })
    case .claim:
        body = BandWire.field(14, BandWire.field(1, count.map { BandWire.field(1, $0) } ?? Data()))
    case .inspect(let id):
        body = BandWire.field(14, BandWire.field(2, BandWire.field(4, UInt64(returnedID ?? id)) + BandWire.field(3, name)))
    default:
        // The diagnostic must never snapshot, read, or write a setting value.
        throw CapabilityFixtureError.unexpectedSettingOperation
    }
    return BandWire.field(1, request.id) + BandWire.field(2, 1) + body
}

private func runCapabilityInspection(count: UInt64? = 27, names: [Int: String] = [:],
                                     mismatched: Set<Int> = [], timedOut: Set<Int> = [],
                                     malformed: Set<Int> = [], recovering: Bool = false,
                                     stopBeforeSnapshot: Bool = false) throws
    -> (BandModelCapture, [BandModelCapture.Operation]) {
    let capture = BandModelCapture()
    if recovering { try capture.recoverNormalMode(at: 0) }
    else { try capture.start(at: 0) }
    var operations: [BandModelCapture.Operation] = []
    var time = 0.0
    while let request = capture.next(at: time) {
        try #require(operations.count < 80)
        operations.append(request.operation)
        if stopBeforeSnapshot, case .snapshot = request.operation { return (capture, operations) }
        var name = Data("other-setting".utf8)
        var returned: Int?
        if case .inspect(let id) = request.operation {
            if timedOut.contains(id) { time += 1.01; continue }
            name = Data((names[id] ?? "other-setting").utf8)
            if malformed.contains(id) { name = Data([0xff, 0, 0x0a]) }
            if mismatched.contains(id) { returned = id + 1 }
        }
        let reply = try capabilityReply(request, count: count, name: name, returnedID: returned)
        #expect(capture.receive(channel: request.channel, payload: reply, at: time + 0.01))
        time += 0.02
    }
    return (capture, operations)
}

@Suite("Read-only handwriting capabilities")
struct BandModelCapabilityTests {
    @Test func smallTableIsInspectedWithoutReadingOrWritingSettingValues() throws {
        let (capture, operations) = try runCapabilityInspection(names: [27: "standby-gesture"])
        #expect(operations == [.streams(true), .claim] + (1...27).map(BandModelCapture.Operation.inspect) + [.streams(false)])
        #expect(capture.status.phase == .finished)
        #expect(capture.status.restorationVerified)
        #expect(capture.status.problem?.contains("not exposed") == true)
        #expect(capture.status.problem?.contains("27 settings checked") == true)
        #expect(!capture.streamWanted)
    }

    @Test func resolvedNamesRequireTypedSnapshotsBeforeAnyModelWrite() throws {
        let (capture, operations) = try runCapabilityInspection(count: 4,
                                                               names: [2: "data-collection", 4: "data-collection-model"],
                                                               stopBeforeSnapshot: true)
        #expect(operations == [.streams(true), .claim, .inspect(1), .inspect(2), .inspect(3), .inspect(4), .snapshot(2)])
        #expect(capture.pending?.collectionID == 2)
        capture.restore(at: 1)
        let stop = try #require(capture.next(at: 1))
        #expect(stop.operation == .streams(false))
        capture.receive(channel: stop.channel, payload: try capabilityReply(stop), at: 1.01)
        #expect(capture.next(at: 1.02) == nil)
        #expect(capture.status.restorationVerified)
        #expect(capture.status.problem == nil)
    }

    @Test func duplicateKnownNamesAreAmbiguousAndUnknownNamesStayPrivate() throws {
        let (capture, _) = try runCapabilityInspection(count: 4,
                                                       names: [1: "fixture-private-name", 2: "data-collection", 3: "data-collection",
                                                               4: "data-collection-model"])
        #expect(capture.status.restorationVerified)
        #expect(capture.status.problem?.contains("ambiguous") == true)
        #expect(capture.status.problem?.contains("fixture-private-name") == false)
    }

    @Test func mismatchedAndMalformedDescriptionsCannotEstablishMissingControls() throws {
        let (capture, _) = try runCapabilityInspection(count: 4,
                                                       names: [1: "data-collection", 2: "data-collection-model"],
                                                       mismatched: [1], malformed: [2])
        #expect(capture.status.restorationVerified)
        #expect(capture.status.problem?.contains("could not be fully identified") == true)
        #expect(capture.status.problem?.contains("2 of 4") == true)
        #expect(capture.status.problem?.contains("not exposed") == false)
        #expect(capture.status.problem?.contains("data-collection:") == false)
    }

    @Test func anUnansweredDescriptionIsSkippedWithinTheBoundedInspection() throws {
        let (capture, operations) = try runCapabilityInspection(count: 3, timedOut: [2])
        #expect(operations == [.streams(true), .claim, .inspect(1), .inspect(2), .inspect(3), .streams(false)])
        #expect(capture.status.restorationVerified)
        #expect(capture.status.problem?.contains("2 of 3") == true)
    }

    @Test(arguments: [UInt64(0), 129, UInt64.max])
    func invalidExplicitCountsDoNotStartInspectionOrSettingWrites(count: UInt64) throws {
        let (capture, operations) = try runCapabilityInspection(count: count)
        #expect(operations == [.streams(true), .claim, .streams(false)])
        #expect(capture.status.restorationVerified)
        #expect(capture.status.problem == "claiming model controls: the band returned an unsupported model settings schema")
    }

    @Test func aMissingCountDoesNotMasqueradeAsAnExplicitZero() throws {
        let (capture, operations) = try runCapabilityInspection(count: nil)
        #expect(operations == [.streams(true), .claim, .streams(false)])
        #expect(capture.status.restorationVerified)
        #expect(capture.status.problem == "claiming model controls: the band returned an unsupported model settings schema")
    }

    @Test func cancellingInspectionIgnoresItsLateReplyAndOnlyStopsStreams() throws {
        let capture = BandModelCapture()
        try capture.start(at: 0)
        for time in [0.0, 0.02] {
            let request = try #require(capture.next(at: time))
            capture.receive(channel: request.channel, payload: try capabilityReply(request, count: 3), at: time + 0.01)
        }
        let old = try #require(capture.next(at: 0.04))
        #expect(old.operation == .inspect(1))
        capture.restore(at: 0.05)
        let stop = try #require(capture.next(at: 0.05))
        #expect(stop.operation == .streams(false))
        #expect(!capture.receive(channel: old.channel, payload: try capabilityReply(old), at: 0.06))
        #expect(capture.pending?.id == stop.id)
        capture.receive(channel: stop.channel, payload: try capabilityReply(stop), at: 0.07)
        #expect(capture.next(at: 0.08) == nil)
        #expect(capture.status.phase == .finished && capture.status.restorationVerified)
        #expect(capture.status.problem == nil)
    }

    @Test(arguments: [false, true])
    func recoveryWithAnUnfamiliarTableNeverWritesAssumedNormalValues(incomplete: Bool) throws {
        let (capture, operations) = try runCapabilityInspection(count: 3,
                                                               names: [1: "data-collection"],
                                                               timedOut: incomplete ? [3] : [],
                                                               recovering: true)
        #expect(operations == [.claim, .inspect(1), .inspect(2), .inspect(3)])
        #expect(capture.status.phase == .finished)
        #expect(!capture.status.restorationVerified)
        let expected = incomplete ? "could not be fully identified" : "not exposed"
        #expect(capture.status.problem?.contains(expected) == true)
    }
}
