import Foundation
import Testing
@testable import KinesisCore

@Test func shortcutRoundTripPreservesPhysicalChordAndDisplayLabel() throws {
    let shortcut = try #require(KeyboardShortcut(keyCode: 6,
        modifiers: [.control, .option, .shift, .command], keyLabel: "Z"))
    #expect(shortcut.isValid)
    #expect(shortcut.displayName == "⌃⌥⇧⌘Z")
    let data = try JSONEncoder().encode(shortcut)
    let object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    #expect(object["modifiers"] as? Int == 15)
    #expect(try JSONDecoder().decode(KeyboardShortcut.self, from: data) == shortcut)
    #expect(Set([shortcut, shortcut]).count == 1)
}

@Test func ordinaryChordRequiresCommandOptionOrControlAndKnownModifierBits() {
    for rawValue in UInt8(0)...UInt8(15) {
        let modifiers = ShortcutModifiers(rawValue: rawValue)
        let shortcut = KeyboardShortcut(keyCode: 0, modifiers: modifiers, keyLabel: "A")
        #expect((shortcut != nil) == (rawValue != 0 && rawValue != 4))
    }
    for rawValue in [UInt8(16), 17, 31, 128, 255] {
        #expect(KeyboardShortcut(keyCode: 0, modifiers: ShortcutModifiers(rawValue: rawValue), keyLabel: "A") == nil)
    }
}

@Test func shortcutRejectsModifierOnlyAndOutOfRangeVirtualKeys() {
    for keyCode in UInt16(54)...UInt16(63) {
        #expect(KeyboardShortcut(keyCode: keyCode, modifiers: .command, keyLabel: "modifier") == nil)
    }
    for keyCode in [UInt16(127), 256, .max] {
        #expect(KeyboardShortcut(keyCode: keyCode, modifiers: .command, keyLabel: "key") == nil)
    }
    for keyCode in [UInt16(0), 53, 64, 126] {
        #expect(KeyboardShortcut(keyCode: keyCode, modifiers: .option, keyLabel: "key")?.isValid == true)
    }
}

@Test func shortcutDisplayLabelIsBoundedAndCannotContainControlCharacters() {
    for label in ["", "   ", String(repeating: "x", count: 25), "A\nB", "A\rB", "A\tB",
                  "A\0B", "A\u{1b}B", "A\u{2028}B", "A\u{2029}B"] {
        #expect(KeyboardShortcut(keyCode: 0, modifiers: .command, keyLabel: label) == nil)
    }
    for label in [String(repeating: "x", count: 24), "é", "←", "Space", "⌫"] {
        #expect(KeyboardShortcut(keyCode: 0, modifiers: .command, keyLabel: label)?.isValid == true)
    }
}

@Test func shortcutDecoderCannotBypassChordValidation() throws {
    let invalid: [[String: Any]] = [
        ["keyCode": 63, "modifiers": 8, "keyLabel": "Fn"],
        ["keyCode": 127, "modifiers": 8, "keyLabel": "key"],
        ["keyCode": -1, "modifiers": 8, "keyLabel": "key"],
        ["keyCode": 6, "modifiers": 0, "keyLabel": "Z"],
        ["keyCode": 6, "modifiers": 4, "keyLabel": "Z"],
        ["keyCode": 6, "modifiers": 17, "keyLabel": "Z"],
        ["keyCode": 6, "modifiers": 256, "keyLabel": "Z"],
        ["keyCode": 6, "modifiers": true, "keyLabel": "Z"],
        ["keyCode": 6, "modifiers": 8, "keyLabel": ""],
        ["keyCode": 6, "modifiers": 8, "keyLabel": "Z\n"],
        ["keyCode": 6, "modifiers": 8, "keyLabel": String(repeating: "Z", count: 25)],
        ["keyCode": 6, "modifiers": 8],
    ]
    for value in invalid {
        let data = try JSONSerialization.data(withJSONObject: value)
        #expect(throws: DecodingError.self) {
            try JSONDecoder().decode(KeyboardShortcut.self, from: data)
        }
    }
}

@Test func gestureBindingIdentifiersAreStableAndDistinct() {
    let gestures = SwipeDirection.allCases.map(RecognizedGesture.swipe)
        + TapGesture.allCases.map(RecognizedGesture.tap)
    #expect(gestures.map(\.bindingID) == ["swipe.left", "swipe.right", "swipe.up", "swipe.down",
        "tap.indexTap", "tap.indexDoubleTap", "tap.middleTap", "tap.middleDoubleTap", "tap.middleHold"])
    #expect(Set(gestures.map(\.bindingID)).count == gestures.count)
}

@Test func configurableActionsHaveNoImplicitShortcutAndPreserveExistingActionIdentity() {
    #expect(MacAction.dictation.title == "Start or stop Dictation")
    #expect(MacAction.customShortcut.title == "Custom keyboard shortcut")
    for action in [MacAction.dictation, .customShortcut] {
        #expect(action.shortcut == "configured shortcut")
        #expect(action.keyCode == nil)
        #expect(!action.usesCommand && !action.usesControl && !action.usesShift)
        #expect(!action.isKinesisSwitch)
    }
    #expect(MacAction(rawValue: "toggleAirCursor") == .toggleAirCursor)
    #expect(MacAction.toggleAirCursor.title == "Air mouse on / off")
    #expect(MacAction.toggleAirCursor.isKinesisSwitch && MacAction.toggleHandwriting.isKinesisSwitch)
    #expect(MacAction.previousDesktop.rawValue == "previousDesktop")
    #expect(MacAction.previousDesktop.keyCode == 123 && MacAction.previousDesktop.usesControl)
}
