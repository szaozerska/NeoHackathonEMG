import SwiftUI
import KinesisCore

struct PhonePage: View {
    @ObservedObject var model: BandModel
    @ObservedObject var phone: PhoneController

    private let gestures: [RecognizedGesture] = SwipeDirection.allCases.map { .swipe($0) }
        + TapGesture.allCases.map { .tap($0) }

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("your band, on your phone.").font(KinesisType.title).tracking(-1.2)
            Text("Keep the band connected to this Mac and the USB adapter paired to your iPhone. The Mac needs to stay awake.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)

            OpenRow(title: "USB adapter") {
                HStack {
                    Picker("USB port", selection: $phone.selectedPort) {
                        Text("Choose a USB port").tag("")
                        ForEach(portChoices, id: \.self) { port in
                            Text(port.replacingOccurrences(of: "/dev/cu.", with: "")).tag(port)
                        }
                    }.labelsHidden().frame(maxWidth: 220)
                    .disabled(phone.connected)
                    Button { phone.refreshPorts() } label: { Image(systemName: "arrow.clockwise") }
                        .buttonStyle(.plain).accessibilityLabel("Refresh USB ports")
                    Button(phone.connected ? "disconnect USB" : "connect USB") {
                        if phone.connected { phone.disconnect() } else { phone.connect() }
                    }.buttonStyle(KinesisButtonStyle())
                        .disabled(!phone.connected && phone.selectedPort.isEmpty)
                }
            }
            Text(phone.status).font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
                .accessibilityLabel("Phone adapter status")
                .accessibilityValue(phone.status)
            OpenRow(title: "iPhone controls", detail: phone.enabled ? "live" : "paused") {
                Button(phone.enabled ? "pause phone controls" : "enable phone controls") {
                    if phone.enabled { phone.pause() } else { model.enablePhoneControls() }
                }.buttonStyle(KinesisButtonStyle(prominent: !phone.enabled))
                    .disabled(!phone.enabled && (!phone.ready || !model.canEnablePhoneControls))
            }
            HStack {
                Text(phone.lastAction).font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
                Spacer()
                if phone.selected {
                    Button("use Mac controls instead") { model.useMacProfile() }
                        .buttonStyle(.plain).font(KinesisType.caption).foregroundStyle(KinesisStyle.accent)
                }
            }
            if !model.canEnablePhoneControls {
                Text("Connect your band, confirm its wrist, and finish any handwriting recording before enabling phone controls.")
                    .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
            }

            VStack(alignment: .leading, spacing: 10) {
                Text("scroll target").font(KinesisType.label)
                Text("Use these arrows to place the iPhone's mouse pointer over the article or conversation. Wheel input needs a scrollable area under the pointer.")
                    .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
                HStack(spacing: 10) {
                    pointerButton("arrow.left", label: "Move phone pointer left", x: -32, y: 0)
                    pointerButton("arrow.up", label: "Move phone pointer up", x: 0, y: -32)
                    pointerButton("arrow.down", label: "Move phone pointer down", x: 0, y: 32)
                    pointerButton("arrow.right", label: "Move phone pointer right", x: 32, y: 0)
                    Button("test click") { phone.testPointerClick() }
                        .buttonStyle(KinesisButtonStyle())
                }.disabled(!phone.enabled)
            }

            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("scroll distance").font(KinesisType.body)
                    Spacer()
                    Text("\(Int(phone.scrollDistance))").font(KinesisType.label).monospacedDigit()
                }
                PillSlider(value: $phone.scrollDistance, range: 1...120, step: 1, label: "Phone scroll distance")
                HStack {
                    Text("shorter")
                    Spacer()
                    Text("longer")
                }.font(KinesisType.micro).foregroundStyle(KinesisStyle.secondary)
                Toggle("Reverse scroll direction", isOn: $phone.reverseScroll)
                    .font(KinesisType.caption).toggleStyle(.switch).controlSize(.small)
                Text("Each swipe starts the selected scroll distance. A new swipe replaces unfinished movement without adding momentum. Distance depends on the iPhone app.")
                    .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
            }

            VStack(alignment: .leading, spacing: 10) {
                Text("phone gestures").font(KinesisType.label)
                ForEach(gestures, id: \.bindingID) { gesture in
                    HStack {
                        Text(gesture.label).font(KinesisType.body)
                        Spacer()
                        Picker(gesture.label, selection: Binding<PhoneGestureAction>(
                            get: { phone.bindings[gesture.bindingID] ?? PhoneGestureAction.none },
                            set: { phone.bindings[gesture.bindingID] = $0 })) {
                            ForEach(PhoneGestureAction.allCases) { Text($0.title).tag($0) }
                        }.labelsHidden().frame(width: 250)
                    }.padding(.vertical, 3)
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                Text("ChatGPT dictation setup").font(KinesisType.label)
                Text("On your iPhone, save and run a shortcut: ChatGPT → Open your dot → Mode: Dictation. In Full Keyboard Access → Commands, find your saved shortcut and assign F13 if it is listed. While the iPhone records the key, use the button below.")
                    .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
                Button("send F13 to iPhone for setup") {
                    model.pause()
                    phone.sendDictationSetupKey()
                }.buttonStyle(KinesisButtonStyle()).disabled(!phone.ready)
                Toggle("I tested F13 and it starts my iPhone dictation shortcut", isOn: $phone.dictationShortcutReady)
                    .font(KinesisType.caption).toggleStyle(.switch).controlSize(.small)
                Text("The ChatGPT prompt gesture sends F13 once. To stop recording, place the pointer over ChatGPT's Stop/checkmark button and assign Click pointer to a separate gesture. After the text appears, use Return or click Send. Starting dictation never submits your text automatically.")
                    .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
                HStack(spacing: 18) {
                    Link("iPhone keyboard setup", destination: URL(string: "https://support.apple.com/en-ie/guide/iphone/ipha4375873f/26/ios/26")!)
                    Link("ChatGPT shortcut setup", destination: URL(string: "https://learn.chatgpt.com/docs/dots/channels")!)
                }.font(KinesisType.caption)
            }
        }
        .onAppear { phone.refreshPorts() }
    }

    private var portChoices: [String] {
        Set(phone.ports + (phone.selectedPort.isEmpty ? [] : [phone.selectedPort])).sorted()
    }

    private func pointerButton(_ symbol: String, label: String, x: Int, y: Int) -> some View {
        Button { phone.movePointer(horizontal: x, vertical: y) } label: {
            Image(systemName: symbol).frame(width: 26)
        }.buttonStyle(KinesisButtonStyle()).accessibilityLabel(label).help(label)
    }
}
