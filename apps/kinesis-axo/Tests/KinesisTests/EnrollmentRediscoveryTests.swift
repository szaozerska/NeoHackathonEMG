import Foundation
import Testing
import KinesisCore
@testable import Kinesis

private enum RediscoveryFixtureError: Error { case unexpectedOwnershipRequest }

/// Discovery tests never perform an ownership HTTP request or access the Keychain.
private struct RediscoveryPairClient: BandPairClient {
    func pairRequest(_ data: CeremonyPairRequestData) async throws -> MetaPairClient.Pending {
        throw RediscoveryFixtureError.unexpectedOwnershipRequest
    }

    func pair(_ data: CeremonyPairData) async throws -> MetaPairClient.Final {
        throw RediscoveryFixtureError.unexpectedOwnershipRequest
    }
}

@MainActor private final class RediscoveryRig {
    let defaults = MemoryDefaults()
    let connection = RecordedConnection()
    let store = SavedSessionStore()
    let remembered = BandDevice(address: "rediscovery-old", name: "Meta Band 005M", rssi: -55)
    let current = BandDevice(address: "rediscovery-current", name: "Meta Band 005M", rssi: -50)
    let other = BandDevice(address: "rediscovery-other", name: "Meta Band 00W8", rssi: -30)
    let model: BandModel

    init(savedSession: Bool = true, identityExists: @escaping (String) -> Bool = { _ in false }) throws {
        defaults.set(try JSONEncoder().encode(remembered), forKey: "band")
        defaults.set("left", forKey: "bandHand")
        if savedSession { store.saved = MetaSession(accessToken: "fixture-session", userID: "7") }
        model = BandModel(defaults: defaults, connection: connection, controls: RecordingControls(),
                          workspaceNotifications: NotificationCenter(),
                          pairClient: { _ in RediscoveryPairClient() }, sessionStore: store,
                          bandIdentityExists: identityExists, clock: { 100 })
    }
}

@MainActor private func awaitRediscovery(_ condition: () -> Bool) async throws {
    var turns = 0
    while !condition(), turns < 1000 {
        try await Task.sleep(for: .milliseconds(5))
        turns += 1
    }
    try #require(condition())
}

@Suite("Enrollment rediscovery")
struct EnrollmentRediscoveryTests {
    @Test @MainActor func rotatedIdentifierSelectsTheIntendedBandDespiteAStrongerOtherBand() async throws {
        let rig = try RediscoveryRig()
        rig.model.pairBand()
        #expect(rig.connection.requests == ["scan"])
        #expect(rig.model.pairRoute == .scanning)

        rig.connection.send(.devices([rig.other, rig.current]))
        rig.connection.finish()
        try await awaitRediscovery { rig.connection.requests.count == 2 }

        #expect(rig.connection.requests == ["scan", "enroll rediscovery-current"])
        #expect(rig.model.selectedAddress == rig.current.address)
        #expect(rig.model.bandName == rig.current.name)
        let saved = try #require(rig.defaults.data(forKey: "band"))
        let profile = try JSONDecoder().decode(BandDevice.self, from: saved)
        #expect(profile.address == rig.current.address)
        #expect(rig.store.saved?.accessToken == "fixture-session")
        #expect(rig.store.saves == 0 && rig.store.deletions == 0)
        #expect(rig.model.bandHand == .left)
        await rig.model.shutdown()
    }

    @Test @MainActor func missingTargetDoesNotClaimTheOtherBandOrReuseTheStaleIdentifier() async throws {
        let rig = try RediscoveryRig()
        rig.model.pairBand()
        rig.connection.send(.devices([rig.other]))
        rig.connection.finish()
        try await awaitRediscovery { !rig.model.pairInProgress }

        #expect(rig.connection.requests == ["scan"])
        #expect(rig.model.selectedAddress == rig.remembered.address)
        #expect(rig.model.pairFailedStep == .find)
        #expect(rig.model.pairFailure != nil)
        #expect(rig.store.saved?.accessToken == "fixture-session")
        #expect(rig.store.deletions == 0)
        await rig.model.shutdown()
    }

    @Test @MainActor func ambiguousNameDoesNotChooseEitherReplacement() async throws {
        let rig = try RediscoveryRig()
        let duplicate = BandDevice(address: "rediscovery-duplicate", name: rig.current.name, rssi: -70)
        rig.model.pairBand()
        rig.connection.send(.devices([rig.current, rig.other, duplicate]))
        rig.connection.finish()
        try await awaitRediscovery { !rig.model.pairInProgress }

        #expect(rig.connection.requests == ["scan"])
        #expect(rig.model.selectedAddress == rig.remembered.address)
        #expect(rig.model.pairFailedStep == .find)
        #expect(rig.model.pairFailure?.contains("more than one band") == true)
        #expect(rig.model.pairing.detail.contains("more than one band"))
        #expect(rig.store.deletions == 0)
        await rig.model.shutdown()
    }

    @Test @MainActor func theAdvertisedRememberedIdentifierWinsOverAnotherSameNamedBand() async throws {
        let rig = try RediscoveryRig()
        rig.model.pairBand()
        rig.connection.send(.devices([rig.current, rig.other, rig.remembered]))
        rig.connection.finish()
        try await awaitRediscovery { rig.connection.requests.count == 2 }

        #expect(rig.connection.requests == ["scan", "enroll rediscovery-old"])
        #expect(rig.model.selectedAddress == rig.remembered.address)
        #expect(rig.model.pairFailure == nil)
        await rig.model.shutdown()
    }

    @Test @MainActor func successfulSignInRescansBeforeStartingTheOwnershipCeremony() async throws {
        let rig = try RediscoveryRig(savedSession: false)
        rig.model.pairBand()
        #expect(rig.model.enrollmentStage == .login)
        #expect(rig.connection.requests.isEmpty)

        rig.model.enroll(session: MetaSession(accessToken: "new-fixture-session", userID: "8"))
        #expect(rig.connection.requests == ["scan"])
        #expect(rig.model.pairRoute == .scanning)
        rig.connection.send(.devices([rig.other, rig.current]))
        rig.connection.finish()
        try await awaitRediscovery { rig.connection.requests.count == 2 }

        #expect(rig.connection.requests == ["scan", "enroll rediscovery-current"])
        #expect(rig.store.saved?.accessToken == "new-fixture-session")
        #expect(rig.store.saves == 1 && rig.store.deletions == 0)
        #expect(rig.model.hasSavedMetaSession)
        await rig.model.shutdown()
    }

    @Test @MainActor func aRefreshedIdentifierWithAnExistingIdentityConnectsWithoutReplacingIt() async throws {
        let rig = try RediscoveryRig(identityExists: { $0 == "rediscovery-current" })
        rig.model.pairBand()
        #expect(rig.connection.requests == ["scan"])
        rig.connection.send(.devices([rig.other, rig.current]))
        rig.connection.finish()
        try await awaitRediscovery { rig.connection.requests.count == 2 }

        #expect(rig.connection.requests == ["scan", "connect rediscovery-current"])
        #expect(rig.model.selectedAddress == rig.current.address)
        #expect(rig.model.hasBandIdentity)
        #expect(rig.model.enrollmentStage == .idle)
        #expect(rig.store.saves == 0 && rig.store.deletions == 0)
        await rig.model.shutdown()
    }

    @Test @MainActor func cancellationIgnoresLateDiscoveryAndDoesNotContinueEnrollment() async throws {
        let rig = try RediscoveryRig()
        rig.connection.finishesOnStop = false
        rig.model.pairBand()
        #expect(rig.connection.requests == ["scan"])

        rig.model.cancelPairing()
        rig.connection.send(.devices([rig.other, rig.current]))
        rig.connection.finish()
        try await awaitRediscovery { !rig.model.busy }

        #expect(rig.connection.requests == ["scan"])
        #expect(!rig.model.pairInProgress)
        #expect(rig.model.selectedAddress == rig.remembered.address)
        #expect(rig.store.saved?.accessToken == "fixture-session")
        #expect(rig.store.deletions == 0)
        rig.connection.finishesOnStop = true
        await rig.model.shutdown()
    }
}
