import Foundation
import KinesisCore

/// HapticsReq (RpcRequest field 17) as found so far: field 1 holds a message that starts
/// a buzz (an empty one buzzes until stopped), and an empty message in field 2 stops it.
/// Every buzz here is followed by a stop, so unknown parameters can't leave the band buzzing.
@MainActor
final class HapticsProbe {
    private static let rpcField = 17
    private static let stopMessage = BandWire.field(2, Data())
    private let link: BandLink
    private var awaitingReplies: Set<UInt64> = []
    private var running: Task<Void, Never>?

    init(link: BandLink) {
        self.link = link
    }

    func replied(to id: UInt64) {
        awaitingReplies.remove(id)
    }

    func play(_ start: Data, seconds: Double) {
        run { try await self.buzz(start, seconds: seconds) }
    }

    /// Every field × value combination, one at a time, each inside field 1.
    func sweep(fields: [Int], values: [String], seconds: Double) {
        run {
            for field in fields {
                for value in values {
                    print("▶ 1 { \(field)=\(value) }")
                    try await self.buzz(Protobuf.encode(["\(field)=\(value)"]), seconds: seconds)
                    try await Task.sleep(for: .seconds(1))
                }
            }
            print("sweep done")
        }
    }

    func stop() throws {
        running?.cancel()
        running = nil
        _ = try send(Self.stopMessage)
    }

    private func run(_ steps: @escaping @MainActor () async throws -> Void) {
        running?.cancel()
        running = Task {
            do { try await steps() } catch is CancellationError {
                print("stopped")
            } catch {
                print("error: \(error.localizedDescription)")
            }
        }
    }

    private func buzz(_ start: Data, seconds: Double) async throws {
        let id = try send(BandWire.field(1, start))
        try await Task.sleep(for: .seconds(seconds))
        _ = try send(Self.stopMessage)
        if awaitingReplies.remove(id) != nil {
            print("  no reply to request \(id): the band likely couldn't decode it (wrong wire type?)")
        }
    }

    private func send(_ payload: Data) throws -> UInt64 {
        let id = try link.sendRPC(field: Self.rpcField, payload: payload)
        awaitingReplies.insert(id)
        print("→ request \(id): hapticsReq \(Protobuf.hex(payload))")
        return id
    }
}
