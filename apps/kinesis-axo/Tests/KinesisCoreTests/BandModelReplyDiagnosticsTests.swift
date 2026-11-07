import Foundation
import Testing
@testable import KinesisCore

@Suite("Model reply structural diagnostics")
struct BandModelReplyDiagnosticsTests {
    @Test func wireShapeContainsOnlyFieldNumbersKindsAndMultiplicities() throws {
        let first = BandWire.field(1, 879244661177) + BandWire.field(1, 999)
            + BandWire.field(2, Data("fixture-private-token".utf8))
        let second = BandWire.field(1, 1) + BandWire.field(1, 2)
            + BandWire.field(2, Data("different-private-contents-and-length".utf8))
        let expected = "1:int(2);2:bytes(1)"
        #expect(try ProtoFields(first).wireShape == expected)
        #expect(try ProtoFields(second).wireShape == expected)
    }

    @Test(arguments: [19, 20]) func settingReplySummaryIdentifiesTheStageWithoutValues(setting: Int) {
        let request = BandModelCapture.Request(id: 0x10000001, operation: .snapshot(setting),
                                               deadline: 5, collectionID: 19)
        let privateBytes = Data("fixture-token-password-phone-email-blob-private".utf8)
        let nested = BandWire.field(1, UInt64(setting)) + BandWire.field(2, 0)
            + BandWire.field(3, 879244661177) + BandWire.field(8, privateBytes)
        let payload = BandWire.field(1, request.id) + BandWire.field(2, 1)
            + BandWire.field(14, BandWire.field(3, nested))
        let summary = BandModelCapture.replyDiagnostic(request, payload: payload)
        #expect(summary.contains(setting == 19 ? "reading collection setting" : "reading model setting"))
        #expect(summary.contains("setting=\(setting)"))
        #expect(summary.contains("rpc=[1:int(1);2:int(1);14:bytes(1)]"))
        #expect(summary.contains("wrapper14=[3:bytes(1)]"))
        #expect(summary.contains("response14.3=[1:int(1);2:int(1);3:int(1);8:bytes(1)]"))
        #expect(!summary.contains("fixture"))
        #expect(!summary.contains("879244661177"))
        #expect(!summary.contains(String(request.id)))
        #expect(summary.utf8.count <= 512)
    }

    @Test func descriptorNamesAndConfigurationBytesNeverEnterTheSummary() {
        let marker = Data("fixture-private-description".utf8)
        let descriptor = BandModelCapture.Request(id: 42, operation: .inspect(19), deadline: 5, collectionID: 19)
        let descriptorPayload = BandWire.field(1, descriptor.id) + BandWire.field(2, 1)
            + BandWire.field(14, BandWire.field(2, BandWire.field(3, marker) + BandWire.field(4, 19)))
        let description = BandModelCapture.replyDiagnostic(descriptor, payload: descriptorPayload)
        #expect(description.contains("response14.2=[3:bytes(1);4:int(1)]"))
        #expect(!description.contains("fixture-private-description"))

        let config = BandModelCapture.Request(id: 43, operation: .config, deadline: 5)
        let configPayload = BandWire.field(1, config.id) + BandWire.field(2, 1)
            + BandWire.field(6, BandWire.field(99, marker))
        let configuration = BandModelCapture.replyDiagnostic(config, payload: configPayload)
        #expect(configuration.contains("reading model configuration"))
        #expect(configuration.contains("config6=[99:bytes(1)]"))
        #expect(!configuration.contains("fixture-private-description"))
    }

    @Test func largeOrMalformedShapesHaveBoundedGenericSummaries() throws {
        let many = (1...100).reduce(into: Data()) {
            $0 += BandWire.field($1, Data("fixture-private-marker".utf8))
        }
        #expect(try ProtoFields(many).wireShape.utf8.count <= 96)
        let request = BandModelCapture.Request(id: 1, operation: .snapshot(19), deadline: 5, collectionID: 19)
        let summary = BandModelCapture.replyDiagnostic(request, payload: many)
        #expect(summary.utf8.count <= 512)
        #expect(!summary.contains("fixture-private-marker"))
        let malformed = BandModelCapture.replyDiagnostic(request, payload: Data([0xff]))
        #expect(malformed.contains("rpc=[invalid]"))
        #expect(malformed.contains("response14.3=[unavailable]"))
    }
}
