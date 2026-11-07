import CryptoKit
import Foundation
import Testing
@testable import KinesisCore

private func modernScalar(_ value: UInt8) -> Data { Data(repeating: 0, count: 31) + Data([value]) }

private func modernRequest(point: Data, curve: UInt64 = 0, offer: UInt64 = 27) throws -> Data {
    try BandWire.frame(channel: 0x9c01, words: [0x81000005, 0x02000001], payload:
        BandWire.field(1, point) + BandWire.field(2, Data(0..<16))
        + BandWire.field(3, curve) + BandWire.field(4, offer) + BandWire.field(7, 17))
}

private func modernEnable(point: Data, scheme: UInt64 = 26) throws -> Data {
    try BandWire.frame(channel: 0x1801, words: [0x02000002], payload:
        BandWire.field(1, point) + BandWire.field(2, Data(0..<32)) + BandWire.field(3, Data(16..<32))
        + BandWire.field(4, 42) + BandWire.field(5, scheme))
}

/// A synthetic band covering the observed legacy and modern record profiles.
/// Test scalars are public constants; no identity is loaded from disk or Keychain.
/// Derive its keys independently of AirShieldKeys.
private struct ModernPeer {
    let profile: AirShieldScheme
    let session: BandSession
    let hostPoint: Data
    let hostChallenge: Data
    let bandPoint: Data
    let bandSigningKey: P256.Signing.PrivateKey
    var sender: AirShieldCipher
    var receiver: AirShieldReceiver
    var clientPending = Data()
    var startup: [DataXFrame] = []

    init(enrolled: Bool = false, peerParameters: UInt64 = 26) throws {
        let legacy = peerParameters == 3
        let scheme: AirShieldScheme = legacy ? .scheme3 : .scheme26
        profile = scheme
        bandSigningKey = try P256.Signing.PrivateKey(rawRepresentation: modernScalar(2))
        let identity = try enrolled ? BandEnrollmentIdentity(
            privateKey: P256.Signing.PrivateKey(rawRepresentation: modernScalar(3)),
            bandPublicKey: bandSigningKey.publicKey) : nil
        session = try BandSession(enrollment: identity)
        let host = try ProtoFields(Data(session.request().dropFirst(12)))
        hostPoint = try host.bytes(1)
        hostChallenge = try host.bytes(2)
        #expect(try host.integer(4) == 31)
        let transport = try P256.KeyAgreement.PrivateKey(rawRepresentation: modernScalar(1))
        bandPoint = Data(transport.publicKey.x963Representation.dropFirst())
        var reply = Data()
        for byte in try modernRequest(point: bandPoint, offer: legacy ? 3 : 27) {
            let result = try session.feed(Data([byte]), at: 100)
            reply += result.outgoing
            #expect(result.events.isEmpty)
        }
        let enable = try ProtoFields(Data(reply.dropFirst(8)))
        #expect(try enable.integer(5) == (legacy ? 3 : 26))
        #expect(try enable.bytes(1) == hostPoint)
        let peer = try P256.KeyAgreement.PublicKey(x963Representation: Data([4]) + hostPoint)
        let secret = try transport.sharedSecretFromKeyAgreement(with: peer).withUnsafeBytes { Data($0) }
        func keys(challenge: Data, seed: Data) -> AirShieldKeys {
            let material = legacy ? Data(SHA256.hash(data: secret)) : secret
            let salt = Data(SHA256.hash(data: (legacy ? material : Data()) + challenge + seed))
            let key = HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: material),
                salt: salt, info: Data("AirShield".utf8), outputByteCount: 32)
                .withUnsafeBytes { Data($0) }
            return AirShieldKeys(encryption: key, mac: key)
        }
        sender = AirShieldCipher(keys: keys(challenge: hostChallenge, seed: Data(0..<32)),
            iv: Data(16..<32), counter: 42, scheme: scheme)
        receiver = AirShieldReceiver(cipher: AirShieldCipher(
            keys: keys(challenge: Data(0..<16), seed: try enable.bytes(2)),
            iv: try enable.bytes(3), counter: UInt32(try enable.integer(4)), scheme: scheme))
        var output = Data()
        // Modern peer Enable values share a record profile while the host
        // announces 26; the legacy profile announces 3 in both directions.
        for byte in try modernEnable(point: bandPoint, scheme: peerParameters) {
            output += try session.feed(Data([byte]), at: 100).outgoing
        }
        startup = try requests(output)
    }

    /// Decode host requests independently of DataXReceiver, applying each
    /// profile's padding rule and retaining partial frames across records.
    mutating func requests(_ bytes: Data) throws -> [DataXFrame] {
        for var plain in try receiver.feed(bytes) {
            let count = Int(try #require(plain.last)) - 0xc0
            let maximum = profile == .scheme3 ? 15 : 16
            let padded = (1...maximum).contains(count) && plain.suffix(count).allSatisfy({ Int($0) == 0xc0 + count })
            guard profile == .scheme3 || padded else {
                throw BandProtocolError("Invalid modern test-peer padding")
            }
            if padded { plain.removeLast(count) }
            clientPending += plain
        }
        var frames: [DataXFrame] = []
        while clientPending.count >= 4 {
            let length = clientPending.be16(0)
            let size = Int(length & 0x7fff) + 4
            guard clientPending.count >= size else { break }
            var offset = 4
            var words: [UInt32] = []
            if length & 0x8000 != 0 {
                repeat {
                    guard offset + 4 <= size else { throw BandProtocolError("Truncated modern test frame") }
                    words.append(clientPending.be32(offset)); offset += 4
                } while words.last! & 0x80000000 != 0
            }
            frames.append(DataXFrame(channel: clientPending.be16(2), words: words,
                payload: Data(clientPending[offset..<size])))
            clientPending = Data(clientPending.dropFirst(size))
        }
        return frames
    }

    mutating func exchange(channel: UInt16, words: [UInt32], payload: Data = Data(), at time: Double = 101) throws
        -> (events: [BandEvent], requests: [DataXFrame]) {
        let wireChannel = profile == .scheme3 ? channel & 0x80ff : channel
        let wire = try sender.encrypt(BandWire.frame(channel: wireChannel, words: words, payload: payload))
        let result = try session.feed(wire, at: time)
        return (result.events, try requests(result.outgoing))
    }

    mutating func finishLinkAndSubscribe() throws {
        let link = try exchange(channel: 0x9c01, words: [0x02001000], payload:
            BandWire.field(1, 1) + BandWire.field(2, Data(repeating: 1, count: 16)))
        #expect(link.requests.map(\.channel) == [0x8003])
        // Responses retain the unflagged direction: 0x1503 canonicalizes to 3.
        let device = try exchange(channel: 0x1503, words: [0x02000315], payload:
            BandWire.field(1, 1) + BandWire.field(2, 1) + BandWire.field(4, Data()))
        #expect(device.requests.map(\.channel) == [0x8005, 0x8005, 0x8006])
        let flags = BandWire.field(3, 1) + BandWire.field(6, 1) + BandWire.field(8, 1)
        let enabled = try exchange(channel: 0x1c05, words: [0x02000315], payload:
            BandWire.field(1, 3) + BandWire.field(2, 1) + BandWire.field(5, flags))
        #expect(enabled.events.contains { if case .connected = $0.payload { true } else { false } })
        #expect(session.streamsEnabled)
    }
}

private struct SharedRPCSettings {
    var values: [UInt64: UInt64] = [27: 0, 28: 2]

    /// Parse RPC arms independently of BandModelCapture's operation bookkeeping.
    mutating func reply(to request: DataXFrame) throws -> Data {
        let rpc = try ProtoFields(request.payload)
        let body: Data
        if rpc.contains(4) {
            body = BandWire.field(5, try rpc.bytes(4))
        } else if rpc.contains(5) {
            #expect(try rpc.bytes(5).isEmpty)
            let emg = BandWire.field(1, 2048) + BandWire.field(2, 8)
                + BandWire.field(4, 16) + BandWire.field(5, 16) + BandWire.field(10, 0)
            body = BandWire.field(6, BandWire.field(42, emg) + BandWire.field(46, BandWire.field(3, 3)))
        } else {
            let control = try ProtoFields(rpc.bytes(14))
            if control.contains(1) {
                body = BandWire.field(14, BandWire.field(1, BandWire.field(1, 38)))
            } else if control.contains(2) {
                let id = try ProtoFields(control.bytes(2)).requiredInteger(2)
                #expect(id == 27 || id == 28)
                let name = id == 27 ? "data-collection" : "data-collection-model"
                body = BandWire.field(14, BandWire.field(2,
                    BandWire.field(3, Data(name.utf8)) + BandWire.field(4, id)))
            } else {
                let setting = try ProtoFields(control.bytes(3))
                let id = try setting.requiredInteger(1)
                #expect(id == 27 || id == 28)
                let writing = try setting.integer(2) == 1
                if writing {
                    values[id] = try ProtoFields(setting.bytes(id == 27 ? 7 : 10)).integer(1)
                    body = BandWire.field(14, BandWire.field(3, BandWire.field(1, id) + BandWire.field(2, 1)))
                } else {
                    let value = try #require(values[id])
                    body = BandWire.field(14, BandWire.field(3,
                        BandWire.field(1, id) + BandWire.field(id == 27 ? 8 : 11, BandWire.field(1, value))))
                }
            }
        }
        return BandWire.field(1, try rpc.requiredInteger(1)) + BandWire.field(2, 1) + body
    }
}

private func checkSharedRPC(_ request: DataXFrame, openings: inout Int) {
    #expect(request.channel == 0x8001)
    if openings == 0 { #expect(request.words == [0x8100ce56, 0x02000314]) }
    else { #expect(request.words.isEmpty) }
    if !request.words.isEmpty { openings += 1 }
    #expect(openings == 1)
}

private func enableSharedRaw(_ peer: inout ModernPeer, settings: inout SharedRPCSettings,
                             openings: inout Int, initialConfig: DataXFrame? = nil, at time: Double) throws {
    let config: DataXFrame
    if let initialConfig { config = initialConfig }
    else { config = try #require(peer.requests(peer.session.setRawEMGEnabled(true, at: time)).first) }
    checkSharedRPC(config, openings: &openings)
    let read = try ProtoFields(config.payload)
    #expect(read.contains(5) && !read.contains(14))
    let configured = try peer.exchange(channel: 0x1501, words: [0x02000315],
        payload: settings.reply(to: config), at: time + 0.01)
    #expect(configured.events.contains { if case .rawEMGConfiguration(let value) = $0.payload { value.isSupported } else { false } })
    let query = try #require(configured.requests.first)
    #expect(query.channel == 0x8005 && query.words.isEmpty)
    let queryID = try ProtoFields(query.payload).requiredInteger(1)
    let baseline = BandWire.field(3, 1) + BandWire.field(6, 1) + BandWire.field(8, 1)
    let queried = try peer.exchange(channel: 0x1805, words: [0x02000315], payload:
        BandWire.field(1, queryID) + BandWire.field(2, 1) + BandWire.field(5, baseline), at: time + 0.02)
    let update = try #require(queried.requests.first)
    let flags = try ProtoFields(ProtoFields(update.payload).bytes(4))
    #expect(update.channel == 0x8005 && update.words.isEmpty)
    for flag in [2, 3, 6, 8] { #expect(try flags.integer(flag) == 1) }
    let enabled = try peer.exchange(channel: 0x1c05, words: [0x02000315],
        payload: settings.reply(to: update), at: time + 0.03)
    #expect(enabled.events.contains { if case .rawEMGState(true) = $0.payload { true } else { false } })
}

private func runSharedModel(_ peer: inout ModernPeer, settings: inout SharedRPCSettings,
                            openings: inout Int, rawEnabled: Bool, at time: Double) throws {
    try peer.session.setModelCaptureEnabled(true, at: time)
    var configReads = 0
    for index in 0..<11 {
        let now = time + Double(index) * 0.05
        let request = try #require(peer.requests(peer.session.flushModelCapture(at: now).outgoing).first)
        let fields = try ProtoFields(request.payload)
        if fields.contains(4) {
            #expect(request.channel == 0x8005 && request.words.isEmpty)
            let flags = try ProtoFields(fields.bytes(4))
            for flag in [3, 4, 6, 8, 22, 23] { #expect(try flags.integer(flag) == 1) }
            #expect(try flags.integer(2) == (rawEnabled ? 1 : 0))
        } else {
            checkSharedRPC(request, openings: &openings)
            if fields.contains(5) { configReads += 1 }
        }
        if index < 2 {
            // Rejected changes must not alter the wanted raw state before throwing.
            #expect(throws: BandProtocolError.self) {
                try peer.session.setRawEMGEnabled(!rawEnabled, at: now + 0.001)
            }
        }
        if index == 1 {
            _ = try peer.exchange(channel: 0x1801, words: [0x02000315], payload:
                BandWire.field(1, 7) + BandWire.field(2, 1) + BandWire.field(6, Data()), at: now + 0.002)
            #expect(try peer.session.flushModelCapture(at: now + 0.003).outgoing.isEmpty)
        }
        _ = try peer.exchange(channel: 0x1500 | (request.channel & 0xff), words: [0x02000315],
            payload: settings.reply(to: request), at: now + 0.01)
    }
    #expect(configReads == 1 && settings.values[27] == 1 && settings.values[28] == 5)
    let scores = (0..<100).reduce(into: Data()) { bytes, _ in bytes += Float(-log(100.0)).bitPattern.littleEndianData }
    for sequence in 0..<5 {
        _ = try peer.exchange(channel: 0x9c11, words: [0x0200020c], payload:
            BandWire.field(1, UInt64(sequence)) + BandWire.field(2, 1_000_000 + UInt64(sequence) * 20_000)
            + BandWire.field(3, scores) + BandWire.field(10, 3), at: time + 0.6 + Double(sequence) * 0.01)
    }
    let ready = try peer.session.flushModelCapture(at: time + 0.7)
    #expect(ready.events.contains { if case .modelCaptureState(let state) = $0.payload { state.phase == .ready } else { false } })
    try peer.session.setModelCaptureEnabled(false, at: time + 0.8)
    for index in 0..<6 {
        let now = time + 0.8 + Double(index) * 0.05
        let request = try #require(peer.requests(peer.session.flushModelCapture(at: now).outgoing).first)
        let fields = try ProtoFields(request.payload)
        if fields.contains(4) {
            let flags = try ProtoFields(fields.bytes(4))
            for flag in [3, 6, 8] { #expect(try flags.integer(flag) == 1) }
            for flag in [4, 22, 23] { #expect(try flags.integer(flag) == 0) }
            #expect(try flags.integer(2) == (rawEnabled ? 1 : 0))
        } else { checkSharedRPC(request, openings: &openings) }
        _ = try peer.exchange(channel: 0x1800 | (request.channel & 0xff), words: [0x02000315],
            payload: settings.reply(to: request), at: now + 0.01)
    }
    let restored = try peer.session.flushModelCapture(at: time + 1.2)
    #expect(restored.events.contains { if case .modelCaptureState(let state) = $0.payload {
        state.phase == .finished && state.restorationVerified && state.problem == nil
    } else { false } })
    #expect(settings.values[27] == 0 && settings.values[28] == 2)
}

@Suite("Modern band transport compatibility")
struct BandModernFirmwareTests {
    @Test(arguments: [UInt64(3), 26, 27], [false, true])
    func modelAndRawConfigShareOneRPCServiceAfterBatterySetup(peerParameters: UInt64, rawFirst: Bool) throws {
        var peer = try ModernPeer(peerParameters: peerParameters)
        try peer.finishLinkAndSubscribe()
        let battery = try #require(peer.requests(peer.session.queryBatteryStatus(at: 102)).first)
        #expect(battery.channel == 0x8008 && battery.words == [0x8100ce56, 0x02000314])
        let batteryID = try ProtoFields(battery.payload).requiredInteger(1)
        _ = try peer.exchange(channel: 0x1508, words: [0x02000315], payload:
            BandWire.field(1, batteryID) + BandWire.field(2, 1)
            + BandWire.field(3, BandWire.field(1, BandWire.field(1, 72))), at: 102.01)
        var settings = SharedRPCSettings()
        var openings = 0
        if rawFirst { try enableSharedRaw(&peer, settings: &settings, openings: &openings, at: 103) }
        try runSharedModel(&peer, settings: &settings, openings: &openings, rawEnabled: rawFirst, at: 104)
        if !rawFirst { try enableSharedRaw(&peer, settings: &settings, openings: &openings, at: 106) }
        #expect(openings == 1 && peer.session.streamsEnabled && !peer.session.modelCaptureActive)
    }

    @Test(arguments: [UInt64(3), 26, 27])
    func modelPreparationWaitsForAnOutstandingRawConfigTransaction(peerParameters: UInt64) throws {
        var peer = try ModernPeer(peerParameters: peerParameters)
        try peer.finishLinkAndSubscribe()
        let config = try #require(peer.requests(peer.session.setRawEMGEnabled(true, at: 102)).first)
        try peer.session.setModelCaptureEnabled(true, at: 102.01)
        #expect(try peer.session.flushModelCapture(at: 102.02).outgoing.isEmpty)
        var settings = SharedRPCSettings()
        var openings = 0
        try enableSharedRaw(&peer, settings: &settings, openings: &openings, initialConfig: config, at: 102.03)
        let model = try #require(peer.requests(peer.session.flushModelCapture(at: 102.1).outgoing).first)
        #expect(model.channel == 0x8005 && model.words.isEmpty)
        let flags = try ProtoFields(ProtoFields(model.payload).bytes(4))
        for flag in [2, 3, 4, 6, 8, 22, 23] { #expect(try flags.integer(flag) == 1) }
        #expect(openings == 1)
    }

    @Test(arguments: [UInt64(3), 26, 27])
    func aSharedRawConfigRejectionKeepsGesturesAndIgnoresTheOldConfigChannel(peerParameters: UInt64) throws {
        var peer = try ModernPeer(peerParameters: peerParameters)
        try peer.finishLinkAndSubscribe()
        let request = try #require(peer.requests(peer.session.setRawEMGEnabled(true, at: 102)).first)
        #expect(request.channel == 0x8001)
        let unrelated = try peer.exchange(channel: 0x1507, words: [0x0300c001], at: 102.01)
        #expect(!unrelated.events.contains { if case .rawEMGFailure = $0.payload { true } else { false } })
        #expect(try peer.session.queryStreamState().isEmpty)
        let rejected = try peer.exchange(channel: 0x1801, words: [0x0300c001], at: 102.02)
        #expect(rejected.events.contains { if case .rawEMGFailure = $0.payload { true } else { false } })
        #expect(peer.session.streamsEnabled && !peer.session.modelCaptureActive)
        #expect(try !peer.session.queryStreamState().isEmpty)
    }

    @Test func modernRoutingPreservesTheWireTagForRepliesAndLeavesLegacyChannelsUnchanged() throws {
        let frame = try BandWire.frame(channel: 0x9503, words: [0x02001001])
        let plaintext = frame + Data(repeating: 0xc8, count: 8)
        var modern = DataXReceiver()
        let routed = try #require(modern.feed(plaintext, scheme: .scheme26).first)
        #expect(routed.channel == 0x8003 && routed.wireChannel == 0x9503)
        var legacy = DataXReceiver()
        let original = try #require(legacy.feed(plaintext).first)
        #expect(original.channel == 0x9503 && original.wireChannel == 0x9503)
    }

    @Test(arguments: [UInt64(26), 27])
    func modernHandshakeSelects26AndProcessesTaggedStartupAndSensorFrames(peerParameters: UInt64) throws {
        var peer = try ModernPeer(peerParameters: peerParameters)
        #expect(peer.startup.map(\.channel) == [0x8002, 0x8001])
        try peer.finishLinkAndSubscribe()
        let gesture = BandWire.field(1, 1) + BandWire.field(2, 2)
            + BandWire.field(3, 2) + BandWire.field(4, 3)
        // Header + kind + these fields is exactly16 bytes, requiring a full 0xd0 block.
        #expect(try BandWire.frame(channel: 0x9c10, words: [0x0200020d], payload: gesture).count == 16)
        let first = try peer.exchange(channel: 0x9c10, words: [0x0200020d], payload: gesture)
        #expect(first.events.contains { if case .gesture(let value) = $0.payload {
            value.sequence == 1 && value.finger == "index" && value.action == "tap"
        } else { false } })
        let second = try peer.exchange(channel: 0x9810, words: [], payload:
            BandWire.field(1, 2) + BandWire.field(2, 3) + BandWire.field(3, 2) + BandWire.field(4, 3), at: 102)
        #expect(second.events.contains { if case .gesture(let value) = $0.payload { value.sequence == 2 } else { false } })
        let gyro = try peer.exchange(channel: 0x9510, words: [0x0200020f], payload:
            BandWire.field(1, 4) + BandWire.field(2, 1_000_000)
            + BandWire.field(3, Int16(12).littleEndianData + Int16(-5).littleEndianData + Int16(8).littleEndianData), at: 103)
        #expect(gyro.events.contains { if case .gyro(let stamp, let values) = $0.payload {
            stamp == 1_000_000 && values == SIMD3(12, -5, 8)
        } else { false } })
        let hand = try peer.exchange(channel: 0x1806, words: [0x02000315], payload:
            BandWire.field(1, 1) + BandWire.field(2, 1) + BandWire.field(6, BandWire.field(10, 0)), at: 104)
        #expect(hand.events.contains { if case .handedness(.right) = $0.payload { true } else { false } })
    }

    @Test(arguments: [UInt64(26), 27])
    func modernEnrolledStartupVerifiesTaggedIdentityBeforeLinkAndInput(peerParameters: UInt64) throws {
        var peer = try ModernPeer(enrolled: true, peerParameters: peerParameters)
        #expect(peer.startup.count == 1 && peer.startup.first?.channel == 0x8002)
        let accepted = try peer.exchange(channel: 0x1c02, words: [0x03001000])
        #expect(accepted.requests.isEmpty)
        let digest = SHA256.hash(data: Data(SHA256.hash(data: peer.hostChallenge + peer.hostPoint))
            + Data(SHA256.hash(data: Data(0..<32) + peer.bandPoint)))
        let signature = try peer.bandSigningKey.signature(for: digest).rawRepresentation
        let proof = try peer.exchange(channel: 0x9503, words: [0x81000024, 0x02001001], payload:
            BandWire.field(2, signature))
        // Routing ignores the tag, but the peer-open identity ACK must echo it.
        #expect(proof.requests.map(\.channel) == [0x1503, 0x8001])
        #expect(proof.requests.first?.words == [0x03001000])
        try peer.finishLinkAndSubscribe()
    }

    @Test(arguments: [UInt64(0), 1, 2, 4, 26, 31, UInt64.max])
    func unsupportedOffersAreRejectedWithoutNegotiating(offer: UInt64) throws {
        let session = try BandSession()
        let key = try P256.KeyAgreement.PrivateKey(rawRepresentation: modernScalar(1))
        let point = Data(key.publicKey.x963Representation.dropFirst())
        #expect(throws: BandProtocolError.self) { try session.feed(modernRequest(point: point, offer: offer), at: 100) }
        #expect(session.authenticatedPackets == 0 && !session.streamsEnabled)
    }

    @Test func unsupportedCurveAndDuplicateRequestAreRejected() throws {
        let key = try P256.KeyAgreement.PrivateKey(rawRepresentation: modernScalar(1))
        let point = Data(key.publicKey.x963Representation.dropFirst())
        let curve = try BandSession()
        #expect(throws: BandProtocolError.self) { try curve.feed(modernRequest(point: point, curve: 1), at: 100) }
        let repeated = try BandSession()
        _ = try repeated.feed(modernRequest(point: point), at: 100)
        #expect(throws: BandProtocolError.self) { try repeated.feed(modernRequest(point: point), at: 100) }
    }

    @Test(arguments: [(UInt64(27), UInt64(3)), (27, 31), (27, 28), (3, 26), (3, 27)])
    func peerEnableMustMatchTheVerifiedProfile(offer: UInt64, response: UInt64) throws {
        let session = try BandSession()
        let key = try P256.KeyAgreement.PrivateKey(rawRepresentation: modernScalar(1))
        let point = Data(key.publicKey.x963Representation.dropFirst())
        let result = try session.feed(modernRequest(point: point, offer: offer), at: 100)
        let selected = try ProtoFields(Data(result.outgoing.dropFirst(8)))
        #expect(try selected.integer(5) == (offer == 27 ? 26 : 3))
        #expect(throws: BandProtocolError.self) { try session.feed(modernEnable(point: point, scheme: response), at: 100) }
    }

    @Test(arguments: [UInt64(26), 27])
    func peerEnableCannotChangeTheKeyOrArriveBeforeItsRequest(peerParameters: UInt64) throws {
        let first = try P256.KeyAgreement.PrivateKey(rawRepresentation: modernScalar(1))
        let second = try P256.KeyAgreement.PrivateKey(rawRepresentation: modernScalar(2))
        let firstPoint = Data(first.publicKey.x963Representation.dropFirst())
        let secondPoint = Data(second.publicKey.x963Representation.dropFirst())
        let changed = try BandSession()
        _ = try changed.feed(modernRequest(point: firstPoint), at: 100)
        #expect(throws: BandProtocolError.self) {
            try changed.feed(modernEnable(point: secondPoint, scheme: peerParameters), at: 100)
        }
        let early = try BandSession()
        #expect(throws: BandProtocolError.self) {
            try early.feed(modernEnable(point: firstPoint, scheme: peerParameters), at: 100)
        }
    }

    @Test(arguments: [UInt64(26), 27])
    func failedModernPacketAuthenticationCannotReleaseStartupEvents(peerParameters: UInt64) throws {
        var peer = try ModernPeer(peerParameters: peerParameters)
        let frame = try BandWire.frame(channel: 0x9c01, words: [0x02001000], payload: BandWire.field(1, 1))
        var packet = try peer.sender.encrypt(frame)
        packet[1] ^= 1
        #expect(throws: BandProtocolError.self) { try peer.session.feed(packet, at: 101) }
        #expect(peer.session.authenticatedPackets == 0 && !peer.session.streamsEnabled)
    }

    @Test(arguments: [UInt64(26), 27], [false, true])
    func aTaggedModelRejectionRestoresOnlyItsRequestAndKeepsGestureStreams(peerParameters: UInt64, claim: Bool) throws {
        var peer = try ModernPeer(peerParameters: peerParameters)
        try peer.finishLinkAndSubscribe()
        try peer.session.setModelCaptureEnabled(true, at: 102)
        let stream = try #require(peer.requests(peer.session.flushModelCapture(at: 102).outgoing).first)
        let streamID = try ProtoFields(stream.payload).requiredInteger(1)
        if claim {
            let enabled = [3, 4, 6, 8, 22, 23].reduce(into: Data()) { $0 += BandWire.field($1, 1) }
            _ = try peer.exchange(channel: 0x1505, words: [0x02000315], payload:
                BandWire.field(1, streamID) + BandWire.field(2, 1) + BandWire.field(5, enabled), at: 102.01)
            let request = try #require(peer.requests(peer.session.flushModelCapture(at: 102.02).outgoing).first)
            #expect(request.channel == 0x8001)
        }
        let unrelated = try peer.exchange(channel: 0x1c09, words: [0x0300c001], at: 102.03)
        #expect(!unrelated.events.contains { if case .modelCaptureState = $0.payload { true } else { false } })
        #expect(unrelated.requests.isEmpty)
        #expect(try peer.session.flushModelCapture(at: 102.04).outgoing.isEmpty)
        let rejected = try peer.exchange(channel: claim ? 0x1801 : 0x1805,
            words: [0x0300c001], at: 102.05)
        let expected = claim ? "claiming model controls" : "starting model streams"
        #expect(rejected.events.contains { if case .modelCaptureState(let state) = $0.payload {
            state.phase == .restoring && state.problem == expected + ": the band rejected a model request"
        } else { false } })
        #expect(peer.session.streamsEnabled)
        let cleanup = try #require(peer.requests(peer.session.flushModelCapture(at: 102.06).outgoing).first)
        #expect(cleanup.channel == 0x8005 && cleanup.words.isEmpty)
        let fields = try ProtoFields(cleanup.payload)
        let flags = try ProtoFields(fields.bytes(4))
        for flag in [3, 6, 8] { #expect(try flags.integer(flag) == 1) }
        for flag in [4, 22, 23] { #expect(try flags.integer(flag) == 0) }
        _ = try peer.exchange(channel: 0x1c05, words: [0x02000315], payload:
            BandWire.field(1, fields.requiredInteger(1)) + BandWire.field(2, 1)
            + BandWire.field(5, fields.bytes(4)), at: 102.07)
        let finished = try peer.session.flushModelCapture(at: 102.08)
        #expect(finished.events.contains { if case .modelCaptureState(let state) = $0.payload {
            state.phase == .finished && state.restorationVerified
        } else { false } })
    }
}
