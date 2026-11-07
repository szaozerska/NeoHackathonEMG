import Foundation

/// A short wheel trajectory, not an unbounded queue of scroll commands. The
/// receiver determines the distance of each wheel unit on its screen.
public struct PhoneScrollMotion: Sendable {
    private var startedAt = 0.0
    private var lastTick = 0.0
    private var duration = 0.65
    private var distance = 0
    private var emitted = 0
    public private(set) var isActive = false

    public init() {}

    public mutating func stop() { isActive = false; distance = 0; emitted = 0 }

    /// Each gesture replaces unfinished travel with its own fixed distance.
    public mutating func flick(direction: Int, distance amount: Int, at now: Double) {
        guard now.isFinite, now >= 0, direction == -1 || direction == 1 else { stop(); return }
        distance = direction * min(120, max(1, amount))
        emitted = 0
        startedAt = now
        lastTick = now
        duration = 0.65 * max(1, sqrt(Double(abs(distance)) / 48))
        isActive = true
    }

    /// Propose at most eight units. Commit only after the transport accepts the
    /// write, so a busy sender preserves fractions without replaying an action.
    public mutating func step(at now: Double) -> Int {
        guard isActive else { return 0 }
        guard now.isFinite, now >= lastTick, now - lastTick <= 0.15 else { stop(); return 0 }
        lastTick = now
        let elapsed = now - startedAt
        guard elapsed <= duration + 0.12 else { stop(); return 0 }
        let t = min(1, max(0, elapsed / duration))
        let progress = 1 - pow(1 - t, 3)
        // A one-unit gesture must respond on the first normal timer tick rather
        // than waiting for the whole easing interval to reach one integer unit.
        let due = elapsed > 0 ? Int((Double(abs(distance)) * progress).rounded(.up)) : 0
        let count = min(8, max(0, due - emitted))
        if count == 0, t >= 1 { stop() }
        return distance.signum() * count
    }

    public mutating func commit(_ amount: Int) {
        guard isActive, amount.signum() == distance.signum(), abs(amount) <= 8 else { return }
        emitted = min(abs(distance), emitted + abs(amount))
        if emitted == abs(distance) { stop() }
    }
}

public enum PhoneGestureAction: String, CaseIterable, Codable, Identifiable, Sendable {
    case none, scrollUp, scrollDown, chatGPTPrompt, nextItem, previousItem, activate, clickPointer, dismiss, returnKey, stopScrolling
    public var id: String { rawValue }
    public var title: String {
        switch self {
        case .none: "No action"
        case .scrollUp: "Scroll up"
        case .scrollDown: "Scroll down"
        case .chatGPTPrompt: "ChatGPT prompt (F13)"
        case .nextItem: "Next item (Tab)"
        case .previousItem: "Previous item (Shift-Tab)"
        case .activate: "Activate focused item (Space)"
        case .clickPointer: "Click pointer"
        case .dismiss: "Dismiss (Escape)"
        case .returnKey: "Return key"
        case .stopScrolling: "Stop scrolling"
        }
    }

    public var navigation: PhoneNavigationAction? {
        switch self {
        case .chatGPTPrompt: .key(PhoneKeyboardChord(.f13))
        case .nextItem: .key(PhoneKeyboardChord(.tab))
        case .previousItem: .key(PhoneKeyboardChord(.tab, modifiers: [.shift]))
        case .activate: .activate
        case .clickPointer: .click
        case .dismiss: .key(PhoneKeyboardChord(.escape))
        case .returnKey: .key(PhoneKeyboardChord(.enter))
        default: nil
        }
    }

    public static let defaultBindings: [String: Self] = [
        "swipe.up": .scrollUp, "swipe.down": .scrollDown,
        "swipe.left": .previousItem, "swipe.right": .nextItem,
        "tap.indexDoubleTap": .chatGPTPrompt,
        "tap.middleTap": .activate,
        "tap.middleDoubleTap": .stopScrolling,
    ]
}
