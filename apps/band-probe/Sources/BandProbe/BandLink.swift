import CoreBluetooth
import Foundation
import KinesisCore

struct ProbeError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// A stripped-down copy of Kinesis's NativeBandConnection: one band, gestures only,
/// plus raw RPC sends. Holds Kinesis's band lock so the two never share the band.
@MainActor
final class BandLink: NSObject, @preconcurrency CBCentralManagerDelegate, @preconcurrency CBPeripheralDelegate,
    @preconcurrency StreamDelegate {
    private let address: UUID
    private let onEvent: (BandEvent) -> Void
    private let onEnd: (Error?) -> Void
    private var central: CBCentralManager?
    private var peripheral: CBPeripheral?
    private var channel: CBL2CAPChannel?
    private var session: BandSession?
    private var outgoing = Data()
    private var stopping = false
    private var pendingFailure: Error?
    private var finished = false
    private var lease: Int32 = -1
    private let serviceID = CBUUID(string: "FEB8")
    private let psmID = CBUUID(string: "2D41DA7C-82B6-42AA-B34E-E2E01DF8CC1A")
    private var now: Double { ProcessInfo.processInfo.systemUptime }

    var ready: Bool { session?.streamsEnabled == true }

    init(address: UUID, onEvent: @escaping (BandEvent) -> Void, onEnd: @escaping (Error?) -> Void) {
        self.address = address
        self.onEvent = onEvent
        self.onEnd = onEnd
    }

    func start() throws {
        let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Kinesis", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let descriptor = open(directory.appendingPathComponent("band.lock").path, O_CREAT | O_RDWR | O_CLOEXEC, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw ProbeError(message: "Could not open the band lock") }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            close(descriptor)
            throw ProbeError(message: "Kinesis is connected to the band. Quit it first.")
        }
        lease = descriptor
        central = CBCentralManager(delegate: self, queue: .main)
    }

    func sendRPC(field: Int, payload: Data) throws -> UInt64 {
        guard let session else { throw ProbeError(message: "Not connected yet") }
        let request = try session.sendRPC(field: field, payload: payload)
        outgoing.append(request.bytes)
        try flushOutput()
        return request.id
    }

    /// Kinesis polls the subscription when sensors go quiet; with motion off, gestures alone are quiet.
    func keepAlive() throws {
        guard let session, session.streamsEnabled, !stopping else { return }
        outgoing.append(try session.queryStreamState())
        try flushOutput()
    }

    func stop() throws {
        guard !stopping else { return }
        stopping = true
        guard let session, channel != nil else { disconnect(); return }
        outgoing.append(try session.stop())
        try flushOutput()
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            MainActor.assumeIsolated { self.disconnect() }
        }
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central.state == .poweredOn else {
            if central.state == .unauthorized { finish(ProbeError(message: "Allow Bluetooth for your terminal app in System Settings")) }
            if central.state == .poweredOff { finish(ProbeError(message: "Bluetooth is off")) }
            return
        }
        guard peripheral == nil else { return }
        if let known = central.retrievePeripherals(withIdentifiers: [address]).first {
            connect(known)
            return
        }
        print("scanning for \(address.uuidString)…")
        central.scanForPeripherals(withServices: nil)
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard self.peripheral == nil, peripheral.identifier == address else { return }
        connect(peripheral)
    }

    private func connect(_ peripheral: CBPeripheral) {
        self.peripheral = peripheral
        central?.stopScan()
        central?.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        print("bluetooth connected, opening input channel…")
        peripheral.delegate = self
        peripheral.discoverServices([serviceID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        finish(error ?? ProbeError(message: "Could not connect to the band"))
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        finish(stopping ? nil : error ?? ProbeError(message: "The band disconnected"))
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let service = peripheral.services?.first(where: { $0.uuid == serviceID }) else {
            fail(error ?? ProbeError(message: "This device doesn't expose the band input service")); return
        }
        peripheral.discoverCharacteristics([psmID], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard let characteristic = service.characteristics?.first(where: { $0.uuid == psmID }) else {
            fail(error ?? ProbeError(message: "Band input channel is unavailable")); return
        }
        peripheral.readValue(for: characteristic)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error { fail(error); return }
        guard let psm = Self.inputPSM(from: characteristic.value) else {
            fail(ProbeError(message: "Unsupported band input channel")); return
        }
        peripheral.openL2CAPChannel(psm)
    }

    /// Same rule as Kinesis: a little-endian LE dynamic PSM in 0x80...0xff.
    private static func inputPSM(from bytes: Data?) -> CBL2CAPPSM? {
        guard let bytes, bytes.count == 2 else { return nil }
        let psm = UInt16(bytes[bytes.startIndex]) | UInt16(bytes[bytes.startIndex + 1]) << 8
        return (0x0080...0x00ff).contains(psm) ? psm : nil
    }

    func peripheral(_ peripheral: CBPeripheral, didOpen channel: CBL2CAPChannel?, error: Error?) {
        if let error { fail(error); return }
        guard let channel else { fail(ProbeError(message: "Could not open the band input stream")); return }
        do {
            let enrollment = BandIdentity.enrollment(for: address.uuidString)
            print(enrollment == nil ? "no stored Kinesis identity; trying legacy startup" : "authenticating with Kinesis's stored identity")
            let session = try BandSession(enrollment: enrollment, motion: .none)
            self.session = session
            self.channel = channel
            outgoing = try session.request()
            for stream in [channel.inputStream as Stream, channel.outputStream as Stream] {
                stream.delegate = self
                stream.schedule(in: .main, forMode: .common)
                stream.open()
            }
            try flushOutput()
        } catch { fail(error) }
    }

    func stream(_ stream: Stream, handle eventCode: Stream.Event) {
        do {
            if eventCode.contains(.errorOccurred) { throw stream.streamError ?? ProbeError(message: "The band stream failed") }
            if eventCode.contains(.endEncountered) {
                if stopping { disconnect(); return }
                throw ProbeError(message: "The band stream ended")
            }
            if eventCode.contains(.hasBytesAvailable) { try readInput() }
            if eventCode.contains(.hasSpaceAvailable) { try flushOutput() }
        } catch { fail(error) }
    }

    private func readInput() throws {
        guard let input = channel?.inputStream, let session else { return }
        var buffer = [UInt8](repeating: 0, count: 65_536)
        let count = input.read(&buffer, maxLength: buffer.count)
        guard count >= 0 else { throw input.streamError ?? ProbeError(message: "Could not read from the band") }
        guard count > 0 else { return }
        let result = try session.feed(Data(buffer.prefix(count)), at: now)
        outgoing.append(result.outgoing)
        for event in result.events { onEvent(event) }
        try flushOutput()
        if stopping, session.stopAcknowledged { disconnect() }
    }

    private func flushOutput() throws {
        guard let output = channel?.outputStream else { return }
        while !outgoing.isEmpty, output.hasSpaceAvailable {
            let count = outgoing.withUnsafeBytes { output.write($0.bindMemory(to: UInt8.self).baseAddress!, maxLength: outgoing.count) }
            guard count >= 0 else { throw output.streamError ?? ProbeError(message: "Could not write to the band") }
            guard count > 0 else { return }
            outgoing = Data(outgoing.dropFirst(count))
        }
    }

    private func fail(_ error: Error) {
        stopping = true
        disconnect(failure: error)
    }

    private func disconnect(failure: Error? = nil) {
        if let channel {
            for stream in [channel.inputStream as Stream, channel.outputStream as Stream] {
                stream.delegate = nil
                stream.close()
            }
        }
        channel = nil
        guard let peripheral, peripheral.state != .disconnected else { finish(failure); return }
        pendingFailure = failure
        central?.cancelPeripheralConnection(peripheral)
    }

    private func finish(_ error: Error?) {
        guard !finished else { return }
        finished = true
        if lease >= 0 { flock(lease, LOCK_UN); close(lease); lease = -1 }
        onEnd(pendingFailure ?? error)
    }
}
