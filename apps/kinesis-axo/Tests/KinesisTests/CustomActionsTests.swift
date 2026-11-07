import AppKit
import Foundation
import Testing
import KinesisCore
@testable import Kinesis

/// Records output without posting events, asking for permissions, or moving a pointer.
@MainActor private final class CustomActionControls: MacControls {
    var trusted = true
    private(set) var actions: [MacAction] = []
    private(set) var shortcuts: [KeyboardShortcut] = []
    private(set) var accessRequests = 0
    var cursorLocation: CGPoint? { .zero }
    var displaySize: CGSize { CGSize(width: 1600, height: 1000) }

    func requestAccess() { accessRequests += 1 }
    func post(_ action: MacAction) throws { actions.append(action) }
    func postShortcut(_ shortcut: KeyboardShortcut) throws { shortcuts.append(shortcut) }
    func moveCursor(to point: CGPoint, dragging button: CGMouseButton?) throws -> CGPoint { point }
    func mouseButton(_ button: CGMouseButton, down: Bool, clicks: Int, at point: CGPoint?) throws {}
}

@MainActor private final class CustomActionClock {
    var now = 100.0
}

@MainActor private final class CustomActionRig {
    let defaults: MemoryDefaults
    let connection = RecordedConnection()
    let controls = CustomActionControls()
    let clock = CustomActionClock()
    let model: BandModel

    init(defaults: MemoryDefaults = MemoryDefaults()) {
        self.defaults = defaults
        defaults.set(true, forKey: "setupCompleted")
        let clock = clock
        model = BandModel(defaults: defaults, connection: connection, controls: controls,
                          workspaceNotifications: NotificationCenter(), sessionStore: SavedSessionStore(),
                          clock: { clock.now })
    }

    func enable() {
        model.selectedAddress = "custom-actions-test-band"
        model.connect()
        connection.send(.connected, at: clock.now)
        connection.send(.heartbeat, at: clock.now)
        connection.send(.handedness(.left), at: clock.now)
        clock.now += 1
        model.toggleControls()
    }

    @discardableResult
    func gesture(sequence: UInt64, finger: String = "thumb", action: String = "up", at time: Double? = nil) -> BandGesture {
        let receivedAt = time ?? clock.now
        let gesture = BandGesture(sequence: sequence, timestampUs: sequence * 1000,
                                  finger: finger, action: action, receivedAt: receivedAt)
        connection.send(.gesture(gesture), at: receivedAt)
        return gesture
    }
}

@Suite("Custom Mac actions")
struct CustomActionsTests {
    @Test @MainActor func differentGestureShortcutsAndDictationSurviveRecreation() async throws {
        let rig = CustomActionRig()
        let dictation = try #require(KeyboardShortcut(keyCode: 2, modifiers: [.control, .option], keyLabel: "D"))
        let swipe = try #require(KeyboardShortcut(keyCode: 35, modifiers: [.command, .shift], keyLabel: "P"))
        let tap = try #require(KeyboardShortcut(keyCode: 40, modifiers: [.control, .command], keyLabel: "K"))
        rig.model.dictationShortcut = dictation
        rig.model.setCustomShortcut(swipe, for: .swipe(.up))
        rig.model.setCustomShortcut(tap, for: .tap(.indexDoubleTap))
        rig.model.mappings[.up] = .customShortcut
        rig.model.tapMappings[.indexDoubleTap] = .customShortcut

        #expect(rig.model.customShortcut(for: .swipe(.up)) == swipe)
        #expect(rig.model.customShortcut(for: .tap(.indexDoubleTap)) == tap)
        #expect(rig.model.customShortcut(for: .swipe(.down)) == nil)
        let savedDictation = try #require(rig.defaults.data(forKey: "dictationShortcut"))
        #expect(try JSONDecoder().decode(KeyboardShortcut.self, from: savedDictation) == dictation)
        let savedCustom = try #require(rig.defaults.data(forKey: "customShortcuts"))
        let decoded = try JSONDecoder().decode([String: KeyboardShortcut].self, from: savedCustom)
        #expect(decoded["swipe.up"] == swipe)
        #expect(decoded["tap.indexDoubleTap"] == tap)
        #expect(decoded.count == 2)
        await rig.model.shutdown()

        let reopened = CustomActionRig(defaults: rig.defaults)
        #expect(reopened.model.dictationShortcut == dictation)
        #expect(reopened.model.customShortcut(for: .swipe(.up)) == swipe)
        #expect(reopened.model.customShortcut(for: .tap(.indexDoubleTap)) == tap)
        #expect(reopened.model.customShortcut(for: .swipe(.down)) == nil)
        #expect(reopened.model.mappings[.up] == .customShortcut)
        #expect(reopened.model.tapMappings[.indexDoubleTap] == .customShortcut)
        await reopened.model.shutdown()
    }

    @Test @MainActor func liveSwipePostsConfiguredDictationOnlyOnce() async throws {
        let rig = CustomActionRig()
        let shortcut = try #require(KeyboardShortcut(keyCode: 2, modifiers: [.control, .option], keyLabel: "D"))
        rig.model.dictationShortcut = shortcut
        rig.model.mappings[.up] = .dictation
        rig.enable()
        #expect(rig.model.controlsEnabled && rig.model.live)

        let swipe = rig.gesture(sequence: 42)
        rig.connection.send(.gesture(swipe), at: swipe.receivedAt)
        #expect(rig.controls.shortcuts == [shortcut])
        #expect(rig.controls.actions.isEmpty)
        #expect(rig.model.controlsEnabled && rig.model.error == nil)
        await rig.model.shutdown()
    }

    @Test @MainActor func customShortcutUsesOnlyItsOwnGestureAndDeduplicatesEachReport() async throws {
        let rig = CustomActionRig()
        let swipeShortcut = try #require(KeyboardShortcut(keyCode: 35, modifiers: [.command, .shift], keyLabel: "P"))
        let tapShortcut = try #require(KeyboardShortcut(keyCode: 40, modifiers: [.control, .command], keyLabel: "K"))
        for direction in SwipeDirection.allCases { rig.model.mappings[direction] = MacAction.none }
        for tap in TapGesture.allCases { rig.model.tapMappings[tap] = MacAction.none }
        rig.model.mappings[.up] = .customShortcut
        rig.model.tapMappings[.indexDoubleTap] = .customShortcut
        rig.model.setCustomShortcut(swipeShortcut, for: .swipe(.up))
        rig.model.setCustomShortcut(tapShortcut, for: .tap(.indexDoubleTap))
        rig.enable()

        rig.gesture(sequence: 1, action: "down")
        rig.gesture(sequence: 2, finger: "index", action: "tap")
        #expect(rig.controls.shortcuts.isEmpty && rig.controls.actions.isEmpty)
        let swipe = rig.gesture(sequence: 3)
        rig.connection.send(.gesture(swipe), at: swipe.receivedAt)
        #expect(rig.controls.shortcuts == [swipeShortcut])
        rig.clock.now += 1
        let tap = rig.gesture(sequence: 4, finger: "index", action: "doubletap")
        rig.connection.send(.gesture(tap), at: tap.receivedAt)
        #expect(rig.controls.shortcuts == [swipeShortcut, tapShortcut])
        #expect(rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    @Test(arguments: [MacAction.dictation, .customShortcut])
    @MainActor func missingShortcutExplainsConfigurationWithoutPausingOrPosting(action: MacAction) async throws {
        let rig = CustomActionRig()
        rig.model.mappings[.up] = action
        rig.enable()
        rig.gesture(sequence: 1)

        let message = try #require(rig.model.error)
        #expect(!message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        #expect(message.lowercased().contains(action == .dictation ? "dictation" : "shortcut"))
        #expect(rig.model.controlsEnabled)
        #expect(rig.controls.shortcuts.isEmpty && rig.controls.actions.isEmpty)
        #expect(rig.controls.accessRequests == 0)
        await rig.model.shutdown()
    }

    @Test(arguments: [MacAction.dictation, .customShortcut])
    @MainActor func stalePausedAndUntrustedGesturesNeverPostShortcuts(action: MacAction) async throws {
        let rig = CustomActionRig()
        let shortcut = try #require(KeyboardShortcut(keyCode: 2, modifiers: [.control, .option], keyLabel: "D"))
        rig.model.dictationShortcut = shortcut
        rig.model.setCustomShortcut(shortcut, for: .swipe(.up))
        rig.model.mappings[.up] = action
        rig.enable()

        rig.gesture(sequence: 1, at: rig.clock.now - 5)
        // An input captured just before controls were armed is also ineligible.
        rig.gesture(sequence: 2, at: rig.clock.now - 0.1)
        rig.model.pause()
        rig.clock.now += 1
        rig.gesture(sequence: 3)
        rig.model.toggleControls()
        #expect(rig.model.controlsEnabled)
        rig.controls.trusted = false
        rig.clock.now += 1
        rig.gesture(sequence: 4)

        #expect(rig.controls.shortcuts.isEmpty && rig.controls.actions.isEmpty)
        await rig.model.shutdown()
    }

    @Test @MainActor func constructedShortcutEventsCarryTheirKeyModifiersTagAndNoAutorepeat() throws {
        let variants: [(ShortcutModifiers, CGEventFlags)] = [
            ([.control, .option, .shift, .command], [.maskControl, .maskAlternate, .maskShift, .maskCommand]),
            ([.command], [.maskCommand]),
        ]
        let relevantFlags: CGEventFlags = [.maskControl, .maskAlternate, .maskShift, .maskCommand]
        for (modifiers, expectedFlags) in variants {
            let shortcut = try #require(KeyboardShortcut(keyCode: 0, modifiers: modifiers, keyLabel: "A"))
            let (down, up) = try MacShortcuts.events(for: shortcut)
            #expect(down.type == .keyDown && up.type == .keyUp)
            for event in [down, up] {
                #expect(event.getIntegerValueField(.keyboardEventKeycode) == 0)
                #expect(event.flags.intersection(relevantFlags) == expectedFlags)
                #expect(event.getIntegerValueField(.eventSourceUserData) == MacShortcuts.shortcutEventTag)
                #expect(event.getIntegerValueField(.keyboardEventAutorepeat) == 0)
            }
        }
    }
}
