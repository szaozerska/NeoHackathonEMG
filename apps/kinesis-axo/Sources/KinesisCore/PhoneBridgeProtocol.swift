import Foundation

/// Axo's custom command service, separate from the HID reports emitted by
/// the adapter. All integers in the twelve-byte messages are little-endian.
public enum PhoneBridgeWire {
    public static let serviceUUID = "A10A0001-5D53-4A18-8F6A-1C173E442001"
    public static let commandUUID = "A10A0002-5D53-4A18-8F6A-1C173E442001"
    public static let statusUUID = "A10A0003-5D53-4A18-8F6A-1C173E442001"
    public static let version: UInt8 = 1
    public static let messageLength = 12
}

public struct PhoneBridgeStatus: Equatable, Sendable {
    public enum State: UInt8, Sendable { case disarmed = 0, armed = 1 }
    public let state: State
    /// Accepted by the adapter, not confirmation of HID delivery or a phone action.
    public let lastAcceptedSequence: UInt16
    public let session: UInt32
    /// Unknown reason values are retained for forward-compatible diagnostics.
    public let reason: UInt8
    /// The HID host is authenticated, subscribed to input reports, and active.
    /// This does not confirm delivery or that a report can be sent immediately.
    public let outputReady: Bool

    public init?(data: Data) {
        guard data.count == PhoneBridgeWire.messageLength else { return nil }
        let bytes = Array(data)
        guard bytes[0] == PhoneBridgeWire.version,
              let state = State(rawValue: bytes[1]), bytes[9] <= 1,
              bytes[10] == 0, bytes[11] == 0 else { return nil }
        let session = UInt32(bytes[4]) | UInt32(bytes[5]) << 8
            | UInt32(bytes[6]) << 16 | UInt32(bytes[7]) << 24
        guard session != 0 else { return nil }
        self.state = state
        lastAcceptedSequence = UInt16(bytes[2]) | UInt16(bytes[3]) << 8
        self.session = session
        reason = bytes[8]
        outputReady = bytes[9] == 1
    }
}

public enum PhoneBridgeOperation: Equatable, Sendable {
    case arm, disarm, heartbeat
    case action(PhoneNavigationAction)
}

public struct PhoneBridgeCommand: Equatable, Sendable {
    public let operation: PhoneBridgeOperation
    public let sequence: UInt16
    public let session: UInt32

    fileprivate init(operation: PhoneBridgeOperation, sequence: UInt16, session: UInt32) {
        self.operation = operation
        self.sequence = sequence
        self.session = session
    }

    public var data: Data {
        let opcode: UInt8
        let arg0: UInt8
        let arg1: UInt8
        switch operation {
        case .arm: (opcode, arg0, arg1) = (1, 0, 0)
        case .disarm: (opcode, arg0, arg1) = (2, 0, 0)
        case .heartbeat: (opcode, arg0, arg1) = (3, 0, 0)
        case .action(.key(let chord)):
            (opcode, arg0, arg1) = (4, chord.key.rawValue, chord.modifiers.rawValue)
        case .action(.scroll(let scroll)):
            (opcode, arg0, arg1) = (5, UInt8(bitPattern: scroll.vertical), UInt8(bitPattern: scroll.horizontal))
        case .action(.move(let movement)):
            (opcode, arg0, arg1) = (6, UInt8(bitPattern: movement.dx), UInt8(bitPattern: movement.dy))
        case .action(.click): (opcode, arg0, arg1) = (7, 0, 0)
        }
        return Data([
            PhoneBridgeWire.version, opcode,
            UInt8(truncatingIfNeeded: sequence), UInt8(truncatingIfNeeded: sequence >> 8),
            UInt8(truncatingIfNeeded: session), UInt8(truncatingIfNeeded: session >> 8),
            UInt8(truncatingIfNeeded: session >> 16), UInt8(truncatingIfNeeded: session >> 24),
            arg0, arg1, 0, 0,
        ])
    }
}

public enum PhoneBridgeCommandError: Error, LocalizedError, Equatable, Sendable {
    case noSession, outputUnavailable, notArmed, sequenceExhausted

    public var errorDescription: String? {
        switch self {
        case .noSession: "Connect to the adapter and read its status first."
        case .outputUnavailable: "Connect and authenticate the phone as an HID host, with input reports enabled."
        case .notArmed: "Arm the adapter and wait for its confirmation first."
        case .sequenceExhausted: "Reconnect the adapter before sending more commands."
        }
    }
}

/// Connection-local sequencing and explicit arming. The caller serializes GATT
/// writes and calls reset() on every disconnect, including failed connections.
/// A command is consumed when prepared: never retry an uncertain action write,
/// since it may already have reached the HID host. Read status or disconnect instead.
public struct PhoneBridgeSequencer: Sendable {
    public private(set) var status: PhoneBridgeStatus?
    private var nextSequence: UInt32 = 1
    private var armSequence: UInt16?

    public init() {}

    public var isArmed: Bool {
        guard let status, let armSequence else { return false }
        return status.state == .armed && status.outputReady
            && status.lastAcceptedSequence >= armSequence
    }

    /// Returns true when the adapter changed session, including HID connection or subscription
    /// transitions. Such a change always requires another explicit arm command.
    @discardableResult
    public mutating func update(status newStatus: PhoneBridgeStatus) -> Bool {
        let changed = status?.session != newStatus.session
        if changed {
            nextSequence = 1
            armSequence = nil
        } else if let status, newStatus.lastAcceptedSequence < status.lastAcceptedSequence {
            return false
        }
        status = newStatus
        nextSequence = max(nextSequence, UInt32(newStatus.lastAcceptedSequence) + 1)
        let disarmConfirmed = newStatus.state == .disarmed
            && (armSequence.map({ newStatus.lastAcceptedSequence >= $0 }) ?? false)
        if !newStatus.outputReady || disarmConfirmed {
            armSequence = nil
        }
        return changed
    }

    public mutating func reset() {
        status = nil
        nextSequence = 1
        armSequence = nil
    }

    public mutating func next(_ operation: PhoneBridgeOperation) throws -> PhoneBridgeCommand {
        guard let status else { throw PhoneBridgeCommandError.noSession }
        guard nextSequence <= UInt32(UInt16.max) else { throw PhoneBridgeCommandError.sequenceExhausted }
        switch operation {
        case .arm:
            guard status.outputReady else { throw PhoneBridgeCommandError.outputUnavailable }
        case .action, .heartbeat:
            guard isArmed else { throw PhoneBridgeCommandError.notArmed }
        case .disarm: break
        }
        let sequence = UInt16(nextSequence)
        nextSequence += 1
        switch operation {
        case .arm: armSequence = sequence
        case .disarm: armSequence = nil
        default: break
        }
        return PhoneBridgeCommand(operation: operation, sequence: sequence, session: status.session)
    }
}
