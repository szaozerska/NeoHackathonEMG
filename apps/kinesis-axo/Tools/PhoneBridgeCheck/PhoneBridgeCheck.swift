import CoreBluetooth
import Darwin
import Foundation
import KinesisCore

private enum CheckError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let value) = self { value } else { nil } }
}

private struct Options {
    let action: PhoneNavigationAction?
    let peripheralID: UUID?

    static let help = """
    PhoneBridgeCheck status [--peripheral UUID]
    PhoneBridgeCheck scroll STEPS [--peripheral UUID]
    PhoneBridgeCheck key KEY [--modifiers ctrl+shift+alt+cmd] [--peripheral UUID]

    Checks the Axo Bluetooth input adapter. status sends no keyboard/mouse input.
    scroll and key explicitly arm, send ONE action, disarm, then disconnect.
    This Mac is the Bluetooth input host during this developer check. The adapter
    supports one host at a time; this tool cannot command a separately paired iPhone.
    Keys: tab, space, enter, escape, up, down, left, right, home, end, pageup,
    pagedown, f13, f14. Scroll steps: -127...127, excluding zero.
    Initial Bluetooth pairing uses the code shown locally by the board's setup
    serial console. Enter it only in the macOS pairing dialog, never in this tool.
    """

    static func parse(_ arguments: [String]) throws -> Self? {
        if arguments.isEmpty || arguments == ["--help"] || arguments == ["-h"] {
            print(help)
            return nil
        }
        var remaining = arguments
        let command = remaining.removeFirst()
        var action: PhoneNavigationAction?
        var chordKey: PhoneNavigationKey?
        switch command {
        case "status": break
        case "scroll":
            guard !remaining.isEmpty, let amount = Int(remaining.removeFirst()),
                  let scroll = PhoneScroll(vertical: amount) else {
                throw CheckError.message("Choose a nonzero scroll step between -127 and 127.")
            }
            action = .scroll(scroll)
        case "key":
            let keys: [String: PhoneNavigationKey] = [
                "tab": .tab, "space": .space, "enter": .enter, "escape": .escape,
                "up": .up, "down": .down, "left": .left, "right": .right,
                "home": .home, "end": .end, "pageup": .pageUp, "pagedown": .pageDown,
                "f13": .f13, "f14": .f14,
            ]
            guard !remaining.isEmpty, let key = keys[remaining.removeFirst().lowercased()] else {
                throw CheckError.message("Choose one of the navigation keys listed in --help.")
            }
            chordKey = key
        default: throw CheckError.message("Unknown command. Use --help for the available checks.")
        }
        var peripheralID: UUID?
        var modifiers: PhoneKeyboardModifiers = []
        var sawModifiers = false
        while !remaining.isEmpty {
            let flag = remaining.removeFirst()
            guard !remaining.isEmpty else { throw CheckError.message("Missing value after \(flag).") }
            let value = remaining.removeFirst()
            switch flag {
            case "--peripheral":
                guard peripheralID == nil, let id = UUID(uuidString: value) else {
                    throw CheckError.message("Provide one valid peripheral UUID.")
                }
                peripheralID = id
            case "--modifiers":
                guard chordKey != nil, !sawModifiers else {
                    throw CheckError.message("Use --modifiers once, with a key command.")
                }
                sawModifiers = true
                for name in value.lowercased().split(separator: "+", omittingEmptySubsequences: false) {
                    switch name {
                    case "ctrl": modifiers.insert(.control)
                    case "shift": modifiers.insert(.shift)
                    case "alt": modifiers.insert(.option)
                    case "cmd": modifiers.insert(.command)
                    default: throw CheckError.message("Modifiers can be ctrl, shift, alt, or cmd.")
                    }
                }
            default: throw CheckError.message("Unknown option: \(flag).")
            }
        }
        if let key = chordKey { action = .key(PhoneKeyboardChord(key, modifiers: modifiers)) }
        return Self(action: action, peripheralID: peripheralID)
    }
}

@MainActor
private final class BridgeCheck: NSObject, @preconcurrency CBCentralManagerDelegate,
    @preconcurrency CBPeripheralDelegate {
    private enum Phase { case scanning, connecting, starting, arming, action, settling, disarming }
    private let options: Options
    private var central: CBCentralManager?
    private var peripheral: CBPeripheral?
    private var commandCharacteristic: CBCharacteristic?
    private var statusCharacteristic: CBCharacteristic?
    private var sequencer = PhoneBridgeSequencer()
    private var candidates: [UUID: CBPeripheral] = [:]
    private var phase = Phase.scanning
    private var timer: Timer?
    private var scanEndsAt: Double?
    private var deadline = Double.infinity
    private var writeDeadline = Double.infinity
    private var inFlight: PhoneBridgeCommand?
    private var awaitingAcceptance: PhoneBridgeCommand?
    private var acceptedAt: Double?
    private var lastRead = 0.0
    private var requestedStatusNotifications = false
    private var now: Double { ProcessInfo.processInfo.systemUptime }
    private let service = CBUUID(string: PhoneBridgeWire.serviceUUID)
    private let commandID = CBUUID(string: PhoneBridgeWire.commandUUID)
    private let statusID = CBUUID(string: PhoneBridgeWire.statusUUID)
    private(set) var exitStatus: Int32?

    init(options: Options) { self.options = options }

    func start() {
        deadline = now + 90
        let timer = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        self.timer = timer
        RunLoop.main.add(timer, forMode: .common)
        print("Looking for an Axo input adapter. Complete any macOS Bluetooth pairing prompt yourself.")
        central = CBCentralManager(delegate: self, queue: .main)
    }

    private func tick() {
        guard exitStatus == nil else { return }
        if now >= deadline || now >= writeDeadline {
            finish("The adapter did not confirm in time. No action will be retried.", code: 1)
            return
        }
        if phase == .scanning, let scanEndsAt, now >= scanEndsAt {
            central?.stopScan()
            let matches = candidates.values.filter { options.peripheralID == nil || $0.identifier == options.peripheralID }
            guard matches.count == 1, let target = matches.first else {
                finish(matches.isEmpty ? "No matching adapter found. Check power and its setup state."
                    : "More than one adapter found. Choose one with --peripheral UUID.", code: 1)
                return
            }
            phase = .connecting
            peripheral = target
            target.delegate = self
            central?.connect(target)
        }
        if phase == .settling, let acceptedAt, now - acceptedAt >= 0.6 {
            phase = .disarming
            send(.disarm)
        } else if awaitingAcceptance != nil, inFlight == nil, now - lastRead >= 0.25 {
            readStatus()
        }
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard exitStatus == nil else { return }
        switch central.state {
        case .poweredOn:
            guard phase == .scanning, scanEndsAt == nil else { return }
            scanEndsAt = now + 5
            central.scanForPeripherals(withServices: [service])
        case .unauthorized: finish("Allow Bluetooth access before checking the adapter.", code: 1)
        case .unsupported: finish("Bluetooth is unavailable on this Mac.", code: 1)
        case .poweredOff: finish("Turn Bluetooth on before checking the adapter.", code: 1)
        default: break
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard phase == .scanning, exitStatus == nil else { return }
        candidates[peripheral.identifier] = peripheral
        print("Adapter: \(peripheral.name ?? "Axo Phone Bridge")  \(peripheral.identifier.uuidString)")
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard exitStatus == nil, peripheral == self.peripheral else { return }
        phase = .starting
        peripheral.discoverServices([service])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        finish("Could not connect to the adapter.", code: 1)
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard exitStatus == nil else { return }
        sequencer.reset()
        finish("The adapter disconnected. Input is disarmed; no action will be replayed.", code: 1)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard error == nil, let service = peripheral.services?.first(where: { $0.uuid == self.service }) else {
            finish("The adapter does not expose the expected command service.", code: 1)
            return
        }
        peripheral.discoverCharacteristics([commandID, statusID], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        commandCharacteristic = service.characteristics?.first { $0.uuid == commandID }
        statusCharacteristic = service.characteristics?.first { $0.uuid == statusID }
        guard error == nil, let command = commandCharacteristic, let status = statusCharacteristic,
              command.properties.contains(.write), status.properties.contains(.read),
              status.properties.contains(.notify) else {
            finish("The adapter's command characteristics are incomplete.", code: 1)
            return
        }
        readStatus()
    }

    private func readStatus() {
        guard let statusCharacteristic else { return }
        lastRead = now
        peripheral?.readValue(for: statusCharacteristic)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic,
                    error: Error?) {
        if error != nil { finish("Could not subscribe to authenticated adapter status.", code: 1) }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard exitStatus == nil, characteristic.uuid == statusID else { return }
        guard error == nil, let data = characteristic.value, let status = PhoneBridgeStatus(data: data) else {
            finish("Could not read valid authenticated status. Open the board's pairing window if this is first setup.", code: 1)
            return
        }
        if !requestedStatusNotifications {
            requestedStatusNotifications = true
            peripheral.setNotifyValue(true, for: characteristic)
        }
        let changed = sequencer.update(status: status)
        if phase == .starting {
            print("Adapter status: \(status.state == .armed ? "armed" : "disarmed"), input \(status.outputReady ? "ready" : "not ready").")
            guard options.action != nil else { finish("Status check complete; no input sent.", code: 0); return }
            guard status.outputReady else { return }
            phase = .arming
            send(.arm)
        } else if changed {
            finish("The adapter's input session changed. Run a fresh check; no action will be replayed.", code: 1)
        } else if phase == .settling && status.state != .armed {
            finish("The adapter disarmed before the check completed (reason \(status.reason)).", code: 1)
        } else {
            completeAcceptedWrite()
        }
    }

    private func send(_ operation: PhoneBridgeOperation) {
        guard exitStatus == nil, inFlight == nil, awaitingAcceptance == nil,
              let peripheral, let commandCharacteristic else {
            finish("The adapter is not ready for another command.", code: 1)
            return
        }
        do {
            let command = try sequencer.next(operation)
            inFlight = command
            awaitingAcceptance = command
            writeDeadline = now + 5
            peripheral.writeValue(command.data, for: commandCharacteristic, type: .withResponse)
        } catch { finish(error.localizedDescription, code: 1) }
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard exitStatus == nil, characteristic.uuid == commandID, inFlight != nil else { return }
        guard error == nil else {
            finish("The write was not confirmed. Disconnecting rather than retrying input.", code: 1)
            return
        }
        inFlight = nil
        completeAcceptedWrite()
    }

    private func completeAcceptedWrite() {
        guard inFlight == nil, let pending = awaitingAcceptance, let status = sequencer.status,
              status.session == pending.session, status.lastAcceptedSequence >= pending.sequence else { return }
        awaitingAcceptance = nil
        writeDeadline = .infinity
        switch pending.operation {
        case .arm:
            guard sequencer.isArmed, let action = options.action else {
                finish("The adapter declined arming (reason \(status.reason)).", code: 1)
                return
            }
            phase = .action
            send(.action(action))
        case .action:
            guard status.state == .armed else {
                finish("The adapter rejected the action (reason \(status.reason)).", code: 1)
                return
            }
            acceptedAt = now
            phase = .settling
        case .disarm:
            guard status.state == .disarmed else { finish("The adapter did not disarm.", code: 1); return }
            finish("Adapter accepted one input command and disarmed. Verify the result on the target device.", code: 0)
        case .heartbeat: break
        }
    }

    private func finish(_ message: String, code: Int32) {
        guard exitStatus == nil else { return }
        print(message)
        timer?.invalidate()
        central?.stopScan()
        if let peripheral { central?.cancelPeripheralConnection(peripheral) }
        sequencer.reset()
        exitStatus = code
    }
}

@main
private struct PhoneBridgeCheck {
    @MainActor static func main() {
        do {
            guard let options = try Options.parse(Array(CommandLine.arguments.dropFirst())) else { return }
            let check = BridgeCheck(options: options)
            check.start()
            while check.exitStatus == nil { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
            exit(check.exitStatus ?? 1)
        } catch {
            fputs("\(error.localizedDescription)\n", stderr)
            exit(2)
        }
    }
}
