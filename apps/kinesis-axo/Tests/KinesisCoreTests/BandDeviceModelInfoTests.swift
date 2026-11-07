import Foundation
import Testing
@testable import KinesisCore

private func modelInfoResponse(_ info: Data, status: UInt64 = 1, requestID: UInt64 = 1) -> Data {
    BandWire.field(1, requestID) + BandWire.field(2, status) + BandWire.field(4, info)
}

@Suite("Passive band model metadata")
struct BandDeviceModelInfoTests {
    @Test func parsesOnlyCurrentAndRepeatedAvailableModels() throws {
        let current = "fixture_current_model"
        let available = [current, "fixture_gesture_model", "hw_fixture_model", "fixture_gesture_model"]
        let info = BandWire.field(9, Data(current.utf8))
            + available.reduce(into: Data()) { $0 += BandWire.field(10, Data($1.utf8)) }
            + BandWire.field(2, Data("fixture-private-serial".utf8))
            + BandWire.field(12, Data("fixture-private-account".utf8))
        let parsed = try BandDeviceModelInfo(response: modelInfoResponse(info))
        #expect(parsed.currentID == current)
        #expect(parsed.availableIDs == [current, "fixture_gesture_model", "hw_fixture_model"])
        #expect(parsed.inventoryReported)
        #expect(!parsed.diagnostic.contains("fixture-private"))
        #expect(parsed.diagnostic.hasPrefix("Band model inventory:"))
    }

    @Test func omittedInventoryDoesNotClaimNoModelsExist() throws {
        let parsed = try BandDeviceModelInfo(response: modelInfoResponse(Data()))
        #expect(parsed.currentID == nil)
        #expect(parsed.availableIDs.isEmpty)
        #expect(!parsed.inventoryReported)
        #expect(parsed.diagnostic.contains("not reported"))
    }

    @Test(arguments: ["https://example.invalid/private", "fixture\nprivate", "fixture@private", ""])
    func rejectsInvalidIdentifiersWithoutPrintingThem(text: String) throws {
        let info = BandWire.field(10, Data(text.utf8))
        #expect(throws: BandProtocolError.self) {
            try BandDeviceModelInfo(response: modelInfoResponse(info))
        }
    }

    @Test func boundsNamesAndInventoryAndRejectsWrongWireTypes() throws {
        let overlong = BandWire.field(10, Data(repeating: 0x61, count: 97))
        let tooMany = (0...32).reduce(into: Data()) { data, id in
            data += BandWire.field(10, Data("fixture_\(id)".utf8))
        }
        for info in [overlong, tooMany, BandWire.field(10, 7)] {
            #expect(throws: BandProtocolError.self) {
                try BandDeviceModelInfo(response: modelInfoResponse(info))
            }
        }
    }

    @Test func unverifiedLegacyCurrentFieldCannotHideOrLeakAlongsideAValidInventory() throws {
        let available = BandWire.field(10, Data("hw_fixture_model".utf8))
        let repeated = BandWire.field(9, Data("fixture-private-a".utf8))
            + BandWire.field(9, Data("fixture-private-b".utf8))
        for legacy in [BandWire.field(9, 7), BandWire.field(9, Data("fixture-private-model".utf8)), repeated] {
            let parsed = try BandDeviceModelInfo(response: modelInfoResponse(available + legacy))
            #expect(parsed.availableIDs == ["hw_fixture_model"])
            #expect(parsed.currentID == nil)
            #expect(parsed.inventoryReported)
            #expect(!parsed.diagnostic.contains("fixture-private"))
        }
    }

    @Test func maximumInventoryHasABoundedDiagnostic() throws {
        let info = (0..<32).reduce(into: Data()) { data, id in
            let suffix = String(id)
            let name = String(repeating: "a", count: 96 - suffix.count) + suffix
            data += BandWire.field(10, Data(name.utf8))
        }
        let parsed = try BandDeviceModelInfo(response: modelInfoResponse(info))
        #expect(parsed.availableIDs.count == 32)
        #expect(parsed.diagnostic.utf8.count < 3300)
    }

    @Test(arguments: [UInt64(0), 2])
    func rejectsUnconfirmedReplyStatus(status: UInt64) throws {
        #expect(throws: BandProtocolError.self) {
            try BandDeviceModelInfo(response: modelInfoResponse(Data(), status: status))
        }
    }
}
