import Foundation
import Testing
@testable import KinesisCore

@Suite("Sensor stream event schema")
struct SensorStreamEventTests {
    private let status = SensorStreamStatus(connected: true, emgRequested: true, emgActive: false,
                                            hand: .right, gyroRequested: true, orientationRequested: true,
                                            bandConnectionID: "connection-fixture", modelCaptureActive: true)

    private func event(_ payload: SensorStreamEvent.Payload, receivedAt: Double = 123.5) -> SensorStreamEvent {
        SensorStreamEvent(sessionID: "session-fixture", sequence: 42, receivedAt: receivedAt, payload: payload)
    }

    private func object(_ event: SensorStreamEvent) throws -> [String: Any] {
        try #require(JSONSerialization.jsonObject(with: event.jsonData()) as? [String: Any])
    }

    private func configuration() throws -> EMGConfiguration {
        let emg = BandWire.field(1, 2048) + BandWire.field(2, 8) + BandWire.field(4, 16)
            + BandWire.field(5, 16) + BandWire.field(10, 0)
        return try EMGConfiguration(response: BandWire.field(2, 1) + BandWire.field(6, BandWire.field(42, emg)))
    }

    @Test func metadataSeparatesReceiptAndBandClocksWithoutIdentity() throws {
        let json = try object(event(.hello(status)))
        #expect(json["schema_version"] as? Int == 1)
        #expect(json["type"] as? String == "hello")
        #expect(json["stream_session_id"] as? String == "session-fixture")
        #expect(json["event_sequence"] as? Int == 42)
        #expect(json["host_time_s"] as? Double == 123.5)
        #expect(json["band_timestamp_us"] == nil)
        let payload = try #require(json["payload"] as? [String: Any])
        #expect(payload["protocol"] as? String == "kinesis.sensor-stream")
        #expect((payload["band_clock"] as? String)?.contains("not synchronized") == true)
        let state = try #require(payload["status"] as? [String: Any])
        #expect(state["emg_requested"] as? Bool == true)
        #expect(state["emg_active"] as? Bool == false)
        #expect(state["hand"] as? String == "right")
        #expect(state["band_connection_id"] as? String == "connection-fixture")
        #expect(state["model_capture_active"] as? Bool == true)
        #expect(state["address"] == nil && state["account"] == nil && state["key"] == nil)
        let offline = SensorStreamStatus(connected: false, emgRequested: false, emgActive: false,
                                         hand: nil, gyroRequested: false, orientationRequested: false)
        let offlineJSON = try object(event(.status(offline)))
        let offlineState = try #require(offlineJSON["payload"] as? [String: Any])
        #expect(offlineState["hand"] is NSNull)
        #expect(offlineState["band_connection_id"] is NSNull)
    }

    @Test func configurationStatesADCUnitsAndUnsupportedCalibration() throws {
        let json = try object(event(.emgConfiguration(configuration())))
        #expect(json["type"] as? String == "emg_configuration")
        let payload = try #require(json["payload"] as? [String: Any])
        #expect(payload["sample_rate_hz"] as? Int == 2048)
        #expect(payload["channels"] as? Int == 8)
        #expect(payload["adc_bits"] as? Int == 16)
        #expect(payload["samples_per_batch"] as? Int == 16)
        #expect(payload["encoding"] as? Int == 0)
        #expect(payload["supported"] as? Bool == true)
        #expect(payload["units"] as? String == "unsigned_adc_counts")
        #expect((payload["calibration"] as? String)?.contains("unknown") == true)
    }

    @Test func EMGBatchPreservesEveryUnsignedSampleInSampleMajorOrder() throws {
        var bytes = Data()
        let expected = (0..<128).map { UInt16($0 * 500) }
        for value in expected { bytes.append(UInt8(value & 255)); bytes.append(UInt8(value >> 8)) }
        let batch = try EMGBatch(payload: BandWire.field(1, 77) + BandWire.field(2, 1_000_000)
                                + BandWire.field(3, bytes), configuration: configuration())
        let json = try object(event(.emg(batch)))
        #expect(json["band_timestamp_us"] as? Int == 1_000_000)
        let payload = try #require(json["payload"] as? [String: Any])
        #expect(payload["sequence"] as? Int == 77)
        #expect(payload["sample_interval_us"] as? Double == 488.28125)
        #expect(payload["layout"] as? String == "sample_major")
        let values = try #require(payload["values"] as? [[Int]])
        #expect(values.count == 16 && values.allSatisfy { $0.count == 8 })
        #expect(values.flatMap { $0 } == expected.map(Int.init))
        #expect(values.last?.last == 63_500)
    }

    @Test func motionPreservesRawCountsAndWireQuaternionOrder() throws {
        let gyroJSON = try object(event(.gyro(timestamp: 5678, values: SIMD3(-10, 2.5, 100))))
        #expect(gyroJSON["band_timestamp_us"] as? Int == 5678)
        let gyro = try #require(gyroJSON["payload"] as? [String: Any])
        #expect(gyro["values"] as? [Double] == [-10, 2.5, 100])
        #expect(gyro["axes"] as? [String] == ["x", "y", "z"])
        #expect(gyro["units"] as? String == "raw_counts")
        #expect(gyro["observed_degrees_per_second_per_count"] as? Double == 0.07)
        #expect((gyro["calibration"] as? String)?.contains("not calibrated") == true)
        let orientationJSON = try object(event(.orientation(timestamp: 5680, values: SIMD4(0.9, 0.1, 0.2, 0.3))))
        let orientation = try #require(orientationJSON["payload"] as? [String: Any])
        #expect(orientation["values"] as? [Double] == [0.9, 0.1, 0.2, 0.3])
        #expect(orientation["components"] as? [String] == ["w", "x", "y", "z"])
    }

    @Test func gesturesPreserveClassificationAndSyntheticFlagBeforeRouting() throws {
        let message = BandGesture(sequence: 234, timestampUs: 9_876, finger: "middle", action: "doubletap",
                                  derivedAction: "doubleTap", synthetic: true, receivedAt: 123.25)
        let json = try object(event(.gesture(message)))
        #expect(json["type"] as? String == "gesture")
        #expect(json["band_timestamp_us"] as? Int == 9876)
        let payload = try #require(json["payload"] as? [String: Any])
        #expect(payload["sequence"] as? Int == 234)
        #expect(payload["timestamp_us"] as? Int == 9876)
        #expect(payload["finger"] as? String == "middle")
        #expect(payload["action"] as? String == "doubletap")
        #expect(payload["derived_action"] as? String == "doubleTap")
        #expect(payload["synthetic"] as? Bool == true)
        #expect(payload["received_at_s"] as? Double == 123.25)
        #expect(payload["label"] is NSNull)
    }

    @Test func SSEFramingEscapesPayloadNewlinesAndRejectsInvalidNumbers() throws {
        let message = BandGesture(sequence: 1, timestampUs: 2, finger: "index\nevent: injected", action: "tap")
        let encoded = try #require(String(data: event(.gesture(message)).sseData(), encoding: .utf8))
        #expect(encoded.hasPrefix("id: 42\nevent: gesture\ndata: {"))
        #expect(encoded.hasSuffix("\n\n"))
        #expect(encoded.split(separator: "\n").count == 3)
        #expect(throws: EncodingError.self) { try event(.status(status), receivedAt: .nan).jsonData() }
        #expect(throws: EncodingError.self) { try event(.gyro(timestamp: 1, values: SIMD3(.infinity, 0, 0))).jsonData() }
    }
}
