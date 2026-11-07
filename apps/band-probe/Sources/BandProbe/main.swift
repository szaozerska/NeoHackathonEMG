import Foundation
import KinesisCore

let help = """
commands:
  rpc <field> [hex]           send RpcRequest { 1: id, <field>: <hex bytes> }  (hex omitted = empty message)
  pb <field> [n=v n=x:hex …]  same, building the inner message from fields: varints, or x: for bytes
  enc [n=v n=x:hex …]         print the hex of a message, for nesting into x:
  help                        this list
  quit                        unsubscribe and disconnect
known RpcRequest fields: 2 BatteryInfoReq, 4 StreamControlReq, 5 ConfigReq, 14 model settings, 17 hapticsReq (unverified)
"""

func savedKinesisBand() throws -> UUID {
    guard let data = UserDefaults(suiteName: "local.callbacked.kinesis")?.data(forKey: "band") else {
        throw ProbeError(message: "No band saved in Kinesis. Pass the band UUID as the first argument.")
    }
    let band = try JSONDecoder().decode(BandDevice.self, from: data)
    guard let address = UUID(uuidString: band.address) else { throw ProbeError(message: "Kinesis saved an invalid band address") }
    print("using Kinesis's band \(band.name) (\(band.address))")
    return address
}

func printEvent(_ event: BandEvent) {
    switch event.payload {
    case .connected: print("connected. type `help` for commands.")
    case .handedness(let hand): print("band hand: \(hand.rawValue)")
    case .gesture(let gesture): print("gesture: \(gesture.finger) \(gesture.action) / \(gesture.derivedAction)")
    case .rpcReply(let kind, let payload):
        print("← reply type 0x\(String(kind, radix: 16)), \(payload.count) bytes: \(Protobuf.hex(payload))")
        print(Protobuf.dump(payload))
    default: break
    }
}

@MainActor
func run(_ line: String, on link: BandLink) throws {
    let words = line.split(separator: " ").map(String.init)
    guard let command = words.first else { return }
    let arguments = Array(words.dropFirst())
    switch command {
    case "help": print(help)
    case "quit": try link.stop()
    case "enc": print(Protobuf.hex(try Protobuf.encode(arguments)))
    case "rpc", "pb":
        guard let fieldText = arguments.first, let field = Int(fieldText), field > 1 else {
            throw ProbeError(message: "Give an RpcRequest field number above 1")
        }
        let rest = Array(arguments.dropFirst())
        let payload = command == "rpc" ? try Protobuf.data(hex: rest.joined()) : try Protobuf.encode(rest)
        let id = try link.sendRPC(field: field, payload: payload)
        print("→ request \(id): field \(field), payload \(Protobuf.hex(payload))")
    default: throw ProbeError(message: "Unknown command \(command). Type `help`.")
    }
}

let address = try CommandLine.arguments.dropFirst().first.map {
    guard let uuid = UUID(uuidString: $0) else { throw ProbeError(message: "\($0) is not a band UUID") }
    return uuid
} ?? savedKinesisBand()

let link = BandLink(address: address, onEvent: printEvent) { error in
    if let error { print("ended: \(error.localizedDescription)") }
    exit(error == nil ? 0 : 1)
}
try link.start()

let keepAlive = Timer(timeInterval: 2, repeats: true) { _ in
    MainActor.assumeIsolated {
        do { try link.keepAlive() } catch { print("keep-alive failed: \(error.localizedDescription)") }
    }
}
RunLoop.main.add(keepAlive, forMode: .common)

FileHandle.standardInput.readabilityHandler = { handle in
    let text = String(decoding: handle.availableData, as: UTF8.self)
    Task { @MainActor in
        if text.isEmpty { try? link.stop(); return }
        for line in text.split(separator: "\n") {
            do { try run(line.trimmingCharacters(in: .whitespaces), on: link) }
            catch { print("error: \(error.localizedDescription)") }
        }
    }
}

RunLoop.main.run()
