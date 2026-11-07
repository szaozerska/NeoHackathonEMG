import Foundation

public struct ShortcutModifiers: OptionSet, Codable, Hashable, Sendable {
    public let rawValue: UInt8

    public init(rawValue: UInt8) { self.rawValue = rawValue }

    public static let control = ShortcutModifiers(rawValue: 1)
    public static let option = ShortcutModifiers(rawValue: 2)
    public static let shift = ShortcutModifiers(rawValue: 4)
    public static let command = ShortcutModifiers(rawValue: 8)

    fileprivate var isSupported: Bool { rawValue & 0xf0 == 0 }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        let value = ShortcutModifiers(rawValue: try container.decode(UInt8.self))
        guard value.isSupported else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported shortcut modifiers")
        }
        self = value
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

/// An ordinary modified key chord. The label is display text; playback uses the
/// recorded virtual key and modifiers, without interpreting the label as text.
public struct KeyboardShortcut: Codable, Hashable, Sendable {
    public let keyCode: UInt16
    public let modifiers: ShortcutModifiers
    public let keyLabel: String

    public init?(keyCode: UInt16, modifiers: ShortcutModifiers, keyLabel: String) {
        guard Self.valid(keyCode: keyCode, modifiers: modifiers, keyLabel: keyLabel) else { return nil }
        self.keyCode = keyCode
        self.modifiers = modifiers
        self.keyLabel = keyLabel
    }

    public var isValid: Bool { Self.valid(keyCode: keyCode, modifiers: modifiers, keyLabel: keyLabel) }

    public var displayName: String {
        var prefix = ""
        if modifiers.contains(.control) { prefix += "⌃" }
        if modifiers.contains(.option) { prefix += "⌥" }
        if modifiers.contains(.shift) { prefix += "⇧" }
        if modifiers.contains(.command) { prefix += "⌘" }
        return prefix + keyLabel
    }

    private static func valid(keyCode: UInt16, modifiers: ShortcutModifiers, keyLabel: String) -> Bool {
        guard keyCode <= 126, !(54...63).contains(keyCode), modifiers.isSupported,
              !modifiers.intersection([.control, .option, .command]).isEmpty,
              !keyLabel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              keyLabel.count <= 24 else { return false }
        return keyLabel.unicodeScalars.allSatisfy {
            !CharacterSet.controlCharacters.contains($0) && !CharacterSet.newlines.contains($0)
        }
    }

    private enum CodingKeys: String, CodingKey { case keyCode, modifiers, keyLabel }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let keyCode = try container.decode(UInt16.self, forKey: .keyCode)
        let modifiers = try container.decode(ShortcutModifiers.self, forKey: .modifiers)
        let keyLabel = try container.decode(String.self, forKey: .keyLabel)
        guard let shortcut = Self(keyCode: keyCode, modifiers: modifiers, keyLabel: keyLabel) else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath,
                debugDescription: "Invalid keyboard shortcut"))
        }
        self = shortcut
    }
}
