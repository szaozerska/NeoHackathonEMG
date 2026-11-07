import Foundation

/// The model identifiers advertised by DeviceInfoResp. Other device metadata is ignored.
struct BandDeviceModelInfo: Equatable, Sendable {
    static let maximumIdentifierBytes = 96
    static let maximumModels = 32

    let currentID: String?
    let availableIDs: [String]
    /// An omitted inventory is not evidence that a model is absent.
    let inventoryReported: Bool

    init(response: Data) throws {
        let rpc = try ProtoFields(response)
        guard try rpc.requiredInteger(1) == 1, try rpc.requiredInteger(2) == 1 else {
            throw BandProtocolError("Unconfirmed device model metadata")
        }
        // The startup request is RPC arm 3; its DeviceInfoResp is arm 4.
        let info = try ProtoFields(rpc.bytes(4))
        let models = try info.repeatedBytes(10, maximumCount: Self.maximumModels,
                                           maximumBytes: Self.maximumIdentifierBytes)
        var unique: [String] = []
        for bytes in models {
            let model = try Self.identifier(bytes)
            if !unique.contains(model) { unique.append(model) }
        }
        availableIDs = unique
        inventoryReported = info.contains(10)
        // Field 9 is a legacy current-ID field. Accept it only when the advertised
        // inventory independently confirms it; a changed schema must not leak another field.
        let legacy = try? info.repeatedBytes(9, maximumCount: 1,
                                           maximumBytes: Self.maximumIdentifierBytes)
        if let bytes = legacy?.first, let candidate = try? Self.identifier(bytes),
           unique.contains(candidate) { currentID = candidate }
        else { currentID = nil }
    }

    /// Bounded, model-specific metadata only. No serials, account fields, or raw payloads.
    var diagnostic: String {
        let inventory = inventoryReported ? availableIDs.joined(separator: ",") : "not reported"
        return "Band model inventory: current=\(currentID ?? "not reported") available=[\(inventory)]"
    }

    private static func identifier(_ bytes: Data) throws -> String {
        guard !bytes.isEmpty, bytes.count <= maximumIdentifierBytes,
              bytes.allSatisfy({ byte in
                  (0x30...0x39).contains(byte) || (0x41...0x5a).contains(byte)
                      || (0x61...0x7a).contains(byte) || [0x5f, 0x2d, 0x2e, 0x2b].contains(byte)
              }), let text = String(data: bytes, encoding: .utf8) else {
            throw BandProtocolError("Invalid device model identifier")
        }
        return text
    }
}
