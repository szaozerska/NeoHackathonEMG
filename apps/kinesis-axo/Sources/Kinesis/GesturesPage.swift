import AppKit
import SwiftUI
import KinesisCore

struct GesturesPage: View {
    @ObservedObject var model: BandModel
    @State private var family = "swipe"
    @State private var recording: ShortcutTarget?
    @State private var assignmentAfterRecording: RecognizedGesture?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private var actions: [Choice<MacAction>] {
        MacAction.allCases.filter { $0 != .toggleHandwriting || model.developerMode }
            .map { Choice($0, $0.title.lowercased()) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            Text("little moves. your rules.").font(KinesisType.title).tracking(-1.2).reveal(0)
            PillTray(options: ["swipe", "tap", "turn"].map { Choice($0, $0) }, selection: family,
                     select: { family = $0 }, label: "Gesture family").reveal(1)
            VStack(alignment: .leading, spacing: 7) {
                Text(family == "swipe" ? "a shortcut at your fingertips." : family == "tap" ? "taps, and one hold." : "turn it just a little.")
                    .font(KinesisType.headline).tracking(-0.4)
                Text(family == "swipe" ? "slide your thumb across your index finger in any direction." : family == "tap" ? "tap your thumb to your index or middle finger, or hold it on the middle one." : "pinch thumb and index, then turn your wrist. release to reset.")
                    .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
            }.reveal(2)
            GestureLight(model: model) { fires in
            VStack(spacing: 2) {
                if family == "swipe" {
                    ForEach(SwipeDirection.allCases) { direction in
                        assignment(direction.label, symbol: direction.symbol, last: direction == SwipeDirection.allCases.last,
                                   trigger: fires[.swipe(direction)] ?? 0,
                                   gesture: .swipe(direction),
                                   selection: model.mappings[direction] ?? .none) { model.mappings[direction] = $0 }
                    }
                } else if family == "tap" {
                    ForEach(TapGesture.allCases) { tap in
                        assignment(tap.label, symbol: tap.symbol, last: tap == TapGesture.allCases.last,
                                   trigger: fires[.tap(tap)] ?? 0,
                                   gesture: .tap(tap),
                                   selection: model.tapMappings[tap] ?? .none) { model.tapMappings[tap] = $0 }
                    }
                } else {
                    row(symbol: "dial.low", title: "pinch + turn", held: model.dialEngaged && model.live) {
                        PillMenu(options: DialTarget.allCases.map { Choice($0, $0.title.lowercased()) },
                                 selection: model.dialTarget, select: { model.dialTarget = $0 }, label: "Dial controls")
                    }
                    VStack(alignment: .leading, spacing: 14) {
                        HStack {
                            Text("sensitivity").font(KinesisType.body)
                            Spacer()
                            Text(model.dialSensitivity.formatted(.number.precision(.fractionLength(2))) + "×")
                                .font(KinesisType.label).monospacedDigit().contentTransition(.numericText())
                                .animation(KinesisMotion.settle, value: model.dialSensitivity)
                        }
                        PillSlider(value: $model.dialSensitivity, range: 0.5...4, step: 0.25, label: "Dial sensitivity")
                        HStack {
                            Text("more precise")
                            Spacer()
                            Text("less movement")
                        }.font(KinesisType.micro).foregroundStyle(KinesisStyle.secondary)
                    }.padding(.top, 18)
                }
            }
            }
            // A new family's rows arrive the same way a page does.
            .reveal(3).id(family).transition(.asymmetric(insertion: .identity, removal: .opacity.animation(.easeOut(duration: 0.1))))
            Text(model.live ? "perform a gesture and its row lights up." : "connect your band to try them as you edit.")
                .font(KinesisType.micro).foregroundStyle(KinesisStyle.secondary).padding(.top, -10).reveal(4)
            Text(family == "swipe" ? "desktop actions use the Mac’s Control + arrow shortcuts. window and tab actions stay in the current app." : family == "tap" ? "a single tap waits briefly when that finger also has a double-tap or hold action, so the longer gesture takes priority. holding the index finger is the dial, so only the middle finger has a hold." : "volume follows your audio output, including AirPods. brightness controls your Mac’s display; external displays may not respond. pinch again after changing settings.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary).lineSpacing(4).reveal(5)
            if family != "turn" { shortcutSetup }
        }
        .animation(reduceMotion ? nil : KinesisMotion.settle, value: family)
        .sheet(item: $recording) { target in
            ShortcutRecorder(title: target.title,
                             initial: shortcut(for: target),
                             onSave: { shortcut in
                switch target {
                case .dictation: model.dictationShortcut = shortcut
                case .chatGPTDictation: model.chatGPTDictationShortcut = shortcut
                case .chatGPTSend: model.chatGPTSendShortcut = shortcut
                case .gesture(let gesture): model.setCustomShortcut(shortcut, for: gesture)
                }
                if let gesture = assignmentAfterRecording {
                    switch gesture {
                    case .swipe(let direction): model.mappings[direction] = target.action
                    case .tap(let tap): model.tapMappings[tap] = target.action
                    }
                }
                assignmentAfterRecording = nil
                recording = nil
            }, onCancel: { assignmentAfterRecording = nil; recording = nil })
        }
    }

    private var shortcutSetup: some View {
        VStack(alignment: .leading, spacing: 12) {
            OpenRow(title: "macOS Dictation shortcut", detail: model.dictationShortcut?.displayName ?? "needs setup") {
                Button(model.dictationShortcut == nil ? "set shortcut" : "change") { beginRecording(.dictation) }
                    .buttonStyle(KinesisButtonStyle())
            }
            Text("turn on Dictation in macOS System Settings → Keyboard, choose a custom shortcut, then record that same shortcut here. select a text field before performing its gesture; Kinesis leaves that app in focus.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary).lineSpacing(4)
            Button("open Keyboard settings") {
                if let url = URL(string: "x-apple.systempreferences:com.apple.preference.keyboard") { NSWorkspace.shared.open(url) }
            }.buttonStyle(.plain).font(KinesisType.caption).foregroundStyle(KinesisStyle.accent)
            OpenRow(title: "ChatGPT destination") {
                PillTray(options: ChatGPTDestination.allCases.map { Choice($0, $0.title.lowercased()) },
                         selection: model.chatGPTDestination, select: { model.chatGPTDestination = $0 },
                         label: "ChatGPT destination")
            }
            if model.chatGPTDestination == .myDot {
                VStack(alignment: .leading, spacing: 8) {
                    TextField("Paste your dot chat link", text: $model.chatGPTChatLink)
                        .textFieldStyle(.roundedBorder).font(KinesisType.body)
                        .accessibilityLabel("Dot chat link")
                    if !model.chatGPTChatLink.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                       ChatGPTDestination.conversationURL(from: model.chatGPTChatLink) == nil {
                        Text("paste a full codex://threads/… conversation link copied from ChatGPT.")
                            .font(KinesisType.caption).foregroundStyle(KinesisStyle.warning)
                    } else {
                        Text("optional: leave blank for your account’s Dot, or paste its copied chat link to open that exact conversation.")
                            .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
                    }
                }
            }
            OpenRow(title: "ChatGPT Dictation shortcut", detail: model.chatGPTDictationShortcut?.displayName ?? "needs setup") {
                Button(model.chatGPTDictationShortcut == nil ? "set shortcut" : "change") { beginRecording(.chatGPTDictation) }
                    .buttonStyle(KinesisButtonStyle())
            }
            Text("record your ChatGPT Dictation shortcut here. current chat brings ChatGPT to the front; my dot uses the optional chat link above or opens your current account’s Dot. its gesture then sends the configured start or stop shortcut. review the text before sending.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary).lineSpacing(4)
            OpenRow(title: "ChatGPT Send shortcut", detail: model.chatGPTSendShortcut?.displayName ?? "needs setup") {
                Button(model.chatGPTSendShortcut == nil ? "set shortcut" : "change") { beginRecording(.chatGPTSend) }
                    .buttonStyle(KinesisButtonStyle())
            }
            Text("Send in ChatGPT is a separate action. with ChatGPT in front, review the text before performing its gesture. Command-Return is the usual send shortcut; record the exact chord your app uses. Dictation never submits a message automatically.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary).lineSpacing(4)
            Text("air mouse: use its assigned gesture again, or press Escape, to stop. while it is on, index and middle pinches control mouse clicks; use index or middle gesture actions with the air mouse off. thumb swipes keep their assignments, so a swipe works well for Dictation.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary).lineSpacing(4)
        }
    }

    private func shortcut(for target: ShortcutTarget) -> KinesisCore.KeyboardShortcut? {
        switch target {
        case .dictation: model.dictationShortcut
        case .chatGPTDictation: model.chatGPTDictationShortcut
        case .chatGPTSend: model.chatGPTSendShortcut
        case .gesture(let gesture): model.customShortcut(for: gesture)
        }
    }

    private func beginRecording(_ target: ShortcutTarget, assigning gesture: RecognizedGesture? = nil) {
        model.pause()
        assignmentAfterRecording = gesture
        recording = target
    }

    private func assignment(_ label: String, symbol: String, last: Bool, trigger: Int, gesture: RecognizedGesture, selection: MacAction,
                            select: @escaping (MacAction) -> Void) -> some View {
        row(symbol: symbol, title: label.lowercased(), trigger: trigger) {
            VStack(alignment: .trailing, spacing: 8) {
                PillMenu(options: actions, selection: selection, select: { action in
                    if action == .customShortcut && model.customShortcut(for: gesture) == nil {
                        beginRecording(.gesture(gesture), assigning: gesture)
                    } else if action == .dictation && model.dictationShortcut == nil {
                        beginRecording(.dictation, assigning: gesture)
                    } else if action == .chatGPTDictation && model.chatGPTDictationShortcut == nil {
                        beginRecording(.chatGPTDictation, assigning: gesture)
                    } else if action == .chatGPTSend && model.chatGPTSendShortcut == nil {
                        beginRecording(.chatGPTSend, assigning: gesture)
                    } else { select(action) }
                }, label: label)
                if selection == .customShortcut {
                    Button(model.customShortcut(for: gesture)?.displayName ?? "record shortcut") { beginRecording(.gesture(gesture)) }
                        .buttonStyle(.plain).font(KinesisType.caption).foregroundStyle(KinesisStyle.accent)
                        .accessibilityLabel("\(label) custom shortcut")
                }
            }
        }
    }

    private func row<Control: View>(symbol: String, title: String, trigger: Int = 0, held: Bool = false,
                                    @ViewBuilder control: @escaping () -> Control) -> some View {
        Flash(trigger: trigger, held: held) { glow in
            OpenRow(symbol: symbol, title: title, glow: glow) { control() }
        }
    }
}

private enum ShortcutTarget: Identifiable {
    case dictation, chatGPTDictation, chatGPTSend, gesture(RecognizedGesture)
    var gesture: RecognizedGesture? { if case .gesture(let gesture) = self { gesture } else { nil } }
    var id: String {
        switch self {
        case .dictation: "dictation"
        case .chatGPTDictation: "chatGPTDictation"
        case .chatGPTSend: "chatGPTSend"
        case .gesture(let gesture): gesture.bindingID
        }
    }
    var title: String {
        switch self {
        case .dictation: "macOS Dictation shortcut"
        case .chatGPTDictation: "ChatGPT Dictation shortcut"
        case .chatGPTSend: "ChatGPT Send shortcut"
        case .gesture(let gesture): "\(gesture.label) shortcut"
        }
    }
    var action: MacAction {
        switch self {
        case .dictation: .dictation
        case .chatGPTDictation: .chatGPTDictation
        case .chatGPTSend: .chatGPTSend
        case .gesture: .customShortcut
        }
    }
}
