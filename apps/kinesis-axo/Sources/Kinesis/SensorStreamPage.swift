import AppKit
import SwiftUI

struct SensorStreamPage: View {
    @ObservedObject var model: BandModel
    @ObservedObject var stream: SensorStreamController

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("signals, in real time.").font(KinesisType.title).tracking(-1.2)
            Text("Read the band from your own code while Kinesis stays connected. The feed includes raw EMG, gyro, orientation, and decoded gestures, with timestamps.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
                .fixedSize(horizontal: false, vertical: true)
            OpenRow(title: "local sensor feed", detail: stream.server.statusText) {
                Toggle("Local sensor feed", isOn: Binding(get: { model.sensorStreamEnabled }, set: { enabled in
                    if enabled { model.startSensorStream() } else { model.stopSensorStream() }
                }))
                .toggleStyle(KinesisToggleStyle())
                .disabled(!model.sensorStreamEnabled && model.modelControlsUnavailable)
            }
            if let error = model.sensorStreamError { ErrorNote(text: error) }
            if stream.enabled {
                HStack {
                    Text("127.0.0.1 · \(stream.server.clientCount) connected \(stream.server.clientCount == 1 ? "reader" : "readers")")
                        .font(KinesisType.micro).foregroundStyle(KinesisStyle.secondary)
                    Spacer()
                    Button("copy stream URL") { copyURL() }.buttonStyle(KinesisButtonStyle(prominent: true))
                        .disabled(stream.server.endpointURL == nil)
                }
                Text("The link works on this Mac and changes each time you start the feed. Stop the feed to disconnect every reader. It starts off when Kinesis opens.")
                    .font(KinesisType.micro).foregroundStyle(KinesisStyle.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 28) {
                Readout(symbol: "waveform.path", value: emgState, label: "raw EMG")
                Readout(symbol: "gyroscope", value: feedState, label: "gyro + orientation")
                Readout(symbol: "hand.draw", value: feedState, label: "band gestures")
                Spacer(minLength: 0)
            }
            if let error = model.rawEMGError { ErrorNote(text: error) }
            Text("EMG contains eight channels of unsigned ADC counts at 2,048 samples per second per channel. Gyro values are raw counts; their physical scale is estimated. Gestures are the band’s decoded messages, including press/release and synthetic flags, before control filtering.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
                .fixedSize(horizontal: false, vertical: true)
            OpenRow(title: "use it in your project", detail: "HTTP · Server-Sent Events · JSON") { EmptyView() }
            Text("Python: open the copied URL with urllib.request.urlopen and parse each line beginning with data:. In a local browser project, use new EventSource(url) and addEventListener(\"emg\", handler), or listen for gyro, orientation, and gesture.")
                .font(KinesisType.caption).foregroundStyle(KinesisStyle.secondary)
                .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            Text("The feed sends original sensor batches without waiting for graphs or recording files. Each reader gets current configuration followed by new data. A slow reader is disconnected rather than building up delayed input.")
                .font(KinesisType.micro).foregroundStyle(KinesisStyle.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var emgState: String {
        if !stream.enabled { return model.rawEMGActive && model.live ? "live" : "off" }
        if !model.live { return "waiting for band" }
        if model.rawEMGChanging { return "starting…" }
        return model.rawEMGActive ? "live" : "unavailable"
    }

    private var feedState: String { !stream.enabled ? "feed off" : model.live ? "live" : "waiting" }

    private func copyURL() {
        guard let url = stream.server.endpointURL else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(url.absoluteString, forType: .string)
    }
}
