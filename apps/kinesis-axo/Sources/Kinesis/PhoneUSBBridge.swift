import Combine
import Darwin
import Foundation
import KinesisCore
import OSLog

@MainActor
protocol PhoneUSBTransport: AnyObject {
    var ports: [String] { get }
    var selectedPort: String { get set }
    var connected: Bool { get }
    var ready: Bool { get }
    var armed: Bool { get }
    var busy: Bool { get }
    var statusText: String { get }
    var onBoundary: (() -> Void)? { get set }
    func refreshPorts()
    func connect()
    func disconnect()
    func arm()
    func disarm()
    @discardableResult func send(action: PhoneNavigationAction) -> Bool
}

/// Small injectable I/O boundary. Tests never open a serial device.
@MainActor
protocol PhoneUSBSerialPort: AnyObject {
    func readAvailable() throws -> Data
    func write(_ data: Data) throws -> Int
    func close()
}

private struct PhoneUSBIOError: Error {}

@MainActor
private final class POSIXPhoneUSBSerialPort: PhoneUSBSerialPort {
    private var descriptor: Int32

    init(path: String) throws {
        descriptor = Darwin.open(path, O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW)
        guard descriptor >= 0 else { throw PhoneUSBIOError() }
        var attributes = termios()
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0, metadata.st_mode & S_IFMT == S_IFCHR,
              ioctl(descriptor, TIOCEXCL) == 0, tcgetattr(descriptor, &attributes) == 0 else {
            Darwin.close(descriptor)
            descriptor = -1
            throw PhoneUSBIOError()
        }
        cfmakeraw(&attributes)
        attributes.c_cflag &= ~tcflag_t(PARENB | CSTOPB | CSIZE | CCTS_OFLOW | CRTS_IFLOW | HUPCL)
        attributes.c_cflag |= tcflag_t(CS8 | CLOCAL | CREAD)
        withUnsafeMutableBytes(of: &attributes.c_cc) { values in
            values[Int(VMIN)] = 1
            values[Int(VTIME)] = 0
        }
        guard cfsetspeed(&attributes, speed_t(B115200)) == 0,
              tcsetattr(descriptor, TCSANOW, &attributes) == 0 else {
            Darwin.close(descriptor)
            descriptor = -1
            throw PhoneUSBIOError()
        }
        // No modem-control ioctl: opening the console must not pulse reset or
        // replace Bluetooth enrollment. HUPCL is clear to avoid a close-time pulse.
    }

    deinit { if descriptor >= 0 { Darwin.close(descriptor) } }

    func readAvailable() throws -> Data {
        var bytes = [UInt8](repeating: 0, count: 2048)
        let amount = Darwin.read(descriptor, &bytes, bytes.count)
        if amount > 0 { return Data(bytes.prefix(amount)) }
        if amount < 0, errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR { return Data() }
        throw PhoneUSBIOError()
    }

    func write(_ data: Data) throws -> Int {
        let amount = data.withUnsafeBytes { buffer in
            Darwin.write(descriptor, buffer.baseAddress, buffer.count)
        }
        if amount >= 0 { return amount }
        if errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR { return 0 }
        throw PhoneUSBIOError()
    }

    func close() {
        guard descriptor >= 0 else { return }
        _ = ioctl(descriptor, TIOCNXCL)
        Darwin.close(descriptor)
        descriptor = -1
    }
}

/// USB UART commands and acknowledgements. No input is queued across connection
/// boundaries, automatically rearmed, or retried after an uncertain write.
@MainActor
final class PhoneUSBBridge: ObservableObject, PhoneUSBTransport {
    @Published private(set) var ports: [String] = []
    @Published var selectedPort = "" {
        didSet { if selectedPort != oldValue, connected { disconnect() } }
    }
    @Published private(set) var connected = false
    @Published private(set) var ready = false
    @Published private(set) var armed = false
    @Published private(set) var busy = false
    @Published private(set) var statusText = "Connect the adapter by USB."
    var onBoundary: (() -> Void)?

    private struct Pending {
        let command: PhoneBridgeCommand
        let deadline: Double
    }
    private let enumeratePorts: () -> [String]
    private let openPort: (String) throws -> any PhoneUSBSerialPort
    private let clock: () -> Double
    private let automaticallyTicks: Bool
    private var serial: (any PhoneUSBSerialPort)?
    private var timer: Timer?
    private var parser = PhoneUSBStatusParser()
    private var sequencer = PhoneBridgeSequencer()
    private var outgoing = Data()
    private var pending: Pending?
    private var handshakeDeadline = 0.0
    private var lastStatusAt = 0.0
    private var nextHelloAt = 0.0
    private var nextHeartbeatAt = 0.0
    private var quietUntil = 0.0
    private var wantsDisarm = false
    private let phoneScrollLog = Logger(subsystem: "local.callbacked.kinesis", category: "phone-scroll")
    private var acceptedWheelPackets = 0
    private var acceptedWheelUnits = 0

    convenience init() {
        self.init(enumeratePorts: Self.availablePorts, openPort: { try POSIXPhoneUSBSerialPort(path: $0) })
    }

    init(enumeratePorts: @escaping () -> [String],
         openPort: @escaping (String) throws -> any PhoneUSBSerialPort,
         clock: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime },
         automaticallyTicks: Bool = true) {
        self.enumeratePorts = enumeratePorts
        self.openPort = openPort
        self.clock = clock
        self.automaticallyTicks = automaticallyTicks
        refreshPorts()
    }

    static func availablePorts() -> [String] {
        ((try? FileManager.default.contentsOfDirectory(atPath: "/dev")) ?? [])
            .filter { $0.hasPrefix("cu.usb") }
            .map { "/dev/" + $0 }.sorted()
    }

    func refreshPorts() {
        ports = enumeratePorts().filter(Self.allowedPort).sorted()
        if selectedPort.isEmpty, ports.count == 1 { selectedPort = ports[0] }
    }

    private static func allowedPort(_ path: String) -> Bool {
        path.hasPrefix("/dev/cu.usb") && !path.dropFirst(5).contains("/")
            && path.utf8.count < 256
    }

    func connect() {
        guard !connected else { return }
        refreshPorts()
        guard Self.allowedPort(selectedPort), ports.contains(selectedPort) else {
            statusText = "Choose the connected USB adapter port."
            return
        }
        do { serial = try openPort(selectedPort) }
        catch { statusText = "Close Serial Monitor, then reconnect the USB adapter."; return }
        parser.reset()
        sequencer.reset()
        outgoing.removeAll(keepingCapacity: true)
        pending = nil
        wantsDisarm = false
        acceptedWheelPackets = 0
        acceptedWheelUnits = 0
        quietUntil = 0
        let now = clock()
        handshakeDeadline = now + 5
        lastStatusAt = now
        nextHelloAt = now
        nextHeartbeatAt = now
        connected = true
        ready = false
        armed = false
        busy = false
        statusText = "Checking USB adapter firmware…"
        if automaticallyTicks {
            let timer = Timer(timeInterval: 0.01, repeats: true) { [weak self] timer in
                guard let self else { timer.invalidate(); return }
                MainActor.assumeIsolated { self.tick() }
            }
            self.timer = timer
            RunLoop.main.add(timer, forMode: .common)
        }
        tick()
    }

    func disconnect() { close(message: "USB adapter disconnected.") }

    func arm() {
        guard connected, ready else { return }
        guard pending == nil, outgoing.isEmpty, clock() >= quietUntil else { return }
        wantsDisarm = false
        if prepare(.arm) { statusText = "Enabling iPhone controls…" }
    }

    func disarm() {
        wantsDisarm = true
        armed = false
        onBoundary?()
        statusText = connected ? "iPhone controls paused." : "USB adapter disconnected."
        tick()
    }

    @discardableResult
    func send(action: PhoneNavigationAction) -> Bool {
        guard connected, ready, armed, !wantsDisarm, pending == nil,
              outgoing.isEmpty, clock() >= quietUntil else { return false }
        return prepare(.action(action))
    }

    @discardableResult
    private func prepare(_ operation: PhoneBridgeOperation) -> Bool {
        guard pending == nil, outgoing.isEmpty else { return false }
        do {
            let command = try sequencer.next(operation)
            outgoing = PhoneUSBWire.command(command)
            pending = Pending(command: command, deadline: clock() + 0.5)
            busy = true
            nextHeartbeatAt = clock() + 0.4
            return true
        } catch {
            close(message: "Reconnect the adapter before enabling iPhone controls again.")
            return false
        }
    }

    /// Internal for a deterministic fake-port fixture. It performs bounded,
    /// nonblocking work; a blocked USB writer never freezes band rendering.
    func tick() {
        guard connected, let serial else { return }
        let now = clock()
        do {
            let bytes = try serial.readAvailable()
            for status in parser.append(bytes) { receive(status, at: now) }
            guard connected else { return }
            if sequencer.status == nil, now >= handshakeDeadline {
                close(message: "Update the adapter firmware for click support, then reconnect.")
                return
            }
            if sequencer.status != nil, now - lastStatusAt >= 1 {
                close(message: "The USB adapter stopped answering. Reconnect to resume.")
                return
            }
            if let pending, now >= pending.deadline {
                close(message: "The adapter did not confirm the command. Reconnect to resume.")
                return
            }
            if outgoing.isEmpty, pending == nil {
                if wantsDisarm, sequencer.status != nil {
                    _ = prepare(.disarm)
                } else if armed, now >= nextHeartbeatAt {
                    _ = prepare(.heartbeat)
                } else if now >= nextHelloAt {
                    outgoing = PhoneUSBWire.hello
                    nextHelloAt = now + 0.25
                }
            }
            if !outgoing.isEmpty {
                let amount = try serial.write(outgoing)
                guard amount >= 0, amount <= outgoing.count else { throw PhoneUSBIOError() }
                outgoing.removeFirst(amount)
            }
            busy = pending != nil || !outgoing.isEmpty || now < quietUntil || wantsDisarm
        } catch {
            close(message: "USB connection lost. Reconnect the adapter to resume.")
        }
    }

    private func receive(_ status: PhoneBridgeStatus, at now: Double) {
        let previous = sequencer.status
        // Ignore delayed status within a session rather than allowing an old
        // frame to cancel a newer command or restore output readiness.
        if let previous, previous.session == status.session,
           status.lastAcceptedSequence < previous.lastAcceptedSequence { return }
        let wasArmed = armed
        let changedSession = sequencer.update(status: status)
        lastStatusAt = now
        ready = status.outputReady
        if changedSession {
            pending = nil
            let interruptedLine = !outgoing.isEmpty
            outgoing.removeAll(keepingCapacity: true)
            if interruptedLine { outgoing = Data([10]) }
            quietUntil = 0
            wantsDisarm = false
            armed = false
            onBoundary?()
        } else if let pending, status.lastAcceptedSequence >= pending.command.sequence {
            self.pending = nil
            switch pending.command.operation {
            case .action(.key), .action(.click): quietUntil = now + 0.1
            case .action(.move): quietUntil = now
            // The adapter accepts its next queued command only after the prior
            // HID transfer has completed. One pending ACK bounds the host queue;
            // an extra host delay visibly reduces the scroll update cadence.
            case .action(.scroll(let scroll)):
                quietUntil = now
                acceptedWheelPackets += 1
                acceptedWheelUnits += abs(Int(scroll.vertical))
                phoneScrollLog.info("Adapter accepted phone wheel packets \(self.acceptedWheelPackets, privacy: .public), units \(self.acceptedWheelUnits, privacy: .public)")
            case .disarm: wantsDisarm = false
            default: break
            }
        }
        armed = !wantsDisarm && sequencer.isArmed
        if wasArmed, !armed, !changedSession { onBoundary?() }
        if !ready {
            statusText = "Pair the iPhone and enable its keyboard and mouse access."
        } else if armed {
            statusText = "iPhone controls enabled."
        } else if pending?.command.operation == .arm {
            statusText = "Enabling iPhone controls…"
        } else {
            statusText = "iPhone connected. Enable controls when ready."
        }
    }

    private func close(message: String) {
        // A final disarm is best effort. Never retry the previous action, and
        // never append to a partially written command. The adapter's independent
        // watchdog also disarms if the cable disappears before this can arrive.
        if connected, outgoing.isEmpty, let serial,
           let command = try? sequencer.next(.disarm) {
            _ = try? serial.write(PhoneUSBWire.command(command))
        }
        timer?.invalidate()
        timer = nil
        serial?.close()
        serial = nil
        parser.reset()
        sequencer.reset()
        pending = nil
        outgoing.removeAll(keepingCapacity: true)
        wantsDisarm = false
        connected = false
        ready = false
        armed = false
        busy = false
        statusText = message
        onBoundary?()
    }
}
