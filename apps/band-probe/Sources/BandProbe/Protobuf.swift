import Foundation
import KinesisCore

/// Schema-less protobuf: enough to build probe payloads and read whatever comes back.
enum Protobuf {
    enum Value {
        case varint(UInt64)
        case fixed64(UInt64)
        case fixed32(UInt32)
        case bytes(Data)
    }

    /// Parses every field, or returns nil if the bytes aren't a well-formed message.
    static func parse(_ data: Data) -> [(field: Int, value: Value)]? {
        let bytes = [UInt8](data)
        var offset = 0
        var fields: [(Int, Value)] = []
        func varint() -> UInt64? {
            var value: UInt64 = 0
            for shift in stride(from: 0, to: 64, by: 7) {
                guard offset < bytes.count else { return nil }
                let byte = bytes[offset]
                offset += 1
                value |= UInt64(byte & 0x7f) << UInt64(shift)
                if byte & 0x80 == 0 { return value }
            }
            return nil
        }
        func take(_ count: Int) -> [UInt8]? {
            guard count >= 0, offset + count <= bytes.count else { return nil }
            defer { offset += count }
            return Array(bytes[offset..<offset + count])
        }
        while offset < bytes.count {
            guard let tag = varint(), tag >> 3 > 0 else { return nil }
            let field = Int(tag >> 3)
            switch tag & 7 {
            case 0:
                guard let value = varint() else { return nil }
                fields.append((field, .varint(value)))
            case 1:
                guard let raw = take(8) else { return nil }
                fields.append((field, .fixed64(raw.reversed().reduce(0) { $0 << 8 | UInt64($1) })))
            case 2:
                guard let size = varint(), let raw = take(Int(size)) else { return nil }
                fields.append((field, .bytes(Data(raw))))
            case 5:
                guard let raw = take(4) else { return nil }
                fields.append((field, .fixed32(raw.reversed().reduce(0) { $0 << 8 | UInt32($1) })))
            default: return nil
            }
        }
        return fields
    }

    /// Indented tree; length-delimited fields are shown as nested messages when they parse as one.
    static func dump(_ data: Data, indent: String = "  ") -> String {
        guard let fields = parse(data), !fields.isEmpty else { return "\(indent)\(hex(data))" }
        return fields.map { field, value in
            switch value {
            case .varint(let v): "\(indent)\(field): \(v)"
            case .fixed64(let v): "\(indent)\(field): fixed64 \(v) (\(Double(bitPattern: v)))"
            case .fixed32(let v): "\(indent)\(field): fixed32 \(v) (\(Float(bitPattern: v)))"
            case .bytes(let bytes):
                if let nested = parse(bytes), !nested.isEmpty {
                    "\(indent)\(field) {\n\(dump(bytes, indent: indent + "  "))\n\(indent)}"
                } else if let text = String(data: bytes, encoding: .utf8), !text.isEmpty,
                          text.unicodeScalars.allSatisfy({ $0.properties.isAlphabetic || (0x20..<0x7f).contains($0.value) }) {
                    "\(indent)\(field): \"\(text)\""
                } else {
                    "\(indent)\(field): bytes[\(bytes.count)] \(hex(bytes))"
                }
            }
        }.joined(separator: "\n")
    }

    /// `1=5 2=x:0a01` → field 1 varint 5, field 2 bytes 0a01.
    static func encode(_ assignments: [String]) throws -> Data {
        try assignments.reduce(into: Data()) { message, assignment in
            let parts = assignment.split(separator: "=", maxSplits: 1).map(String.init)
            guard parts.count == 2, let field = Int(parts[0]), field > 0 else {
                throw ProbeError(message: "Expected field=value, got \(assignment)")
            }
            if parts[1].hasPrefix("x:") {
                message += BandWire.field(field, try data(hex: String(parts[1].dropFirst(2))))
                return
            }
            guard let value = UInt64(parts[1]) else { throw ProbeError(message: "\(parts[1]) is not an unsigned integer") }
            message += BandWire.field(field, value)
        }
    }

    static func data(hex: String) throws -> Data {
        let digits = Array(hex.filter { !$0.isWhitespace })
        guard digits.count.isMultiple(of: 2) else { throw ProbeError(message: "Odd number of hex digits") }
        return try Data(stride(from: 0, to: digits.count, by: 2).map {
            guard let byte = UInt8(String(digits[$0...$0 + 1]), radix: 16) else { throw ProbeError(message: "Invalid hex: \(hex)") }
            return byte
        })
    }

    static func hex(_ data: Data) -> String {
        data.isEmpty ? "(empty)" : data.map { String(format: "%02x", $0) }.joined()
    }
}
