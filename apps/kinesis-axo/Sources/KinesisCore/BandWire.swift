import Foundation

struct ProtoFields {
    enum Value { case integer(UInt64), bytes(Data), fixed }
    private var values: [Int: [Value]] = [:]

    init(_ data: Data) throws {
        let bytes = [UInt8](data)
        var offset = 0
        func varint() throws -> UInt64 {
            var value: UInt64 = 0
            for shift in stride(from: 0, through: 63, by: 7) {
                guard offset < bytes.count else { throw BandProtocolError("Truncated protobuf varint") }
                let byte = bytes[offset]
                offset += 1
                guard shift < 63 || byte <= 1 else { throw BandProtocolError("Protobuf varint overflow") }
                value |= UInt64(byte & 127) << shift
                if byte < 128 { return value }
            }
            throw BandProtocolError("Unterminated protobuf varint")
        }
        while offset < bytes.count {
            let tag = try varint()
            let number = Int(tag >> 3)
            guard number > 0, number < 1 << 29 else {
                throw BandProtocolError("Invalid protobuf field number")
            }
            let wire = tag & 7
            if wire == 0 { values[number, default: []].append(.integer(try varint())); continue }
            let size: UInt64
            switch wire {
            case 1: size = 8
            case 2: size = try varint()
            case 5: size = 4
            default: throw BandProtocolError("Unsupported protobuf wire type")
            }
            guard size <= bytes.count - offset else { throw BandProtocolError("Truncated protobuf field") }
            if wire == 2 {
                values[number, default: []].append(.bytes(Data(bytes[offset..<offset + Int(size)])))
            } else {
                values[number, default: []].append(.fixed)
            }
            offset += Int(size)
        }
    }

    func integer(_ field: Int, default fallback: UInt64 = 0) throws -> UInt64 {
        guard let fieldValues = values[field] else { return fallback }
        guard fieldValues.count == 1, case .integer(let integer) = fieldValues[0] else { throw BandProtocolError("Expected protobuf integer") }
        return integer
    }
    func requiredInteger(_ field: Int) throws -> UInt64 {
        guard values[field] != nil else { throw BandProtocolError("Missing protobuf integer") }
        return try integer(field)
    }
    func bytes(_ field: Int, count: Int? = nil) throws -> Data {
        guard let fieldValues = values[field], fieldValues.count == 1,
              case .bytes(let bytes) = fieldValues[0], count == nil || bytes.count == count else {
            throw BandProtocolError("Invalid protobuf byte field")
        }
        return bytes
    }
    func contains(_ field: Int) -> Bool { values[field] != nil }

    func repeatedBytes(_ field: Int, maximumCount: Int, maximumBytes: Int) throws -> [Data] {
        let entries = values[field] ?? []
        guard maximumCount >= 0, maximumBytes >= 0, entries.count <= maximumCount else {
            throw BandProtocolError("Invalid repeated protobuf byte field")
        }
        return try entries.map { entry in
            guard case .bytes(let data) = entry, data.count <= maximumBytes else {
                throw BandProtocolError("Invalid repeated protobuf byte field")
            }
            return data
        }
    }

    /// Structural diagnostics only: field numbers, wire categories and multiplicities.
    /// Never includes scalar values, byte lengths, strings or byte contents.
    var wireShape: String {
        let fields = values.keys.sorted().prefix(12).map { field in
            var integers = 0, bytes = 0, fixed = 0
            for value in values[field] ?? [] {
                switch value {
                case .integer: integers += 1
                case .bytes: bytes += 1
                case .fixed: fixed += 1
                }
            }
            let kinds = [("int", integers), ("bytes", bytes), ("fixed", fixed)]
                .filter { $0.1 > 0 }.map { "\($0.0)(\($0.1))" }.joined(separator: "+")
            return "\(field):\(kinds)"
        }
        let text = fields.joined(separator: ";") + (values.count > 12 ? ";..." : "")
        return String((text.isEmpty ? "empty" : text).prefix(96))
    }
}

public enum BandWire {
    public static func varint(_ value: UInt64) -> Data {
        var value = value
        var bytes: [UInt8] = []
        while value >= 128 { bytes.append(UInt8(value & 127) | 128); value >>= 7 }
        bytes.append(UInt8(value))
        return Data(bytes)
    }
    public static func field(_ number: Int, _ value: UInt64) -> Data {
        varint(UInt64(number << 3)) + varint(value)
    }
    public static func field(_ number: Int, _ bytes: Data) -> Data {
        varint(UInt64(number << 3 | 2)) + varint(UInt64(bytes.count)) + bytes
    }
    static func frame(channel: UInt16, words: [UInt32] = [], payload: Data = Data()) throws -> Data {
        let body = words.reduce(into: Data()) { $0.append($1.bigEndianData) } + payload
        guard body.count <= 0x7fff else { throw BandProtocolError("DataX frame too large") }
        let size = UInt16(body.count) | (words.isEmpty ? 0 : 0x8000)
        return size.bigEndianData + channel.bigEndianData + body
    }
}

public struct DataXFrame {
    public let channel: UInt16
    /// Original channel tags are retained for acknowledgements to peer-opened services.
    public let wireChannel: UInt16
    public let words: [UInt32]
    public let payload: Data

    public init(channel: UInt16, words: [UInt32], payload: Data, wireChannel: UInt16? = nil) {
        self.channel = channel
        self.wireChannel = wireChannel ?? channel
        self.words = words
        self.payload = payload
    }
}

struct DataXReceiver {
    private var pending = Data()

    mutating func feed(_ plaintext: Data, scheme: AirShieldScheme = .scheme3) throws -> [DataXFrame] {
        guard !plaintext.isEmpty, plaintext.count % 16 == 0 else {
            throw BandProtocolError("Unaligned DataX plaintext")
        }
        var bytes = plaintext
        let padding = Int(bytes.last!) - 0xc0
        let maximumPadding = scheme == .scheme26 ? 16 : 15
        let padded = (1...maximumPadding).contains(padding)
            && bytes.suffix(padding).allSatisfy({ Int($0) == 0xc0 + padding })
        guard scheme != .scheme26 || padded else { throw BandProtocolError("Invalid DataX padding") }
        if padded {
            bytes.removeLast(padding)
        }
        pending.append(bytes)
        var frames: [DataXFrame] = []
        while pending.count >= 4 {
            let length = pending.be16(0)
            let size = Int(length & 0x7fff) + 4
            guard pending.count >= size else { break }
            let wireChannel = pending.be16(2)
            // New firmware adds connection-specific tags above the channel ID.
            // Preserve the peer-open bit while routing to the original service.
            let channel = scheme == .scheme26 ? wireChannel & 0x80ff : wireChannel
            var offset = 4
            var words: [UInt32] = []
            if length & 0x8000 != 0 {
                repeat {
                    guard offset + 4 <= size else { throw BandProtocolError("Truncated DataX typed header") }
                    words.append(pending.be32(offset))
                    offset += 4
                } while words.last! & 0x80000000 != 0
            }
            frames.append(DataXFrame(channel: channel, words: words, payload: Data(pending[offset..<size]),
                                     wireChannel: wireChannel))
            pending = Data(pending.dropFirst(size))
        }
        return frames
    }
}

extension Data {
    func be16(_ offset: Int) -> UInt16 { UInt16(self[offset]) << 8 | UInt16(self[offset + 1]) }
    func be32(_ offset: Int) -> UInt32 { UInt32(be16(offset)) << 16 | UInt32(be16(offset + 2)) }
}
