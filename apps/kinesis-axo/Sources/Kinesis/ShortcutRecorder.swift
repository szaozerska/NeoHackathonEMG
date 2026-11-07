import AppKit
import SwiftUI
import KinesisCore

struct ShortcutRecorder: View {
    let title: String
    let initial: KinesisCore.KeyboardShortcut?
    let onSave: (KinesisCore.KeyboardShortcut) -> Void
    let onCancel: () -> Void
    @State private var candidate: KinesisCore.KeyboardShortcut?
    @State private var problem: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(title).font(KinesisType.headline)
            Text("press a key with Control, Option or Command. Shift can be included. modifier-only shortcuts such as Fn twice are not supported.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
            ShortcutCapture(onShortcut: { candidate = $0; problem = nil },
                            onCancel: onCancel, onInvalid: { problem = "include Control, Option or Command with a key." })
                .frame(height: 70)
                .overlay {
                    Text(candidate?.displayName ?? initial?.displayName ?? "press your shortcut")
                        .font(.system(size: 24, weight: .medium)).allowsHitTesting(false)
                }
                .background(KinesisStyle.tray, in: RoundedRectangle(cornerRadius: 12))
                .accessibilityLabel("Record keyboard shortcut")
            if let problem { Text(problem).font(KinesisType.caption).foregroundStyle(KinesisStyle.warning) }
            Text("controls are paused while you record. enable controls again after saving.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
            HStack {
                Button("cancel", action: onCancel).buttonStyle(KinesisButtonStyle())
                Spacer()
                Button("save shortcut") { if let shortcut = candidate ?? initial { onSave(shortcut) } }
                    .buttonStyle(KinesisButtonStyle(prominent: true)).disabled(candidate == nil && initial == nil)
            }
        }
        .padding(30).frame(width: 460)
    }
}

/// Observes only key-down events in this sheet's own window, and consumes the
/// recorded chord before Kinesis's menus can act on it. No global listener.
private struct ShortcutCapture: NSViewRepresentable {
    let onShortcut: (KinesisCore.KeyboardShortcut) -> Void
    let onCancel: () -> Void
    let onInvalid: () -> Void

    @MainActor final class Coordinator {
        var parent: ShortcutCapture
        var monitor: Any?
        init(_ parent: ShortcutCapture) { self.parent = parent }
        func stop() {
            if let monitor { NSEvent.removeMonitor(monitor) }
            monitor = nil
        }
    }

    final class CaptureView: NSView {
        override var acceptsFirstResponder: Bool { true }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            window?.makeFirstResponder(self)
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> CaptureView {
        let view = CaptureView()
        let coordinator = context.coordinator
        coordinator.monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak view, weak coordinator] event in
            guard let view, let window = view.window, event.window === window,
                  let coordinator else { return event }
            guard !event.isARepeat else { return nil }
            guard event.cgEvent?.getIntegerValueField(.eventSourceUserData) != MacShortcuts.shortcutEventTag else { return nil }
            var modifiers: ShortcutModifiers = []
            if event.modifierFlags.contains(.control) { modifiers.insert(.control) }
            if event.modifierFlags.contains(.option) { modifiers.insert(.option) }
            if event.modifierFlags.contains(.shift) { modifiers.insert(.shift) }
            if event.modifierFlags.contains(.command) { modifiers.insert(.command) }
            if event.keyCode == 53 && modifiers.isEmpty { coordinator.parent.onCancel(); return nil }
            // Keep the sheet's Save/Cancel controls reachable from the keyboard.
            if event.keyCode == 48 && modifiers.subtracting(.shift).isEmpty { return event }
            guard window.firstResponder === view else { return event }
            let functionKeys: Set<UInt16> = [36, 48, 76, 115, 116, 117, 119, 121, 123, 124, 125, 126,
                122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, 105, 107, 113]
            if event.modifierFlags.contains(.function) && !functionKeys.contains(event.keyCode) {
                coordinator.parent.onInvalid()
                return nil
            }
            let label = Self.keyLabel(for: event)
            if let shortcut = KinesisCore.KeyboardShortcut(keyCode: event.keyCode, modifiers: modifiers, keyLabel: label) {
                coordinator.parent.onShortcut(shortcut)
            } else { coordinator.parent.onInvalid() }
            return nil
        }
        return view
    }

    func updateNSView(_ view: CaptureView, context: Context) { context.coordinator.parent = self }
    static func dismantleNSView(_ view: CaptureView, coordinator: Coordinator) { coordinator.stop() }

    private static func keyLabel(for event: NSEvent) -> String {
        let special: [UInt16: String] = [36: "Return", 48: "Tab", 49: "Space", 51: "Delete", 53: "Escape",
            76: "Enter", 115: "Home", 116: "Page Up", 117: "Forward Delete", 119: "End", 121: "Page Down",
            123: "←", 124: "→", 125: "↓", 126: "↑",
            122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7", 100: "F8",
            101: "F9", 109: "F10", 103: "F11", 111: "F12", 105: "F13", 107: "F14", 113: "F15"]
        return special[event.keyCode] ?? event.charactersIgnoringModifiers?.uppercased() ?? ""
    }
}
