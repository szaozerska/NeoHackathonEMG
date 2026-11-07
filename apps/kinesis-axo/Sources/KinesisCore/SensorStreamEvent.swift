import Foundation

/// Current input subscriptions. A requested stream may still be waiting for the band.
/// This deliberately excludes pairing identity, account information, and control mappings.
public struct SensorStreamStatus: Sendable, Encodable, Equatable {
    public let connected: Bool
    public let emgRequested: Bool
    public let emgActive: Bool
    public let hand: BandHand?
    public let gyroRequested: Bool
    public let orientationRequested: Bool
    public let bandConnectionID: String?
    public let modelCaptureActive: Bool
    public let emgChanging: Bool

    public init(connected: Bool, emgRequested: Bool, emgActive: Bool, hand: BandHand?,
                gyroRequested: Bool, orientationRequested: Bool, bandConnectionID: String? = nil,
                modelCaptureActive: Bool = false, emgChanging: Bool = false) {
        self.connected = connected
        self.emgRequested = emgRequested
        self.emgActive = emgActive
        self.hand = hand
        self.gyroRequested = gyroRequested
        self.orientationRequested = orientationRequested
        self.bandConnectionID = bandConnectionID
        self.modelCaptureActive = modelCaptureActive
        self.emgChanging = emgChanging
    }

    private enum CodingKeys: String, CodingKey {
        case connected, hand
        case emgRequested = "emg_requested", emgActive = "emg_active"
        case gyroRequested = "gyro_requested", orientationRequested = "orientation_requested"
        case bandConnectionID = "band_connection_id", modelCaptureActive = "model_capture_active"
        case emgChanging = "emg_changing"
    }

    public func encode(to encoder: any Encoder) throws {
        var fields = encoder.container(keyedBy: CodingKeys.self)
        try fields.encode(connected, forKey: .connected)
        try fields.encode(emgRequested, forKey: .emgRequested)
        try fields.encode(emgActive, forKey: .emgActive)
        try fields.encode(hand?.rawValue, forKey: .hand)
        try fields.encode(gyroRequested, forKey: .gyroRequested)
        try fields.encode(orientationRequested, forKey: .orientationRequested)
        try fields.encode(bandConnectionID, forKey: .bandConnectionID)
        try fields.encode(modelCaptureActive, forKey: .modelCaptureActive)
        try fields.encode(emgChanging, forKey: .emgChanging)
    }
}

/// Versioned sensor-only event shared by the local API and its consumers.
/// Host time is receipt time on the Mac's monotonic uptime clock; it is not band time.
public struct SensorStreamEvent: Sendable, Encodable {
    public static let schemaVersion = 1

    public enum Payload: Sendable {
        case hello(SensorStreamStatus)
        case status(SensorStreamStatus)
        case emgConfiguration(EMGConfiguration)
        case emg(EMGBatch)
        case gyro(timestamp: UInt64, values: SIMD3<Double>)
        case orientation(timestamp: UInt64, values: SIMD4<Double>)
        /// Decoded band classification, before the app's control-action routing.
        case gesture(BandGesture)
    }

    public let sessionID: String
    public let sequence: UInt64
    public let receivedAt: Double
    public let payload: Payload

    public init(sessionID: String, sequence: UInt64, receivedAt: Double, payload: Payload) {
        self.sessionID = sessionID
        self.sequence = sequence
        self.receivedAt = receivedAt
        self.payload = payload
    }

    public var type: String {
        switch payload {
        case .hello: "hello"
        case .status: "status"
        case .emgConfiguration: "emg_configuration"
        case .emg: "emg"
        case .gyro: "gyro"
        case .orientation: "orientation"
        case .gesture: "gesture"
        }
    }

    public var bandTimestampUs: UInt64? {
        switch payload {
        case .hello, .status, .emgConfiguration: nil
        case .emg(let batch): batch.timestampUs
        case .gyro(let timestamp, _), .orientation(let timestamp, _): timestamp
        case .gesture(let gesture): gesture.timestampUs
        }
    }

    public func jsonData() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        // The default rejection of nonfinite numbers prevents invalid JSON on the wire.
        return try encoder.encode(self)
    }

    public func sseData() throws -> Data {
        var result = Data("id: \(sequence)\nevent: \(type)\ndata: ".utf8)
        result.append(try jsonData())
        result.append(Data("\n\n".utf8))
        return result
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version", type, sessionID = "stream_session_id"
        case sequence = "event_sequence", receivedAt = "host_time_s"
        case bandTimestampUs = "band_timestamp_us", payload
    }

    public func encode(to encoder: any Encoder) throws {
        var fields = encoder.container(keyedBy: CodingKeys.self)
        try fields.encode(Self.schemaVersion, forKey: .schemaVersion)
        try fields.encode(type, forKey: .type)
        try fields.encode(sessionID, forKey: .sessionID)
        try fields.encode(sequence, forKey: .sequence)
        try fields.encode(receivedAt, forKey: .receivedAt)
        try fields.encodeIfPresent(bandTimestampUs, forKey: .bandTimestampUs)
        try encodePayload(to: fields.superEncoder(forKey: .payload))
    }

    private struct Field: CodingKey {
        let stringValue: String
        let intValue: Int? = nil
        init(_ value: String) { stringValue = value }
        init?(stringValue: String) { self.init(stringValue) }
        init?(intValue: Int) { return nil }
    }

    private func encodePayload(to encoder: any Encoder) throws {
        switch payload {
        case .status(let status): try status.encode(to: encoder)
        case .hello(let status):
            var fields = encoder.container(keyedBy: Field.self)
            try fields.encode("kinesis.sensor-stream", forKey: Field("protocol"))
            try fields.encode("server-sent-events", forKey: Field("transport"))
            try fields.encode("seconds since Mac boot (monotonic receipt time)", forKey: Field("host_clock"))
            try fields.encode("microseconds on the band clock; not synchronized to host time", forKey: Field("band_clock"))
            try fields.encode("event_sequence is global within stream_session_id, including other readers' bootstrap metadata; gaps alone do not prove sample loss; use EMG sequence for batch gaps; no history is replayed",
                              forKey: Field("delivery"))
            try fields.encode(status, forKey: Field("status"))
        case .emgConfiguration(let configuration):
            var fields = encoder.container(keyedBy: Field.self)
            try fields.encode(configuration.sampleRate, forKey: Field("sample_rate_hz"))
            try fields.encode(configuration.channels, forKey: Field("channels"))
            try fields.encode(configuration.adcBits, forKey: Field("adc_bits"))
            try fields.encode(configuration.samplesPerBatch, forKey: Field("samples_per_batch"))
            try fields.encode(configuration.encoding, forKey: Field("encoding"))
            try fields.encode(configuration.isSupported, forKey: Field("supported"))
            try fields.encode("unsigned_adc_counts", forKey: Field("units"))
            try fields.encode("unknown; no voltage conversion applied", forKey: Field("calibration"))
        case .emg(let batch):
            var fields = encoder.container(keyedBy: Field.self)
            try fields.encode(batch.sequence, forKey: Field("sequence"))
            try fields.encode(2048, forKey: Field("sample_rate_hz"))
            try fields.encode(EMGBatch.sampleIntervalUs, forKey: Field("sample_interval_us"))
            try fields.encode(EMGBatch.channelCount, forKey: Field("channels"))
            try fields.encode(EMGBatch.sampleCount, forKey: Field("samples_per_batch"))
            try fields.encode("sample_major", forKey: Field("layout"))
            try fields.encode("unsigned_adc_counts", forKey: Field("units"))
            let rows = stride(from: 0, to: batch.values.count, by: EMGBatch.channelCount).map {
                Array(batch.values[$0..<min($0 + EMGBatch.channelCount, batch.values.count)])
            }
            try fields.encode(rows, forKey: Field("values"))
        case .gyro(_, let values):
            var fields = encoder.container(keyedBy: Field.self)
            try fields.encode([values.x, values.y, values.z], forKey: Field("values"))
            try fields.encode(["x", "y", "z"], forKey: Field("axes"))
            try fields.encode("raw_counts", forKey: Field("units"))
            try fields.encode(0.07, forKey: Field("observed_degrees_per_second_per_count"))
            try fields.encode("observed estimate; not calibrated", forKey: Field("calibration"))
        case .orientation(_, let values):
            var fields = encoder.container(keyedBy: Field.self)
            // SIMD component names are positional here: the wire's first component is w.
            try fields.encode([values.x, values.y, values.z, values.w], forKey: Field("values"))
            try fields.encode(["w", "x", "y", "z"], forKey: Field("components"))
            try fields.encode("quaternion", forKey: Field("units"))
        case .gesture(let gesture):
            var fields = encoder.container(keyedBy: Field.self)
            try fields.encode(gesture.sequence, forKey: Field("sequence"))
            try fields.encode(gesture.finger, forKey: Field("finger"))
            try fields.encode(gesture.action, forKey: Field("action"))
            try fields.encode(gesture.derivedAction, forKey: Field("derived_action"))
            try fields.encode(gesture.synthetic, forKey: Field("synthetic"))
            try fields.encode(gesture.receivedAt, forKey: Field("received_at_s"))
            try fields.encode(gesture.timestampUs, forKey: Field("timestamp_us"))
            try fields.encode(gesture.gestureLabel, forKey: Field("label"))
        }
    }
}
