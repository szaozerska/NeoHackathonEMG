import AppKit
import Foundation
import Testing
import KinesisCore
@testable import Kinesis

private let chatGPTFixtureChatLink = "codex://threads/11111111-2222-4333-8444-555555555555?hostId=durable"

@MainActor private final class ChatGPTDictationControls: MacControls {
    struct TargetedShortcut: Equatable {
        let shortcut: KeyboardShortcut
        let processIdentifier: Int32
    }

    var trusted = true
    var frontmostProcessIdentifier: Int32 = 42
    var frontmostApplicationIsChatGPT = true
    var frontmostChatGPTProcessIdentifier: Int32? {
        frontmostApplicationIsChatGPT && frontmostProcessIdentifier == 42 ? 42 : nil
    }
    private(set) var actions: [MacAction] = []
    private(set) var globalShortcuts: [KeyboardShortcut] = []
    private(set) var targetedShortcuts: [TargetedShortcut] = []
    private(set) var activationRequests = 0
    private(set) var activationDestinations: [ChatGPTDestination] = []
    private(set) var activationChatLinks: [String] = []
    private(set) var activationCompletions = 0
    private(set) var accessRequests = 0
    private var pendingActivation: CheckedContinuation<Int32, Error>?
    var cursorLocation: CGPoint? { .zero }
    var displaySize: CGSize { CGSize(width: 1600, height: 1000) }

    func requestAccess() { accessRequests += 1 }
    func post(_ action: MacAction) throws { actions.append(action) }
    func postShortcut(_ shortcut: KeyboardShortcut) throws { globalShortcuts.append(shortcut) }
    func activateChatGPT(destination: ChatGPTDestination, chatLink: String) async throws -> Int32 {
        activationRequests += 1
        activationDestinations.append(destination)
        activationChatLinks.append(chatLink)
        let processIdentifier = try await withCheckedThrowingContinuation { continuation in
            pendingActivation = continuation
        }
        activationCompletions += 1
        return processIdentifier
    }
    func postShortcut(_ shortcut: KeyboardShortcut, toApplication processIdentifier: Int32) throws {
        guard frontmostProcessIdentifier == processIdentifier else {
            throw KinesisError(message: "ChatGPT lost focus before its Dictation shortcut could be sent.")
        }
        targetedShortcuts.append(TargetedShortcut(shortcut: shortcut, processIdentifier: processIdentifier))
    }
    func completeActivation(processIdentifier: Int32 = 42, error: Error? = nil) {
        let continuation = pendingActivation
        pendingActivation = nil
        if let error { continuation?.resume(throwing: error) }
        else { continuation?.resume(returning: processIdentifier) }
    }
    func moveCursor(to point: CGPoint, dragging button: CGMouseButton?) throws -> CGPoint { point }
    func mouseButton(_ button: CGMouseButton, down: Bool, clicks: Int, at point: CGPoint?) throws {}
}

@MainActor private final class ChatGPTDictationClock {
    var now = 100.0
    var readStep = 0.0

    func read() -> Double {
        defer { now += readStep }
        return now
    }
}

/// A manually completed app launch verifies the asynchronous boundary without
/// opening ChatGPT, posting input, touching saved sign-in, or using Bluetooth.
@MainActor private final class ChatGPTDictationRig {
    let defaults: MemoryDefaults
    let connection = RecordedConnection()
    let controls = ChatGPTDictationControls()
    let clock = ChatGPTDictationClock()
    let model: BandModel
    private var sequence: UInt64 = 0

    init(defaults: MemoryDefaults = MemoryDefaults()) {
        self.defaults = defaults
        defaults.set(true, forKey: "setupCompleted")
        let clock = clock
        model = BandModel(defaults: defaults, connection: connection, controls: controls,
                          workspaceNotifications: NotificationCenter(), sessionStore: SavedSessionStore(),
                          clock: { clock.read() }, cursorPacing: 0, cursorFrames: .manual)
    }

    func enable() {
        model.selectedAddress = "chatgpt-dictation-test-band"
        model.connect()
        connection.send(.connected, at: clock.now)
        connection.send(.heartbeat, at: clock.now)
        connection.send(.handedness(.right), at: clock.now)
        model.toggleControls()
        clock.now += 1
    }

    func configure() throws -> KeyboardShortcut {
        let shortcut = try #require(KeyboardShortcut(keyCode: 22, modifiers: [.command], keyLabel: "6"))
        model.chatGPTDictationShortcut = shortcut
        model.mappings[.up] = .chatGPTDictation
        return shortcut
    }

    func configureSend() throws -> KeyboardShortcut {
        let shortcut = try #require(KeyboardShortcut(keyCode: 36, modifiers: [.command], keyLabel: "Return"))
        model.chatGPTSendShortcut = shortcut
        model.mappings[.down] = .chatGPTSend
        return shortcut
    }

    func gesture(finger: String = "thumb", action: String = "up", derived: String = "unknown",
                 timestampUs: UInt64? = nil, receivedAt: Double? = nil) {
        sequence += 1
        let receivedAt = receivedAt ?? clock.now
        connection.send(.gesture(BandGesture(sequence: sequence, timestampUs: timestampUs ?? sequence * 1_000,
                                             finger: finger, action: action, derivedAction: derived,
                                             receivedAt: receivedAt)), at: receivedAt)
    }
}

@MainActor private func waitForChatGPTDictation(_ condition: () -> Bool) async throws {
    for _ in 0..<200 {
        if condition() { return }
        await Task.yield()
    }
    try #require(condition())
}

@MainActor private func settleChatGPTDictation() async {
    for _ in 0..<20 { await Task.yield() }
}

@Suite("ChatGPT Dictation")
struct ChatGPTDictationTests {
    @Test @MainActor func chatGPTDictationConfigurationPersistsIndependentlyOfMacDictation() async throws {
        let rig = ChatGPTDictationRig()
        #expect(rig.model.chatGPTDictationShortcut == nil)
        #expect(rig.model.chatGPTSendShortcut == nil)
        #expect(rig.model.chatGPTDestination == .currentChat)
        #expect(rig.model.chatGPTChatLink.isEmpty)
        let shortcut = try rig.configure()
        let sendShortcut = try rig.configureSend()
        rig.model.chatGPTDestination = .myDot
        rig.model.chatGPTChatLink = chatGPTFixtureChatLink
        let macDictation = try #require(KeyboardShortcut(keyCode: 2, modifiers: [.control, .option], keyLabel: "D"))
        rig.model.dictationShortcut = macDictation
        rig.model.tapMappings[.middleHold] = .chatGPTDictation
        let saved = try #require(rig.defaults.data(forKey: "chatGPTDictationShortcut"))
        #expect(try JSONDecoder().decode(KeyboardShortcut.self, from: saved) == shortcut)
        await rig.model.shutdown()

        let reopened = ChatGPTDictationRig(defaults: rig.defaults)
        #expect(reopened.model.chatGPTDictationShortcut == shortcut)
        #expect(reopened.model.chatGPTSendShortcut == sendShortcut)
        #expect(reopened.model.chatGPTDestination == .myDot)
        #expect(reopened.model.chatGPTChatLink == chatGPTFixtureChatLink)
        #expect(reopened.defaults.string(forKey: "chatGPTChatLink") == chatGPTFixtureChatLink)
        #expect(reopened.model.dictationShortcut == macDictation)
        #expect(reopened.model.tapMappings[.middleHold] == .chatGPTDictation)
        #expect(reopened.model.mappings[.up] == .chatGPTDictation)
        #expect(reopened.model.mappings[.down] == .chatGPTSend)
        reopened.model.chatGPTDictationShortcut = nil
        reopened.model.chatGPTSendShortcut = nil
        #expect(reopened.defaults.data(forKey: "chatGPTDictationShortcut") == nil)
        #expect(reopened.defaults.data(forKey: "chatGPTSendShortcut") == nil)
        #expect(reopened.model.dictationShortcut == macDictation)
        #expect(reopened.controls.activationRequests == 0)
        await reopened.model.shutdown()
    }

    @Test(arguments: [ChatGPTDestination.currentChat, .myDot]) @MainActor
    func chatGPTDictationActivatesTheConfiguredDestination(destination: ChatGPTDestination) async throws {
        let rig = ChatGPTDictationRig()
        let shortcut = try rig.configure()
        rig.model.chatGPTDestination = destination
        rig.model.chatGPTChatLink = chatGPTFixtureChatLink
        rig.enable()
        rig.gesture()
        try await waitForChatGPTDictation { rig.controls.activationRequests == 1 }
        #expect(rig.controls.activationDestinations == [destination])
        #expect(rig.controls.activationChatLinks == [chatGPTFixtureChatLink])
        rig.controls.completeActivation()
        try await waitForChatGPTDictation { rig.controls.targetedShortcuts.count == 1 }
        #expect(rig.controls.targetedShortcuts == [.init(shortcut: shortcut, processIdentifier: 42)])
        #expect(rig.controls.globalShortcuts.isEmpty && rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func chatGPTDictationNeedsAnExplicitShortcutWithoutPausingControls() async throws {
        let rig = ChatGPTDictationRig()
        rig.model.mappings[.up] = .chatGPTDictation
        rig.enable()
        rig.gesture()
        await settleChatGPTDictation()

        let error = try #require(rig.model.error)
        #expect(error.lowercased().contains("chatgpt") && error.lowercased().contains("shortcut"))
        #expect(rig.model.controlsEnabled)
        #expect(rig.controls.activationRequests == 0 && rig.controls.accessRequests == 0)
        #expect(rig.controls.actions.isEmpty && rig.controls.globalShortcuts.isEmpty
                && rig.controls.targetedShortcuts.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func chatGPTDictationRejectsAnInvalidDotChatLinkBeforeOpeningAnApp() async throws {
        let rig = ChatGPTDictationRig()
        _ = try rig.configure()
        rig.model.chatGPTDestination = .myDot
        rig.model.chatGPTChatLink = "https://example.invalid/foo"
        rig.enable()
        rig.gesture()
        await settleChatGPTDictation()

        let error = try #require(rig.model.error)
        #expect(!error.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        #expect(error.lowercased().contains("link"))
        #expect(rig.model.controlsEnabled)
        #expect(rig.controls.activationRequests == 0 && rig.controls.targetedShortcuts.isEmpty
                && rig.controls.globalShortcuts.isEmpty && rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func chatGPTDictationDeduplicatesRawAndDerivedHoldAndPostsOnlyTheConfiguredChord() async throws {
        let rig = ChatGPTDictationRig()
        let shortcut = try rig.configure()
        rig.model.tapMappings[.middleHold] = .chatGPTDictation
        rig.enable()
        rig.gesture(finger: "middle", action: "hold", timestampUs: 1_000_000)
        rig.gesture(finger: "middle", action: "unknown", derived: "buttonHold", timestampUs: 1_000_000)
        try await waitForChatGPTDictation { rig.controls.activationRequests == 1 }
        #expect(rig.controls.targetedShortcuts.isEmpty && rig.controls.globalShortcuts.isEmpty)
        // Launch completion is the only point where the configured chord may
        // be sent. No Return/submit or other keyboard action is appended.
        rig.controls.completeActivation()
        try await waitForChatGPTDictation { rig.controls.targetedShortcuts.count == 1 }
        #expect(rig.controls.targetedShortcuts == [.init(shortcut: shortcut, processIdentifier: 42)])
        #expect(rig.controls.activationRequests == 1 && rig.controls.actions.isEmpty
                && rig.controls.globalShortcuts.isEmpty)
        #expect(rig.model.controlsEnabled && rig.model.error == nil)
        await rig.model.shutdown()
    }

    @Test @MainActor func chatGPTDictationIgnoresAnotherRequestWhileItsLaunchIsPending() async throws {
        let rig = ChatGPTDictationRig()
        let shortcut = try rig.configure()
        rig.enable()
        rig.gesture()
        try await waitForChatGPTDictation { rig.controls.activationRequests == 1 }
        rig.clock.now += 0.5
        rig.gesture()
        await settleChatGPTDictation()
        #expect(rig.controls.activationRequests == 1)
        rig.controls.completeActivation()
        try await waitForChatGPTDictation { rig.controls.targetedShortcuts.count == 1 }
        #expect(rig.controls.targetedShortcuts == [.init(shortcut: shortcut, processIdentifier: 42)])
        await rig.model.shutdown()
    }

    @Test(arguments: [false, true]) @MainActor
    func chatGPTDictationSwipeStopsAirMouseWithoutRepeatingItsDerivedReport(advancingClock: Bool) async throws {
        let rig = ChatGPTDictationRig()
        let shortcut = try rig.configure()
        rig.enable()
        // A real clock advances between requesting Dictation and the mode
        // change rearming the gate; the fixed-clock case cannot expose that.
        rig.clock.readStep = advancingClock ? 0.001 : 0
        rig.model.setAirCursorEnabled(true)
        #expect(rig.model.airCursorEnabled)
        rig.gesture(timestampUs: 1_000_000)
        try await waitForChatGPTDictation { rig.controls.activationRequests == 1 }
        #expect(!rig.model.airCursorEnabled)
        rig.controls.completeActivation()
        try await waitForChatGPTDictation { rig.controls.targetedShortcuts.count == 1 }

        // Mode changes reset the normal router. A classified report arriving
        // after launch completion must still not toggle Dictation back off.
        rig.clock.now += 0.05
        rig.gesture(action: "unknown", derived: "buttonUp", timestampUs: 1_000_000)
        await settleChatGPTDictation()
        #expect(rig.controls.activationRequests == 1)
        #expect(rig.controls.targetedShortcuts == [.init(shortcut: shortcut, processIdentifier: 42)])
        #expect(rig.controls.globalShortcuts.isEmpty && rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    private enum ContextChange: CaseIterable {
        case pause, disconnect, permissionLoss, remap, changeShortcut, changeDestination, changeChatLink, enableAirMouse
    }

    @Test(arguments: ContextChange.allCases) @MainActor
    private func chatGPTDictationCannotPostAfterTheLaunchContextChanges(change: ContextChange) async throws {
        let rig = ChatGPTDictationRig()
        _ = try rig.configure()
        rig.enable()
        rig.gesture()
        try await waitForChatGPTDictation { rig.controls.activationRequests == 1 }
        switch change {
        case .pause: rig.model.pause()
        case .disconnect: rig.model.disconnect()
        case .permissionLoss: rig.controls.trusted = false
        case .remap: rig.model.mappings[.up] = MacAction.none
        case .changeShortcut:
            rig.model.chatGPTDictationShortcut = KeyboardShortcut(keyCode: 3, modifiers: [.command], keyLabel: "F")
        case .changeDestination: rig.model.chatGPTDestination = .myDot
        case .changeChatLink: rig.model.chatGPTChatLink = chatGPTFixtureChatLink
        case .enableAirMouse: rig.model.setAirCursorEnabled(true)
        }
        rig.controls.completeActivation()
        try await waitForChatGPTDictation { rig.controls.activationCompletions == 1 }
        await settleChatGPTDictation()
        #expect(rig.controls.targetedShortcuts.isEmpty && rig.controls.globalShortcuts.isEmpty
                && rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func chatGPTDictationAbandonsALaunchThatTakesLongerThanItsInputBudget() async throws {
        let rig = ChatGPTDictationRig()
        _ = try rig.configure()
        rig.enable()
        rig.gesture()
        try await waitForChatGPTDictation { rig.controls.activationRequests == 1 }
        rig.clock.now += 3.01
        rig.connection.send(.heartbeat, at: rig.clock.now)
        rig.controls.completeActivation()
        try await waitForChatGPTDictation { rig.controls.activationCompletions == 1 }
        await settleChatGPTDictation()
        #expect(rig.controls.targetedShortcuts.isEmpty && rig.controls.globalShortcuts.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func anotherDispatchedActionCancelsThePendingChatGPTDictationLaunch() async throws {
        let rig = ChatGPTDictationRig()
        _ = try rig.configure()
        rig.model.mappings[.right] = .volumeUp
        rig.enable()
        rig.gesture()
        try await waitForChatGPTDictation { rig.controls.activationRequests == 1 }
        rig.clock.now += 0.5
        rig.gesture(action: "right")
        #expect(rig.controls.actions == [.volumeUp])
        rig.controls.completeActivation()
        try await waitForChatGPTDictation { rig.controls.activationCompletions == 1 }
        await settleChatGPTDictation()
        #expect(rig.controls.targetedShortcuts.isEmpty && rig.controls.globalShortcuts.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func chatGPTDictationRejectsStalePausedAndUntrustedInputBeforeLaunching() async throws {
        let rig = ChatGPTDictationRig()
        _ = try rig.configure()
        rig.enable()
        rig.gesture(receivedAt: rig.clock.now - 5)
        rig.model.pause()
        rig.gesture()
        rig.model.toggleControls()
        rig.controls.trusted = false
        rig.clock.now += 1
        rig.gesture()
        await settleChatGPTDictation()
        #expect(rig.controls.activationRequests == 0 && rig.controls.targetedShortcuts.isEmpty)
        #expect(rig.controls.globalShortcuts.isEmpty && rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func chatGPTDictationActivationFailureExplainsTheErrorWithoutSendingInput() async throws {
        let rig = ChatGPTDictationRig()
        _ = try rig.configure()
        rig.enable()
        rig.gesture()
        try await waitForChatGPTDictation { rig.controls.activationRequests == 1 }
        rig.controls.completeActivation(error: KinesisError(message: "ChatGPT could not be opened for Dictation."))
        try await waitForChatGPTDictation { rig.model.error != nil }
        #expect(rig.model.error?.contains("ChatGPT") == true)
        #expect(rig.model.controlsEnabled)
        #expect(rig.controls.targetedShortcuts.isEmpty && rig.controls.globalShortcuts.isEmpty
                && rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func chatGPTDictationNeverFallsBackToAnUntargetedShortcutAfterFocusLoss() async throws {
        let rig = ChatGPTDictationRig()
        _ = try rig.configure()
        rig.enable()
        rig.gesture()
        try await waitForChatGPTDictation { rig.controls.activationRequests == 1 }
        rig.controls.frontmostProcessIdentifier = 99
        rig.controls.completeActivation(processIdentifier: 42)
        try await waitForChatGPTDictation { rig.model.error != nil }
        #expect(rig.model.error?.lowercased().contains("focus") == true)
        #expect(rig.model.controlsEnabled)
        #expect(rig.controls.targetedShortcuts.isEmpty && rig.controls.globalShortcuts.isEmpty
                && rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func chatGPTSendPostsOnlyOneConfiguredChordToTheAlreadyFocusedChatGPT() async throws {
        let rig = ChatGPTDictationRig()
        let shortcut = try rig.configureSend()
        rig.enable()
        rig.gesture(action: "down", timestampUs: 1_000_000)
        rig.gesture(action: "unknown", derived: "buttonDown", timestampUs: 1_000_000)
        await settleChatGPTDictation()
        #expect(rig.controls.targetedShortcuts == [.init(shortcut: shortcut, processIdentifier: 42)])
        #expect(rig.controls.activationRequests == 0 && rig.controls.globalShortcuts.isEmpty
                && rig.controls.actions.isEmpty)
        #expect(rig.model.controlsEnabled && rig.model.error == nil)
        await rig.model.shutdown()
    }

    private enum SendBlock: CaseIterable {
        case missingShortcut, wrongFocus, paused, stale, untrusted, disconnected
    }

    @Test(arguments: SendBlock.allCases) @MainActor
    private func chatGPTSendNeverLaunchesOrPostsWhenItsContextIsInvalid(block: SendBlock) async throws {
        let rig = ChatGPTDictationRig()
        if block == .missingShortcut { rig.model.mappings[.down] = .chatGPTSend }
        else { _ = try rig.configureSend() }
        rig.enable()
        switch block {
        case .wrongFocus: rig.controls.frontmostApplicationIsChatGPT = false
        case .paused: rig.model.pause()
        case .untrusted: rig.controls.trusted = false
        case .disconnected: rig.model.disconnect()
        case .missingShortcut, .stale: break
        }
        rig.gesture(action: "down", receivedAt: block == .stale ? rig.clock.now - 5 : nil)
        await settleChatGPTDictation()
        #expect(rig.controls.activationRequests == 0 && rig.controls.targetedShortcuts.isEmpty
                && rig.controls.globalShortcuts.isEmpty && rig.controls.actions.isEmpty)
        if block == .missingShortcut || block == .wrongFocus {
            let error = try #require(rig.model.error)
            #expect(!error.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            #expect(rig.model.controlsEnabled)
        }
        await rig.model.shutdown()
    }

    @Test @MainActor func chatGPTSendCancelsPendingDictationWithoutOpeningAnotherWindow() async throws {
        let rig = ChatGPTDictationRig()
        _ = try rig.configure()
        let sendShortcut = try rig.configureSend()
        rig.enable()
        rig.gesture()
        try await waitForChatGPTDictation { rig.controls.activationRequests == 1 }
        rig.clock.now += 0.5
        rig.gesture(action: "down")
        #expect(rig.controls.targetedShortcuts == [.init(shortcut: sendShortcut, processIdentifier: 42)])
        rig.controls.completeActivation()
        try await waitForChatGPTDictation { rig.controls.activationCompletions == 1 }
        await settleChatGPTDictation()
        #expect(rig.controls.targetedShortcuts == [.init(shortcut: sendShortcut, processIdentifier: 42)])
        #expect(rig.controls.activationRequests == 1 && rig.controls.globalShortcuts.isEmpty
                && rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    @Test(arguments: [false, true]) @MainActor
    func chatGPTSendSwipeStopsAirMouseWithoutRepeatingItsDerivedReport(advancingClock: Bool) async throws {
        let rig = ChatGPTDictationRig()
        let shortcut = try rig.configureSend()
        rig.enable()
        rig.clock.readStep = advancingClock ? 0.001 : 0
        rig.model.setAirCursorEnabled(true)
        #expect(rig.model.airCursorEnabled)
        rig.gesture(action: "down", timestampUs: 1_000_000)
        #expect(!rig.model.airCursorEnabled)
        #expect(rig.controls.targetedShortcuts == [.init(shortcut: shortcut, processIdentifier: 42)])
        rig.clock.now += 0.05
        rig.gesture(action: "unknown", derived: "buttonDown", timestampUs: 1_000_000)
        await settleChatGPTDictation()
        #expect(rig.controls.targetedShortcuts == [.init(shortcut: shortcut, processIdentifier: 42)])
        #expect(rig.controls.activationRequests == 0 && rig.controls.globalShortcuts.isEmpty
                && rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }
}
