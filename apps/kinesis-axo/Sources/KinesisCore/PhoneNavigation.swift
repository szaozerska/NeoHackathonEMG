import Foundation

/// Keyboard/Keypad-page usages used for navigation, not macOS virtual key codes.
public enum PhoneNavigationKey: UInt8, CaseIterable, Sendable {
    case enter = 0x28, escape = 0x29, tab = 0x2b, space = 0x2c
    case home = 0x4a, pageUp = 0x4b, end = 0x4d, pageDown = 0x4e
    case right = 0x4f, left = 0x50, down = 0x51, up = 0x52
    case f13 = 0x68, f14 = 0x69
}

/// Bits in a HID keyboard modifier byte. These names select the left-hand keys.
public struct PhoneKeyboardModifiers: OptionSet, Hashable, Sendable {
    public let rawValue: UInt8
    public init(rawValue: UInt8) { self.rawValue = rawValue }
    public static let control = Self(rawValue: 1 << 0)
    public static let shift = Self(rawValue: 1 << 1)
    public static let option = Self(rawValue: 1 << 2)
    public static let command = Self(rawValue: 1 << 3)
}

public struct PhoneKeyboardChord: Equatable, Sendable {
    public let key: PhoneNavigationKey
    public let modifiers: PhoneKeyboardModifiers

    public init(_ key: PhoneNavigationKey, modifiers: PhoneKeyboardModifiers = []) {
        self.key = key
        self.modifiers = modifiers
    }
}

/// Relative wheel steps. Positive vertical values mean wheel-up; positive
/// horizontal values mean wheel-right. The host chooses the resulting scroll direction.
public struct PhoneScroll: Equatable, Sendable {
    public let vertical: Int8
    public let horizontal: Int8

    public init?(vertical: Int, horizontal: Int = 0) {
        guard (-127...127).contains(vertical), (-127...127).contains(horizontal),
              vertical != 0 || horizontal != 0 else { return nil }
        self.vertical = Int8(vertical)
        self.horizontal = Int8(horizontal)
    }
}

/// One bounded relative pointer step. Positive x moves right and positive y
/// moves down; the iPhone applies its own pointer speed and acceleration.
public struct PhonePointerMove: Equatable, Sendable {
    public let dx: Int8
    public let dy: Int8

    public init?(dx: Int, dy: Int) {
        guard (-127...127).contains(dx), (-127...127).contains(dy), dx != 0 || dy != 0 else { return nil }
        self.dx = Int8(dx)
        self.dy = Int8(dy)
    }
}

/// Logical report payloads only: no report ID, USB framing, or BLE service is
/// implied. The adapter must supply a matching descriptor and route each kind
/// to the corresponding HID report. The mouse layout is buttons, x, y,
/// vertical wheel, horizontal wheel; it is not the three-byte boot-mouse format.
public struct PhoneHIDReport: Equatable, Sendable {
    public enum Kind: Sendable { case keyboard, mouse }
    public let kind: Kind
    public let bytes: Data

    private init(_ kind: Kind, _ bytes: [UInt8]) {
        self.kind = kind
        self.bytes = Data(bytes)
    }

    public static var releaseReports: [Self] {
        [Self(.keyboard, Array(repeating: 0, count: 8)), Self(.mouse, Array(repeating: 0, count: 5))]
    }

    fileprivate static func keyboard(_ chord: PhoneKeyboardChord) -> [Self] {
        // HID 1.11 Appendix B.1: modifiers, reserved byte, six key slots.
        [Self(.keyboard, [chord.modifiers.rawValue, 0, chord.key.rawValue, 0, 0, 0, 0, 0]),
         Self(.keyboard, Array(repeating: 0, count: 8))]
    }

    fileprivate static func scroll(_ scroll: PhoneScroll) -> [Self] {
        [Self(.mouse, [0, 0, 0, UInt8(bitPattern: scroll.vertical), UInt8(bitPattern: scroll.horizontal)])]
    }

    fileprivate static func move(_ movement: PhonePointerMove) -> [Self] {
        [Self(.mouse, [0, UInt8(bitPattern: movement.dx), UInt8(bitPattern: movement.dy), 0, 0])]
    }

    fileprivate static func click() -> [Self] {
        [Self(.mouse, [1, 0, 0, 0, 0]), Self(.mouse, [0, 0, 0, 0, 0])]
    }
}

public enum PhoneNavigationAction: Equatable, Sendable {
    case key(PhoneKeyboardChord)
    case scroll(PhoneScroll)
    case move(PhonePointerMove)
    /// One left-button press and release at the phone's current pointer position.
    case click

    /// Space is the usual Full Keyboard Access activation key; the user may
    /// configure a different chord. This does not synthesize a touchscreen tap.
    public static let activate = Self.key(PhoneKeyboardChord(.space))

    /// Keyboard and click actions are momentary: adapters must send both reports,
    /// in order. No held-key or held-button operation is exposed by this API.
    public var reports: [PhoneHIDReport] {
        switch self {
        case .key(let chord): PhoneHIDReport.keyboard(chord)
        case .scroll(let scroll): PhoneHIDReport.scroll(scroll)
        case .move(let movement): PhoneHIDReport.move(movement)
        case .click: PhoneHIDReport.click()
        }
    }
}

/// A synchronous gate for immediate output, with no default gesture mappings
/// or action queue. Call this at the transport's write boundary, not when
/// enqueueing work. Any connection transition must disarm it before rearming.
/// Freshness uses the host receipt time: preserve it through buffering, or
/// discard sensor backlog after suspension instead of timestamping it as new.
/// The physical adapter also needs an independent release watchdog because a
/// lost connection can prevent the release report from reaching the phone.
public struct PhoneNavigationSession: Sendable {
    public private(set) var isArmed = false
    private var router = GestureRouter()
    private var armedAt: Double?
    private var lastObservedAt: Double?

    public init() {}

    @discardableResult
    public mutating func arm(at time: Double) -> Bool {
        isArmed = false
        armedAt = nil
        router.reset()
        guard time.isFinite, time >= 0,
              lastObservedAt.map({ time >= $0 }) ?? true else { return false }
        lastObservedAt = time
        armedAt = time
        isArmed = true
        return true
    }

    /// Send these neutral reports if the transport is available. Discard any
    /// previously prepared output. Keep the clock watermark so rearming with
    /// an earlier time cannot make previously received input eligible again.
    public mutating func disarm() -> [PhoneHIDReport] {
        isArmed = false
        armedAt = nil
        router.reset()
        return PhoneHIDReport.releaseReports
    }

    public mutating func connectionChanged() -> [PhoneHIDReport] { disarm() }

    public mutating func reports(for event: BandGesture,
                                 bindings: [RecognizedGesture: PhoneNavigationAction],
                                 at now: Double) -> [PhoneHIDReport] {
        guard isArmed, let armedAt, now.isFinite, now >= 0,
              lastObservedAt.map({ now >= $0 }) ?? true else { return [] }
        lastObservedAt = now
        guard event.receivedAt.isFinite, event.receivedAt >= 0,
              event.receivedAt > armedAt, event.receivedAt <= now,
              now - event.receivedAt <= 0.35,
              let gesture = router.gesture(from: event, now: now),
              let action = bindings[gesture] else { return [] }
        return action.reports
    }
}
