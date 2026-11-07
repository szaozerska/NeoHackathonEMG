import Foundation

/// The USB console deliberately carries only the existing bounded adapter protocol.
/// Other console output, including local enrollment messages, is never surfaced.
public enum PhoneUSBWire {
    /// Envelope 3 advertises momentary left clicks. The enclosed BLE packet
    /// remains version 1, preserving the bytes of all existing actions.
    public static let envelopeVersion = 3
    public static let hello = Data("HELLO\n".utf8)

    public static func command(_ command: PhoneBridgeCommand) -> Data {
        Data(("USB " + command.data.map { String(format: "%02x", $0) }.joined() + "\n").utf8)
    }

    public static func status(from line: Data) -> PhoneBridgeStatus? {
        let prefix = Array("AXOUSB \(envelopeVersion) ".utf8)
        let bytes = Array(line)
        guard bytes.count == prefix.count + PhoneBridgeWire.messageLength * 2,
              bytes.starts(with: prefix) else { return nil }
        var payload = Data()
        for offset in stride(from: prefix.count, to: bytes.count, by: 2) {
            guard let high = nibble(bytes[offset]), let low = nibble(bytes[offset + 1]) else { return nil }
            payload.append(high << 4 | low)
        }
        return PhoneBridgeStatus(data: payload)
    }

    private static func nibble(_ byte: UInt8) -> UInt8? {
        switch byte {
        case 48...57: byte - 48
        case 97...102: byte - 87
        case 65...70: byte - 55
        default: nil
        }
    }
}

/// A bounded line decoder that resynchronizes after boot noise or overlong lines.
public struct PhoneUSBStatusParser: Sendable {
    private var line = Data()
    private var discarding = false

    public init() {}

    public mutating func reset() {
        line.removeAll(keepingCapacity: true)
        discarding = false
    }

    public mutating func append(_ data: Data) -> [PhoneBridgeStatus] {
        var statuses: [PhoneBridgeStatus] = []
        for byte in data {
            if byte == 10 {
                if !discarding, let status = PhoneUSBWire.status(from: line) { statuses.append(status) }
                line.removeAll(keepingCapacity: true)
                discarding = false
            } else if byte == 13 {
                // Serial Monitor and the firmware may use either LF or CRLF.
                continue
            } else if !discarding {
                if line.count < 64 { line.append(byte) }
                else { line.removeAll(keepingCapacity: true); discarding = true }
            }
        }
        return statuses
    }
}
