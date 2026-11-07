import CryptoKit
import Foundation
import Testing
@testable import KinesisCore

private func airShieldVector(_ hex: String) -> Data {
    Data(stride(from: 0, to: hex.count, by: 2).map {
        UInt8(hex[hex.index(hex.startIndex, offsetBy: $0)..<hex.index(hex.startIndex, offsetBy: $0 + 2)], radix: 16)!
    })
}

@Suite("Verified AirShield schemes")
struct AirShieldScheme26Tests {
    // Synthetic vectors generated independently with Python cryptography 46:
    // HKDF-SHA256, AES-256-CBC and stdlib HMAC. Scheme 26's fixed rules match
    // 896kb/air-gestures docs/hardware-day.md (September 25 / October 22, 2026).
    private let secret = Data(0..<32)
    private let challenge = Data(0..<16)
    private let seed = Data(32..<64)
    private let iv = Data(0..<16)
    private let legacyPackets = [
        "408dbba2dd4240ddef00950f104ab6db2b4b6daec6a60759ba46",
        "40255fe35f459babd4004cbb031200fee11ed6e2084c6279cf8e",
    ].map(airShieldVector)
    private let modernPackets = [
        "4036b76ff1742f4f8f0167817aabc097ab4f02ba80cfac425b0d6723bf567f84e366051ccc5e7078fc5a",
        "40da5cf0317009e05100f65a7561b833b061b5a73493a5f015a0",
    ].map(airShieldVector)

    private func keys(_ scheme: AirShieldScheme) throws -> AirShieldKeys {
        try AirShieldKeys(secret: secret, challenge: challenge, seed: seed, scheme: scheme)
    }

    @Test func keyDerivationMatchesIndependentVectorsForBothSchemes() throws {
        let legacy = try keys(.scheme3)
        let modern = try keys(.scheme26)
        #expect(legacy.encryption.withUnsafeBytes { Data($0) } == airShieldVector(
            "5080496832e72e0a4de90f22e7797a3c6277197b4bd29f296bd7142850db1998"))
        #expect(modern.encryption.withUnsafeBytes { Data($0) } == airShieldVector(
            "be4a1ce4657ac7e8b9605751cbe0e3ce5b741863b632edc8661dc7b62ac25497"))
        #expect(modern.mac.withUnsafeBytes { Data($0) } == modern.encryption.withUnsafeBytes { Data($0) })
        #expect(legacy.mac.withUnsafeBytes { Data($0) } == legacy.encryption.withUnsafeBytes { Data($0) })
    }

    @Test func legacyDefaultPacketsRemainByteForByteIdentical() throws {
        let legacyKeys = try AirShieldKeys(secret: secret, challenge: challenge, seed: seed)
        var sender = AirShieldCipher(keys: legacyKeys, iv: iv, counter: .max)
        #expect(try sender.encrypt(Data(0..<16)) == legacyPackets[0])
        #expect(sender.counter == 0)
        #expect(try sender.encrypt(Data("abc".utf8)) == legacyPackets[1])
        #expect(sender.counter == 1)
    }

    @Test func modernPacketsMatchIndependentKDFPrefixPaddingAndChainingVectors() throws {
        var sender = AirShieldCipher(keys: try keys(.scheme26), iv: iv, counter: .max, scheme: .scheme26)
        #expect(try sender.encrypt(Data(0..<16)) == modernPackets[0])
        #expect(sender.counter == 0)
        #expect(try sender.encrypt(Data("abc".utf8)) == modernPackets[1])
        #expect(sender.counter == 1)
        #expect(sender.iv == Data(modernPackets[1].suffix(16)))
    }

    @Test func decryptsIndependentModernPacketsAndRetainsFullBlockPadding() throws {
        var receiver = AirShieldCipher(keys: try keys(.scheme26), iv: iv, counter: .max, scheme: .scheme26)
        #expect(try receiver.decrypt(modernPackets[0]) == Data(0..<16) + Data(repeating: 0xd0, count: 16))
        #expect(try receiver.decrypt(modernPackets[1]) == Data("abc".utf8) + Data(repeating: 0xcd, count: 13))
        #expect(receiver.counter == 1)
        #expect(receiver.iv == Data(modernPackets[1].suffix(16)))
    }

    @Test func authenticationFailuresNeverAdvanceIVOrCounter() throws {
        for index in [1, 10, modernPackets[0].count - 1] {
            var corrupted = modernPackets[0]
            corrupted[index] ^= 1
            var receiver = AirShieldCipher(keys: try keys(.scheme26), iv: iv, counter: .max, scheme: .scheme26)
            #expect(throws: BandProtocolError.self) { try receiver.decrypt(corrupted) }
            #expect(receiver.iv == iv)
            #expect(receiver.counter == .max)
            // A rejected packet leaves the independent valid packet usable.
            #expect(try receiver.decrypt(modernPackets[0]) == Data(0..<16) + Data(repeating: 0xd0, count: 16))
        }
    }

    @Test func wrongSchemeAndCounterCannotAuthenticateModernPackets() throws {
        var wrongScheme = AirShieldCipher(keys: try keys(.scheme26), iv: iv, counter: .max)
        #expect(throws: BandProtocolError.self) { try wrongScheme.decrypt(modernPackets[0]) }
        #expect(wrongScheme.counter == .max)
        var wrongCounter = AirShieldCipher(keys: try keys(.scheme26), iv: iv, counter: 0, scheme: .scheme26)
        #expect(throws: BandProtocolError.self) { try wrongCounter.decrypt(modernPackets[0]) }
        #expect(wrongCounter.iv == iv)
    }

    @Test func malformedAndTruncatedPacketsFailBeforeAnyCipherStateChanges() throws {
        var wrongMarker = modernPackets[0]
        wrongMarker[0] = 0x41
        var wrongCount = modernPackets[0]
        wrongCount[9] = 0
        let invalid = [Data(), Data([0x40]), Data([0x40]) + Data(repeating: 0, count: 8),
                       Data(modernPackets[0].prefix(25)), Data(modernPackets[0].dropLast()),
                       modernPackets[0] + Data([0]), wrongMarker, wrongCount]
        for packet in invalid {
            var receiver = AirShieldCipher(keys: try keys(.scheme26), iv: iv, counter: .max, scheme: .scheme26)
            #expect(throws: BandProtocolError.self) { try receiver.decrypt(packet) }
            #expect(receiver.iv == iv)
            #expect(receiver.counter == .max)
        }
    }

    @Test func modernPaddingRespectsTheMaximumEncryptedRecordSize() throws {
        var modern = AirShieldCipher(keys: try keys(.scheme26), iv: iv, counter: 1, scheme: .scheme26)
        #expect(try modern.encrypt(Data(repeating: 0, count: 4095)).count == 4106)
        let beforeIV = modern.iv
        let beforeCounter = modern.counter
        #expect(throws: BandProtocolError.self) { try modern.encrypt(Data(repeating: 0, count: 4096)) }
        #expect(modern.iv == beforeIV)
        #expect(modern.counter == beforeCounter)
        var legacy = AirShieldCipher(keys: try keys(.scheme3), iv: iv, counter: 1)
        #expect(try legacy.encrypt(Data(repeating: 0, count: 4096)).count == 4106)
        #expect(throws: BandProtocolError.self) { try legacy.encrypt(Data()) }
    }

    @Test func fragmentedModernTransportRetainsAuthenticationAndCounterChaining() throws {
        let cipher = AirShieldCipher(keys: try keys(.scheme26), iv: iv, counter: .max, scheme: .scheme26)
        var receiver = AirShieldReceiver(cipher: cipher)
        var plaintext: [Data] = []
        for byte in modernPackets[0] + modernPackets[1] { plaintext += try receiver.feed(Data([byte])) }
        try receiver.finish()
        #expect(plaintext == [Data(0..<16) + Data(repeating: 0xd0, count: 16),
                              Data("abc".utf8) + Data(repeating: 0xcd, count: 13)])
        #expect(receiver.cipher.counter == 1)
    }
}
