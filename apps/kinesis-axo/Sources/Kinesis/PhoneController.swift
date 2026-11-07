import Combine
import Foundation
import KinesisCore
import OSLog

/// Owns the phone profile. No Bluetooth band migration and no Mac input posting
/// occur here: the selected USB adapter is the iPhone's keyboard/mouse.
@MainActor
final class PhoneController: ObservableObject {
    let bridge: any PhoneUSBTransport
    @Published private(set) var selected = false
    @Published private(set) var enabled = false
    @Published private(set) var connected = false
    @Published private(set) var ready = false
    @Published private(set) var ports: [String] = []
    @Published private(set) var status = "Connect the phone adapter with USB."
    @Published private(set) var lastAction = "Phone controls are paused"
    @Published var selectedPort: String {
        didSet {
            guard selectedPort != oldValue else { return }
            pause()
            bridge.disconnect()
            bridge.selectedPort = selectedPort
            defaults.set(selectedPort, forKey: "phoneUSBPort")
            synchronize()
        }
    }
    @Published var bindings: [String: PhoneGestureAction] {
        didSet {
            stopPendingInput()
            defaults.set(bindings.mapValues(\.rawValue), forKey: "phoneGestureBindings")
        }
    }
    @Published var scrollDistance: Double {
        didSet { motion.stop(); defaults.set(scrollDistance, forKey: "phoneScrollDistance") }
    }
    @Published var reverseScroll: Bool {
        didSet { motion.stop(); defaults.set(reverseScroll, forKey: "phoneReverseScroll") }
    }
    @Published var dictationShortcutReady: Bool {
        didSet { stopPendingInput(); defaults.set(dictationShortcutReady, forKey: "phoneDictationShortcutReady") }
    }
    private let defaults: UserDefaults
    private let clock: () -> Double
    private let automaticallyTicks: Bool
    private var timer: Timer?
    private var wantsArm = false
    private var armRequestedAt: Double?
    private var armedAt = Double.infinity
    private var router = GestureRouter()
    private var motion = PhoneScrollMotion()
    private let scrollLog = Logger(subsystem: "local.callbacked.kinesis", category: "phone-scroll")
    private var scrollPackets = 0
    private var scrollUnits = 0
    private var scrollTickAt: Double?
    private var lastKeyAt = -Double.infinity
    private struct PendingTap {
        let action: PhoneGestureAction
        let queuedAt: Double
    }
    private var singleTaps: [String: PendingTap] = [:]
    private var setupKeyRequestedAt: Double?
    private var setupArmSent = false
    private var setupDisarmAt: Double?

    init(defaults: UserDefaults, bridge: (any PhoneUSBTransport)? = nil,
         clock: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime },
         automaticallyTicks: Bool = true) {
        self.defaults = defaults
        self.clock = clock
        self.automaticallyTicks = automaticallyTicks
        self.bridge = bridge ?? PhoneUSBBridge()
        selectedPort = defaults.string(forKey: "phoneUSBPort") ?? ""
        var initialBindings = PhoneGestureAction.defaultBindings
        let valid = Set(SwipeDirection.allCases.map { RecognizedGesture.swipe($0).bindingID }
            + TapGesture.allCases.map { RecognizedGesture.tap($0).bindingID })
        if let saved = defaults.dictionary(forKey: "phoneGestureBindings") as? [String: String] {
            for (key, value) in saved where valid.contains(key) {
                if let action = PhoneGestureAction(rawValue: value) { initialBindings[key] = action }
            }
        }
        bindings = initialBindings
        let savedDistance = defaults.double(forKey: "phoneScrollDistance")
        scrollDistance = (1...120).contains(savedDistance) ? savedDistance : 48
        reverseScroll = defaults.bool(forKey: "phoneReverseScroll")
        dictationShortcutReady = defaults.bool(forKey: "phoneDictationShortcutReady")
        self.bridge.selectedPort = selectedPort
        self.bridge.onBoundary = { [weak self] in self?.connectionBoundary() }
    }

    func refreshPorts() {
        bridge.refreshPorts()
        if selectedPort.isEmpty, bridge.ports.count == 1 { selectedPort = bridge.ports[0] }
        synchronize()
    }

    func connect() {
        pause()
        bridge.selectedPort = selectedPort
        bridge.connect()
        startTimer()
        synchronize()
    }

    func disconnect() {
        pause()
        bridge.disconnect()
        timer?.invalidate()
        timer = nil
        synchronize()
    }

    func enable() {
        guard bridge.connected, bridge.ready else { synchronize(); return }
        selected = true
        stopPendingInput()
        router.reset()
        wantsArm = true
        armRequestedAt = clock()
        armedAt = .infinity
        startTimer()
        tick()
        synchronize()
    }

    func pause() {
        wantsArm = false
        armRequestedAt = nil
        enabled = false
        armedAt = .infinity
        stopPendingInput()
        router.reset()
        setupKeyRequestedAt = nil
        setupArmSent = false
        setupDisarmAt = nil
        bridge.disarm()
        lastAction = "Phone controls are paused"
    }

    func leavePhoneProfile() { pause(); selected = false }

    /// Position the iPhone's mouse over the area that should receive wheel
    /// input. This is one relative movement, with no click or held button.
    func movePointer(horizontal: Int, vertical: Int) {
        guard enabled, bridge.armed, let movement = PhonePointerMove(dx: horizontal, dy: vertical) else { return }
        stopPendingInput()
        guard !bridge.busy, bridge.send(action: .move(movement)) else {
            lastAction = "Adapter busy; press the pointer button again"
            return
        }
        lastAction = "Pointer moved · place it over the content to scroll"
    }

    func testPointerClick() {
        guard enabled, bridge.armed else { return }
        stopPendingInput()
        guard !bridge.busy, bridge.send(action: .click) else {
            lastAction = "Adapter busy; click was not sent"
            return
        }
        lastAction = "Pointer clicked once"
    }

    /// The user presses this while the iPhone is recording a shortcut binding.
    /// It sends F13 once, independently of the band's gesture assignments.
    func sendDictationSetupKey() {
        guard bridge.connected, bridge.ready else { return }
        pause()
        setupKeyRequestedAt = clock()
        startTimer()
        tick()
    }

    @discardableResult
    func receive(_ message: BandGesture, at now: Double) -> RecognizedGesture? {
        guard selected, now.isFinite, message.receivedAt.isFinite,
              now - message.receivedAt >= 0, now - message.receivedAt <= 0.35 else { return nil }
        if ["press", "hold", "buttonPress", "buttonHold"].contains(message.action)
            || ["buttonPress", "buttonHold"].contains(message.derivedAction) {
            singleTaps[message.finger] = nil
        }
        guard let gesture = router.gesture(from: message, now: now) else { return nil }
        guard enabled, message.receivedAt > armedAt else { return gesture }
        let action = bindings[gesture.bindingID] ?? .none
        if case .tap(let tap) = gesture {
            if tap.action != "tap" { singleTaps[tap.finger] = nil }
            else if action != .none, TapGesture.allCases.contains(where: {
                $0.finger == tap.finger && $0.action != "tap"
                    && (bindings[RecognizedGesture.tap($0).bindingID] ?? .none) != .none
            }) {
                singleTaps[tap.finger] = PendingTap(action: action, queuedAt: now)
                return gesture
            }
        }
        perform(action, at: now)
        return gesture
    }

    func tick() {
        let now = clock()
        synchronize()
        if let requestedAt = setupKeyRequestedAt {
            if now - requestedAt > 3 { pause(); lastAction = "F13 was not sent. Try again when the adapter is ready." }
            else if !setupArmSent, !bridge.busy, bridge.ready {
                setupArmSent = true
                bridge.arm()
            }
            else if bridge.armed, !bridge.busy,
                    bridge.send(action: .key(PhoneKeyboardChord(.f13))) {
                setupKeyRequestedAt = nil
                setupDisarmAt = now + 0.25
                lastAction = "F13 sent once to your iPhone"
            }
            return
        }
        if let deadline = setupDisarmAt {
            if now >= deadline, !bridge.busy { setupDisarmAt = nil; bridge.disarm() }
            return
        }
        if let requestedAt = armRequestedAt {
            if now - requestedAt > 3 {
                armRequestedAt = nil
                wantsArm = false
                lastAction = "Adapter busy; enable phone controls again when ready"
            } else if bridge.ready, !bridge.busy {
                armRequestedAt = nil
                bridge.arm()
            }
            return
        }
        guard enabled else { motion.stop(); return }
        for (finger, pending) in singleTaps where now - pending.queuedAt >= 0.4 {
            singleTaps[finger] = nil
            if now - pending.queuedAt <= 0.55 { perform(pending.action, at: now) }
        }
        let wasMoving = motion.isActive
        let tickGap = scrollTickAt.map { now - $0 } ?? 0
        if wasMoving { scrollTickAt = now }
        let amount = motion.step(at: now)
        if amount != 0, !bridge.busy, let scroll = PhoneScroll(vertical: amount),
           bridge.send(action: .scroll(scroll)) {
            motion.commit(amount)
            scrollPackets += 1
            scrollUnits += abs(amount)
            if scrollPackets == 1 { scrollLog.info("First phone wheel packet prepared: \(amount, privacy: .public)") }
        }
        if wasMoving, !motion.isActive {
            scrollLog.info("Phone scroll ended: \(self.scrollPackets, privacy: .public) packets, \(self.scrollUnits, privacy: .public) units, tick gap \(tickGap, privacy: .public)s")
            scrollTickAt = nil
        }
    }

    private func perform(_ action: PhoneGestureAction, at now: Double) {
        switch action {
        case .none: return
        case .stopScrolling: stopPendingInput()
        case .scrollUp, .scrollDown:
            let direction = (action == .scrollUp ? 1 : -1) * (reverseScroll ? -1 : 1)
            let distance = scrollDistance.isFinite ? Int(min(120, max(1, scrollDistance))) : 48
            motion.flick(direction: direction, distance: distance, at: now)
            scrollPackets = 0
            scrollUnits = 0
            scrollTickAt = now
            scrollLog.info("Phone scroll requested: direction \(direction, privacy: .public), distance \(distance, privacy: .public)")
        default:
            if motion.isActive { scrollLog.info("Phone scroll replaced by another phone key action") }
            motion.stop()
            guard now - lastKeyAt >= 0.4 else { return }
            if action == .chatGPTPrompt, !dictationShortcutReady {
                lastAction = "Set up and confirm the iPhone's F13 Dictation shortcut first"
                return
            }
            guard let navigation = action.navigation, !bridge.busy, bridge.send(action: navigation) else {
                lastAction = "Adapter busy; gesture skipped"
                return
            }
            lastKeyAt = now
        }
        lastAction = action.title
    }

    private func stopPendingInput() {
        if motion.isActive {
            scrollLog.info("Phone scroll cancelled by a context change after \(self.scrollPackets, privacy: .public) packets")
        }
        motion.stop()
        singleTaps.removeAll()
    }

    private func connectionBoundary() {
        wantsArm = false
        armRequestedAt = nil
        enabled = false
        armedAt = .infinity
        stopPendingInput()
        router.reset()
        setupKeyRequestedAt = nil
        setupArmSent = false
        setupDisarmAt = nil
        lastAction = "Phone connection changed; enable phone controls to resume"
    }

    private func synchronize() {
        if connected != bridge.connected { connected = bridge.connected }
        if ready != bridge.ready { ready = bridge.ready }
        if ports != bridge.ports { ports = bridge.ports }
        if status != bridge.statusText { status = bridge.statusText }
        let active = selected && wantsArm && bridge.armed && bridge.ready
        if active != enabled {
            enabled = active
            armedAt = active ? clock() : .infinity
            router.reset()
            stopPendingInput()
            if active { lastAction = "Ready for phone gestures" }
        }
    }

    private func startTimer() {
        guard automaticallyTicks, timer == nil else { return }
        let timer = Timer(timeInterval: 0.02, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        self.timer = timer
        RunLoop.main.add(timer, forMode: .common)
    }
}
