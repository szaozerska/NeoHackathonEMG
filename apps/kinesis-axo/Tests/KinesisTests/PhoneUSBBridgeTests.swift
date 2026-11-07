import Foundation
import Testing
@testable import Kinesis
import KinesisCore

@MainActor
private final class FakePhoneSerial: PhoneUSBSerialPort {
    var incoming = Data()
    var writes = [Data]()
    var writeLimit = Int.max
    var failsRead = false
    var closed = false
    func readAvailable() throws -> Data {
        if failsRead { throw CocoaError(.fileReadUnknown) }
        let result = incoming
        incoming.removeAll()
        return result
    }
    func write(_ data: Data) throws -> Int {
        let count = min(data.count, writeLimit)
        writes.append(Data(data.prefix(count)))
        return count
    }
    func close() { closed = true }
    func status(armed: Bool = false, sequence: UInt16 = 0, session: UInt32 = 0x12345678,
                ready: Bool = true) {
        let bytes: [UInt8] = [1, armed ? 1 : 0, UInt8(truncatingIfNeeded: sequence),
            UInt8(truncatingIfNeeded: sequence >> 8), UInt8(truncatingIfNeeded: session),
            UInt8(truncatingIfNeeded: session >> 8), UInt8(truncatingIfNeeded: session >> 16),
            UInt8(truncatingIfNeeded: session >> 24), 1, ready ? 1 : 0, 0, 0]
        incoming.append(Data(("AXOUSB 3 " + bytes.map { String(format: "%02x", $0) }.joined() + "\n").utf8))
    }
}

@MainActor
private final class USBFixture {
    let serial = FakePhoneSerial()
    var now = 100.0
    lazy var bridge = PhoneUSBBridge(enumeratePorts: { ["/dev/cu.usbtest"] },
        openPort: { [unowned self] _ in self.serial }, clock: { [unowned self] in self.now },
        automaticallyTicks: false)
    func connected() {
        bridge.connect()
        serial.status()
        bridge.tick()
    }
    func armed() {
        connected()
        bridge.arm()
        bridge.tick()
        serial.status(armed: true, sequence: 1)
        bridge.tick()
    }
}

@Suite("Phone USB forwarding", .serialized)
@MainActor
struct PhoneUSBBridgeTests {
    @Test func openingSendsOnlyHelloAndNeverAutomaticallyArms() {
        let fixture = USBFixture()
        fixture.bridge.connect()
        #expect(fixture.bridge.connected)
        #expect(fixture.serial.writes == [PhoneUSBWire.hello])
        fixture.serial.status(armed: true, sequence: 12)
        fixture.bridge.tick()
        #expect(fixture.bridge.ready)
        #expect(!fixture.bridge.armed)
        #expect(!fixture.bridge.send(action: .activate))
        #expect(!fixture.serial.writes.contains { String(decoding: $0, as: UTF8.self).contains("PAIR") })
    }

    @Test func rejectsNonUSBPathsBeforeOpeningAnything() {
        var opened = false
        let serial = FakePhoneSerial()
        let bridge = PhoneUSBBridge(enumeratePorts: { ["/dev/cu.Bluetooth-Incoming-Port", "/dev/cu.usb/../other"] },
            openPort: { _ in opened = true; return serial }, automaticallyTicks: false)
        bridge.selectedPort = "/dev/cu.Bluetooth-Incoming-Port"
        bridge.connect()
        #expect(!bridge.connected)
        #expect(!opened)
        #expect(bridge.ports.isEmpty)
    }

    @Test func armsOnlyAfterMatchingAcknowledgementAndSerializesActions() throws {
        let fixture = USBFixture()
        fixture.connected()
        fixture.bridge.arm()
        fixture.bridge.tick()
        #expect(!fixture.bridge.armed)
        #expect(fixture.bridge.busy)
        fixture.serial.status(sequence: 0)
        fixture.bridge.tick()
        #expect(!fixture.bridge.armed)
        fixture.serial.status(armed: true, sequence: 1)
        fixture.bridge.tick()
        #expect(fixture.bridge.armed)
        let scroll = PhoneNavigationAction.scroll(try #require(PhoneScroll(vertical: -4)))
        #expect(fixture.bridge.send(action: scroll))
        #expect(!fixture.bridge.send(action: scroll))
        fixture.bridge.tick()
        fixture.serial.status(armed: true, sequence: 2)
        fixture.bridge.tick()
        #expect(!fixture.bridge.busy)
        #expect(fixture.bridge.send(action: scroll))
        #expect(!fixture.bridge.send(action: scroll))
        fixture.bridge.tick()
        #expect(String(decoding: fixture.serial.writes.last ?? Data(), as: UTF8.self)
            .hasPrefix("USB 01050300"))
    }

    @Test func wheelAcknowledgementsAllowTheNextFrameWithoutAnArtificialSettleDelay() throws {
        let fixture = USBFixture()
        fixture.armed()
        let scroll = PhoneNavigationAction.scroll(try #require(PhoneScroll(vertical: -2)))
        for sequence in UInt16(2)...UInt16(21) {
            #expect(fixture.bridge.send(action: scroll))
            fixture.bridge.tick()
            #expect(fixture.bridge.busy)
            #expect(!fixture.bridge.send(action: scroll))
            // An independent status receipt is required for each wheel report.
            fixture.now += 0.02
            fixture.serial.status(armed: true, sequence: sequence)
            fixture.bridge.tick()
            #expect(!fixture.bridge.busy)
        }
        let wheelLines = fixture.serial.writes.filter {
            String(decoding: $0, as: UTF8.self).hasPrefix("USB 0105")
        }
        #expect(wheelLines.count == 20)
        #expect(Set(wheelLines).count == 20)
        #expect(abs(fixture.now - 100.4) < 0.000_001)
    }

    @Test func keyboardAcknowledgementStillWaitsForItsReleaseSettleInterval() {
        let fixture = USBFixture()
        fixture.armed()
        #expect(fixture.bridge.send(action: .activate))
        fixture.bridge.tick()
        fixture.serial.status(armed: true, sequence: 2)
        fixture.bridge.tick()
        #expect(fixture.bridge.busy)
        #expect(!fixture.bridge.send(action: .activate))
        fixture.now += 0.101
        fixture.bridge.tick()
        #expect(!fixture.bridge.busy)
        #expect(fixture.bridge.send(action: .activate))
    }

    @Test func pointerMovementRequiresArmingAndItsOwnAcknowledgementWithoutASettleDelay() throws {
        let fixture = USBFixture()
        fixture.connected()
        let action = PhoneNavigationAction.move(try #require(PhonePointerMove(dx: 48, dy: -48)))
        #expect(!fixture.bridge.send(action: action))
        fixture.bridge.arm()
        fixture.bridge.tick()
        fixture.serial.status(armed: true, sequence: 1)
        fixture.bridge.tick()
        #expect(fixture.bridge.send(action: action))
        #expect(!fixture.bridge.send(action: action))
        fixture.bridge.tick()
        #expect(String(decoding: fixture.serial.writes.last ?? Data(), as: UTF8.self)
            == "USB 010602007856341230d00000\n")
        fixture.serial.status(armed: true, sequence: 2)
        fixture.bridge.tick()
        #expect(!fixture.bridge.busy)
        #expect(fixture.bridge.send(action: action))
    }

    @Test func clickAcknowledgementReservesItsMomentaryReleaseInterval() {
        let fixture = USBFixture()
        fixture.connected()
        #expect(!fixture.bridge.send(action: .click))
        fixture.bridge.arm()
        fixture.bridge.tick()
        fixture.serial.status(armed: true, sequence: 1)
        fixture.bridge.tick()
        #expect(fixture.bridge.send(action: .click))
        #expect(!fixture.bridge.send(action: .click))
        fixture.bridge.tick()
        #expect(String(decoding: fixture.serial.writes.last ?? Data(), as: UTF8.self)
            == "USB 010702007856341200000000\n")
        fixture.serial.status(armed: true, sequence: 2)
        fixture.bridge.tick()
        #expect(fixture.bridge.busy)
        fixture.now += 0.099
        fixture.bridge.tick()
        #expect(fixture.bridge.busy)
        #expect(!fixture.bridge.send(action: .click))
        fixture.now += 0.002
        fixture.bridge.tick()
        #expect(!fixture.bridge.busy)
        #expect(fixture.bridge.send(action: .click))
    }

    @Test func missingClickAcknowledgementCannotReplayThePress() {
        let fixture = USBFixture()
        fixture.armed()
        #expect(fixture.bridge.send(action: .click))
        fixture.bridge.tick()
        fixture.now += 0.51
        fixture.bridge.tick()
        #expect(!fixture.bridge.connected && !fixture.bridge.armed)
        #expect(fixture.serial.writes.filter {
            String(decoding: $0, as: UTF8.self).hasPrefix("USB 0107")
        }.count == 1)
        #expect(!fixture.bridge.send(action: .click))
    }

    @Test func missingAcknowledgementDisarmsClosesAndNeverRetriesAction() {
        let fixture = USBFixture()
        fixture.armed()
        #expect(fixture.bridge.send(action: .activate))
        fixture.bridge.tick()
        let action = fixture.serial.writes.last
        fixture.now += 0.51
        fixture.bridge.tick()
        #expect(!fixture.bridge.connected)
        #expect(!fixture.bridge.armed)
        #expect(fixture.serial.closed)
        #expect(fixture.serial.writes.filter { $0 == action }.count == 1)
    }

    @Test func newPhoneSessionCancelsOutputAndRequiresManualArm() {
        let fixture = USBFixture()
        fixture.armed()
        var boundaries = 0
        fixture.bridge.onBoundary = { boundaries += 1 }
        fixture.serial.status(armed: true, session: 55)
        fixture.bridge.tick()
        #expect(boundaries >= 1)
        #expect(!fixture.bridge.armed)
        #expect(!fixture.bridge.send(action: .activate))
        fixture.serial.status(armed: true, sequence: 5, session: 55)
        fixture.bridge.tick()
        #expect(!fixture.bridge.armed)
    }

    @Test func explicitDisarmWhileActionIsPendingBlocksFurtherActions() {
        let fixture = USBFixture()
        fixture.armed()
        #expect(fixture.bridge.send(action: .activate))
        fixture.bridge.tick()
        fixture.bridge.disarm()
        #expect(!fixture.bridge.armed)
        #expect(!fixture.bridge.send(action: .activate))
        fixture.serial.status(armed: true, sequence: 2)
        fixture.bridge.tick()
        #expect(!fixture.bridge.armed)
        #expect(String(decoding: fixture.serial.writes.last ?? Data(), as: UTF8.self)
            .hasPrefix("USB 01020300"))
        fixture.serial.status(armed: false, sequence: 3)
        fixture.bridge.tick()
        #expect(!fixture.bridge.armed)
    }

    @Test func partialWritesRetainOnlyTheUnsentSuffix() {
        let fixture = USBFixture()
        fixture.serial.writeLimit = 2
        fixture.bridge.connect()
        for _ in 0..<4 { fixture.bridge.tick() }
        #expect(fixture.serial.writes.reduce(Data(), +) == PhoneUSBWire.hello)
        fixture.serial.status()
        fixture.bridge.tick()
        fixture.bridge.arm()
        for _ in 0..<20 { fixture.bridge.tick() }
        let combined = fixture.serial.writes.reduce(Data(), +)
        #expect(String(decoding: combined, as: UTF8.self) == "HELLO\nUSB 010101007856341200000000\n")
    }

    @Test func oldFirmwareTimeoutProvidesUpdateMessageWithoutSendingInput() {
        let fixture = USBFixture()
        fixture.bridge.connect()
        fixture.serial.incoming = Data("Axo bridge ready, disarmed.\nAXOUSB 2 010000007856341201010000\n".utf8)
        fixture.bridge.tick()
        #expect(!fixture.bridge.ready)
        fixture.bridge.arm()
        #expect(!fixture.bridge.armed)
        fixture.now += 5.01
        fixture.bridge.tick()
        #expect(!fixture.bridge.connected)
        #expect(fixture.bridge.statusText.contains("firmware"))
        #expect(fixture.serial.writes.allSatisfy { $0 == PhoneUSBWire.hello })
    }

    @Test func sendsHeartbeatAndStopsWhenStatusStops() {
        let fixture = USBFixture()
        fixture.armed()
        fixture.now += 0.41
        fixture.bridge.tick()
        #expect(String(decoding: fixture.serial.writes.last ?? Data(), as: UTF8.self)
            .hasPrefix("USB 01030200"))
        fixture.serial.status(armed: true, sequence: 2)
        fixture.bridge.tick()
        fixture.now += 1.01
        fixture.bridge.tick()
        #expect(!fixture.bridge.connected)
        #expect(fixture.serial.closed)
    }
}
