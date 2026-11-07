import Foundation
import Testing
@testable import KinesisCore

@Suite("Phone adapter wire protocol")
struct PhoneBridgeProtocolTests {
    private func bytes(armed: Bool = false, sequence: UInt16 = 0,
                       session: UInt32 = 0x12345678, reason: UInt8 = 1,
                       outputReady: Bool = true) -> Data {
        Data([1, armed ? 1 : 0,
              UInt8(truncatingIfNeeded: sequence), UInt8(truncatingIfNeeded: sequence >> 8),
              UInt8(truncatingIfNeeded: session), UInt8(truncatingIfNeeded: session >> 8),
              UInt8(truncatingIfNeeded: session >> 16), UInt8(truncatingIfNeeded: session >> 24),
              reason, outputReady ? 1 : 0, 0, 0])
    }

    private func status(armed: Bool = false, sequence: UInt16 = 0,
                        session: UInt32 = 0x12345678, reason: UInt8 = 1,
                        outputReady: Bool = true) throws -> PhoneBridgeStatus {
        try #require(PhoneBridgeStatus(data: bytes(armed: armed, sequence: sequence,
            session: session, reason: reason, outputReady: outputReady)))
    }

    @Test func decodesExactLittleEndianStatusAndRetainsUnknownReasons() throws {
        let value = try status(armed: true, sequence: 0xabcd, reason: 255)
        #expect(value.state == .armed)
        #expect(value.lastAcceptedSequence == 0xabcd)
        #expect(value.session == 0x12345678)
        #expect(value.reason == 255)
        #expect(value.outputReady)
        #expect(PhoneBridgeWire.messageLength == 12)
        #expect(Set([PhoneBridgeWire.serviceUUID, PhoneBridgeWire.commandUUID,
                    PhoneBridgeWire.statusUUID]).count == 3)
    }

    @Test func rejectsMalformedStatusWithoutReadingOutsideTheMessage() {
        for length in 0..<12 {
            #expect(PhoneBridgeStatus(data: Data(bytes().prefix(length))) == nil)
        }
        #expect(PhoneBridgeStatus(data: bytes() + Data([0])) == nil)
        for (index, value): (Int, UInt8) in [(0, 0), (0, 2), (1, 2), (9, 2), (10, 1), (11, 1)] {
            var malformed = bytes()
            malformed[index] = value
            #expect(PhoneBridgeStatus(data: malformed) == nil)
        }
        #expect(PhoneBridgeStatus(data: bytes(session: 0)) == nil)
    }

    @Test func encodesArmHeartbeatAndDisarmWithSessionAndStrictSequences() throws {
        var sequencer = PhoneBridgeSequencer()
        #expect(sequencer.update(status: try status()) == true)
        let arm = try sequencer.next(.arm)
        #expect(arm.operation == .arm)
        #expect(arm.sequence == 1)
        #expect(arm.session == 0x12345678)
        #expect(arm.data == Data([1, 1, 1, 0, 0x78, 0x56, 0x34, 0x12, 0, 0, 0, 0]))
        sequencer.update(status: try status(armed: true, sequence: 1))
        #expect(try sequencer.next(.heartbeat).data
            == Data([1, 3, 2, 0, 0x78, 0x56, 0x34, 0x12, 0, 0, 0, 0]))
        #expect(try sequencer.next(.disarm).data
            == Data([1, 2, 3, 0, 0x78, 0x56, 0x34, 0x12, 0, 0, 0, 0]))
        #expect(!sequencer.isArmed)
    }

    @Test func encodesOnlyMomentaryTypedNavigationActions() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try status())
        _ = try sequencer.next(.arm)
        sequencer.update(status: try status(armed: true, sequence: 1))
        let key = PhoneNavigationAction.key(PhoneKeyboardChord(.tab, modifiers: [.command, .shift]))
        #expect(try sequencer.next(.action(key)).data
            == Data([1, 4, 2, 0, 0x78, 0x56, 0x34, 0x12, 0x2b, 0x0a, 0, 0]))
        let wheel = PhoneNavigationAction.scroll(try #require(PhoneScroll(vertical: -127, horizontal: 127)))
        #expect(try sequencer.next(.action(wheel)).data
            == Data([1, 5, 3, 0, 0x78, 0x56, 0x34, 0x12, 0x81, 0x7f, 0, 0]))
    }

    @Test func noStatusAndUnavailableOutputPreventArming() throws {
        var sequencer = PhoneBridgeSequencer()
        #expect(throws: PhoneBridgeCommandError.noSession) { try sequencer.next(.arm) }
        sequencer.update(status: try status(outputReady: false))
        #expect(throws: PhoneBridgeCommandError.outputUnavailable) { try sequencer.next(.arm) }
        #expect(try sequencer.next(.disarm).sequence == 1)
    }

    @Test func pointerMovementAddsOpcodeSixWithoutChangingBinaryVersion() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try status())
        _ = try sequencer.next(.arm)
        sequencer.update(status: try status(armed: true, sequence: 1))
        let movement = try #require(PhonePointerMove(dx: -127, dy: 127))
        #expect(try sequencer.next(.action(.move(movement))).data
            == Data([1, 6, 2, 0, 0x78, 0x56, 0x34, 0x12, 0x81, 0x7f, 0, 0]))
        #expect(PhoneBridgeWire.version == 1)
    }

    @Test func leftClickAddsOnlyOpcodeSevenAndZeroArguments() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try status())
        #expect(throws: PhoneBridgeCommandError.notArmed) { try sequencer.next(.action(.click)) }
        _ = try sequencer.next(.arm)
        sequencer.update(status: try status(armed: true, sequence: 1))
        #expect(try sequencer.next(.action(.click)).data
            == Data([1, 7, 2, 0, 0x78, 0x56, 0x34, 0x12, 0, 0, 0, 0]))
        _ = try sequencer.next(.disarm)
        #expect(throws: PhoneBridgeCommandError.notArmed) { try sequencer.next(.action(.click)) }
    }

    @Test func requiresExplicitLocalArmAndAnAcknowledgementBeforeActions() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try status(armed: true, sequence: 7))
        #expect(!sequencer.isArmed)
        #expect(throws: PhoneBridgeCommandError.notArmed) { try sequencer.next(.heartbeat) }
        #expect(throws: PhoneBridgeCommandError.notArmed) { try sequencer.next(.action(.activate)) }
        #expect(try sequencer.next(.arm).sequence == 8)
        #expect(!sequencer.isArmed)
        sequencer.update(status: try status(armed: true, sequence: 7))
        #expect(!sequencer.isArmed)
        sequencer.update(status: try status(armed: true, sequence: 8))
        #expect(sequencer.isArmed)
        #expect(try sequencer.next(.action(.activate)).sequence == 9)
    }

    @Test func pendingArmSurvivesAnEarlierStatusButNotConfirmedDisarm() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try status())
        _ = try sequencer.next(.arm)
        sequencer.update(status: try status())
        #expect(!sequencer.isArmed)
        sequencer.update(status: try status(armed: true, sequence: 1))
        #expect(sequencer.isArmed)
        sequencer.update(status: try status(armed: false, sequence: 1, reason: 6))
        #expect(!sequencer.isArmed)
        sequencer.update(status: try status(armed: true, sequence: 1))
        #expect(!sequencer.isArmed)
    }

    @Test func newAdapterSessionClearsArmingAndRestartsSequence() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try status())
        _ = try sequencer.next(.arm)
        sequencer.update(status: try status(armed: true, sequence: 1))
        _ = try sequencer.next(.heartbeat)
        #expect(sequencer.update(status: try status(session: 0x90abcdef)) == true)
        #expect(!sequencer.isArmed)
        #expect(throws: PhoneBridgeCommandError.notArmed) { try sequencer.next(.action(.activate)) }
        let command = try sequencer.next(.arm)
        #expect(command.sequence == 1)
        #expect(command.session == 0x90abcdef)
    }

    @Test func resetRemovesSessionEvenIfOldAdapterStatusWasArmed() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try status())
        _ = try sequencer.next(.arm)
        sequencer.update(status: try status(armed: true, sequence: 1))
        sequencer.reset()
        #expect(sequencer.status == nil)
        #expect(!sequencer.isArmed)
        #expect(throws: PhoneBridgeCommandError.noSession) { try sequencer.next(.action(.activate)) }
        sequencer.update(status: try status(armed: true, sequence: 1))
        #expect(!sequencer.isArmed)
    }

    @Test func ignoresOlderAcknowledgementsAndNeverReusesPreparedSequence() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try status())
        _ = try sequencer.next(.arm)
        sequencer.update(status: try status(armed: true, sequence: 1))
        #expect(try sequencer.next(.action(.activate)).sequence == 2)
        #expect(try sequencer.next(.heartbeat).sequence == 3)
        sequencer.update(status: try status(armed: true, sequence: 2))
        #expect(sequencer.update(status: try status(armed: false, sequence: 1)) == false)
        #expect(sequencer.isArmed)
        #expect(try sequencer.next(.heartbeat).sequence == 4)
    }

    @Test func unavailableOutputClearsLocalArmingAndCannotSilentlyRearm() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try status())
        _ = try sequencer.next(.arm)
        sequencer.update(status: try status(armed: true, sequence: 1))
        sequencer.update(status: try status(armed: false, sequence: 1, reason: 5, outputReady: false))
        #expect(!sequencer.isArmed)
        sequencer.update(status: try status(armed: true, sequence: 1))
        #expect(!sequencer.isArmed)
        #expect(try sequencer.next(.arm).sequence == 2)
    }

    @Test func sequenceReachesMaximumWithoutWrappingToReplayOldCommands() throws {
        var sequencer = PhoneBridgeSequencer()
        sequencer.update(status: try status(sequence: UInt16.max - 1))
        let last = try sequencer.next(.arm)
        #expect(last.sequence == UInt16.max)
        #expect(Array(last.data)[2...3] == [0xff, 0xff])
        sequencer.update(status: try status(armed: true, sequence: UInt16.max))
        #expect(throws: PhoneBridgeCommandError.sequenceExhausted) { try sequencer.next(.heartbeat) }
        #expect(throws: PhoneBridgeCommandError.sequenceExhausted) { try sequencer.next(.disarm) }
        sequencer.update(status: try status(session: 123))
        #expect(try sequencer.next(.arm).sequence == 1)
    }
}
