// Standalone checks compiled alongside the real KinesisCore sources; no hardware/credentials.
import Foundation
import CryptoKit

extension Data {
    init(testHex: String) {
        self.init(stride(from: 0, to: testHex.count, by: 2).map {
            UInt8(testHex[testHex.index(testHex.startIndex, offsetBy: $0)..<testHex.index(testHex.startIndex, offsetBy: $0 + 2)], radix: 16)!
        })
    }
}

@main struct ProtocolChecks {
    static func main() throws {
        let secret=Data(0..<32), challenge=Data(0..<16), seed=Data(32..<64), iv=Data(0..<16)
        let legacy=try AirShieldKeys(secret: secret,challenge: challenge,seed: seed)
        assert(legacy.encryption.withUnsafeBytes { Data($0) } == Data(testHex: "5080496832e72e0a4de90f22e7797a3c6277197b4bd29f296bd7142850db1998"))
        let newer=try AirShieldKeys(secret: secret,challenge: challenge,seed: seed,scheme:26)
        // Independently generated using Node's crypto HKDF/AES-CBC/HMAC, not Swift's implementation.
        assert(newer.encryption.withUnsafeBytes { Data($0) } == Data(testHex: "be4a1ce4657ac7e8b9605751cbe0e3ce5b741863b632edc8661dc7b62ac25497"))
        var sender=AirShieldCipher(keys:newer,iv:iv,counter:42)
        let packet=try sender.encrypt(Data(0..<16))
        assert(packet == Data(testHex:"4022da309a7941acda0167817aabc097ab4f02ba80cfac425b0d6723bf567f84e366051ccc5e7078fc5a"))
        var receiver=AirShieldCipher(keys:newer,iv:iv,counter:42)
        let plain=try receiver.decrypt(packet)
        assert(plain == Data(0..<16)+Data(repeating:0xd0,count:16))
        var tampered=packet;tampered[1] ^= 1
        var unchanged=AirShieldCipher(keys:newer,iv:iv,counter:42)
        do { _ = try unchanged.decrypt(tampered); fatalError("Unauthenticated record accepted") }
        catch is BandProtocolError { }
        assert(unchanged.iv == iv && unchanged.counter == 42)
        do { _ = try AirShieldKeys(secret:secret,challenge:challenge,seed:seed,scheme:31);fatalError("Unknown scheme accepted") }
        catch is BandProtocolError { }

        let payload=Data(0..<48)
        let frame=try BandWire.frame(channel:0x9c01,payload:payload)
        var reassembly=DataXReceiver(alwaysPadded:true)
        let first=try reassembly.feed(Data(frame.prefix(32))+Data(repeating:0xd0,count:16))
        assert(first.isEmpty)
        let second=try reassembly.feed(Data(frame.dropFirst(32))+Data(repeating:0xcc,count:12))
        assert(second.count==1 && second[0].payload==payload)
        assert(second[0].channel==0x9c01 && second[0].routedChannel==0x8001)
        var oldAssembly=DataXReceiver()
        let oldPayload=Data(repeating:0,count:27)+Data([0xc1])
        let oldFrames=try oldAssembly.feed(BandWire.frame(channel:5,payload:oldPayload))
        assert(oldFrames.count==1 && oldFrames[0].payload==oldPayload)

        // Complete a scheme-26 setup with a synthetic P-256 peer, then authenticate client startup.
        let session=try BandSession()
        let request=try session.request()
        let client=try ProtoFields(Data(request.dropFirst(12)))
        let peerPrivate=try P256.KeyAgreement.PrivateKey(rawRepresentation:Data(repeating:0,count:31)+Data([1]))
        let peerPoint=Data(peerPrivate.publicKey.x963Representation.dropFirst())
        let peerRequest=try BandWire.frame(channel:0x8001,words:[0x81000005,0x02000001],payload:
            BandWire.field(1,peerPoint)+BandWire.field(2,challenge)+BandWire.field(3,0)+BandWire.field(4,27))
        let enable=try session.feed(peerRequest,at:0).outgoing
        let clientEnable=try ProtoFields(Data(enable.dropFirst(8)))
        let selected=try clientEnable.integer(5)
        assert(selected==26)
        let peerEnable=try BandWire.frame(channel:1,words:[0x02000002],payload:
            BandWire.field(1,peerPoint)+BandWire.field(2,seed)+BandWire.field(3,iv)+BandWire.field(4,42)+BandWire.field(5,27))
        let encryptedStartup=try session.feed(peerEnable,at:0).outgoing
        let clientPublic=try P256.KeyAgreement.PublicKey(x963Representation:Data([4])+client.bytes(1))
        let shared=try peerPrivate.sharedSecretFromKeyAgreement(with:clientPublic).withUnsafeBytes { Data($0) }
        let clientSeed=try clientEnable.bytes(2)
        let clientIV=try clientEnable.bytes(3)
        let counter=try UInt32(clientEnable.integer(4))
        let clientKeys=try AirShieldKeys(secret:shared,challenge:challenge,seed:clientSeed,scheme:26)
        var peerReceiver=AirShieldReceiver(cipher:AirShieldCipher(keys:clientKeys,iv:clientIV,counter:counter))
        let records=try peerReceiver.feed(encryptedStartup)
        var parser=DataXReceiver(alwaysPadded:true)
        var startup:[DataXFrame]=[]
        for record in records { startup += try parser.feed(record) }
        assert(startup.count==2 && startup[0].channel==0x8002)
        print("Scheme-3 regression, independent scheme-26 vectors, authentication rejection, padding/reassembly, tagged routing and synthetic handshake checks passed")
    }
}
