import CoreBluetooth
import Foundation
import Testing
@testable import Kinesis

@Suite("Band input channel discovery")
@MainActor
struct BandInputChannelTests {
    @Test func preservesTheLegacyBandChannel() {
        #expect(NativeBandConnection.inputPSM(from: Data([0xff, 0x00])) == 255)
    }

    @Test func acceptsAdvertisedDynamicChannelsIncludingEvenValues() {
        // LE SPSMs may be even; BR/EDR's odd-PSM restriction does not apply.
        #expect(NativeBandConnection.inputPSM(from: Data([0x80, 0x00])) == 128)
        #expect(NativeBandConnection.inputPSM(from: Data([0x81, 0x00])) == 129)
        #expect(NativeBandConnection.inputPSM(from: Data([0xfe, 0x00])) == 254)
    }

    @Test func readsASlicedValueFromItsActualStartIndex() {
        let bytes = Data([0x5a, 0x80, 0x00, 0xa5])
        let slice = bytes[1..<3]
        #expect(slice.startIndex == 1)
        #expect(NativeBandConnection.inputPSM(from: slice) == 128)
    }

    @Test func rejectsMissingOrMalformedValuesWithoutFallback() {
        #expect(NativeBandConnection.inputPSM(from: nil) == nil)
        #expect(NativeBandConnection.inputPSM(from: Data()) == nil)
        #expect(NativeBandConnection.inputPSM(from: Data([0xff])) == nil)
        #expect(NativeBandConnection.inputPSM(from: Data([0xff, 0x00, 0x00])) == nil)
    }

    @Test func rejectsZeroAndSIGAssignedChannels() {
        #expect(NativeBandConnection.inputPSM(from: Data([0x00, 0x00])) == nil)
        #expect(NativeBandConnection.inputPSM(from: Data([0x01, 0x00])) == nil)
        #expect(NativeBandConnection.inputPSM(from: Data([0x7f, 0x00])) == nil)
    }

    @Test func rejectsReservedRangesAndReversedByteOrder() {
        #expect(NativeBandConnection.inputPSM(from: Data([0x00, 0x01])) == nil)
        #expect(NativeBandConnection.inputPSM(from: Data([0xff, 0xff])) == nil)
        #expect(NativeBandConnection.inputPSM(from: Data([0x00, 0xff])) == nil)
        #expect(NativeBandConnection.inputPSM(from: Data([0x00, 0x80])) == nil)
    }
}
