import Foundation
import Testing
@testable import KinesisCore

@Suite("Phone USB line protocol")
struct PhoneUSBWireTests {
    private let statusLine = Data("AXOUSB 3 010000007856341201010000".utf8)

    @Test func acceptsOnlyCompleteVersionedStatus() throws {
        let status = try #require(PhoneUSBWire.status(from: statusLine))
        #expect(status.session == 0x12345678)
        #expect(status.outputReady)
        #expect(status.state == .disarmed)
        for line in ["AXOUSB 1 010000007856341201010000", "AXOUSB 2 010000007856341201010000", "AXOUSB 4 010000007856341201010000", "AXOUSB 3 01000000785634120101000g",
                     "AXOUSB 3 0100000078563412010100000", "AXOUSB 3 0100000078563412010100",
                     "AXOUSB 3 010000000000000001010000", "Pairing open: 123456"] {
            #expect(PhoneUSBWire.status(from: Data(line.utf8)) == nil)
        }
    }

    @Test func handlesFragmentedFramesBootNoiseAndMultipleLines() throws {
        var parser = PhoneUSBStatusParser()
        #expect(parser.append(Data("boot noise\nAXOUSB 3 01000000".utf8)).isEmpty)
        let statuses = parser.append(Data("7856341201010000\r\n".utf8) + statusLine + Data([10]))
        #expect(statuses.count == 2)
        #expect(statuses.allSatisfy { $0.session == 0x12345678 })
    }

    @Test func rejectsOverlongLinesThenRecoversAtNewline() {
        var parser = PhoneUSBStatusParser()
        #expect(parser.append(Data(repeating: 65, count: 20_000) + statusLine + Data([10])).isEmpty)
        #expect(parser.append(statusLine + Data([10])).count == 1)
        _ = parser.append(Data("AXOUSB 3 01000000".utf8))
        parser.reset()
        #expect(parser.append(Data("7856341201010000\n".utf8)).isEmpty)
    }

    @Test func encodesExistingCommandWithExactConsoleEnvelope() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try #require(PhoneUSBWire.status(from: statusLine)))
        let command = try sequencer.next(.arm)
        #expect(PhoneUSBWire.command(command) == Data("USB 010101007856341200000000\n".utf8))
        #expect(PhoneUSBWire.hello == Data("HELLO\n".utf8))
        #expect(PhoneUSBWire.envelopeVersion == 3)
        #expect(PhoneBridgeWire.version == 1)
    }
}
