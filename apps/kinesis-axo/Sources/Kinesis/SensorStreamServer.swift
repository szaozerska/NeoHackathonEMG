import Combine
import Foundation
import KinesisCore
import Network

/// Explicitly enabled local sensor feed: SSE reads on `/events`, plus `POST /haptics?ms=` buzzes.
/// Network work never runs on the band/UI actor, and a slow reader is disconnected rather than replayed.
@MainActor
final class SensorStreamServer: ObservableObject {
    @Published private(set) var isRunning = false
    @Published private(set) var clientCount = 0
    @Published private(set) var endpointURL: URL?
    @Published private(set) var statusText = "Local stream is off."
    var onSubscribe: ((UUID) -> Void)?
    var onHaptic: ((UInt64) -> Void)?
    var onStopped: (() -> Void)?
    private var worker: SensorStreamWorker?
    private var generation = UUID()

    func start(port: UInt16 = 8766) {
        guard worker == nil else { return }
        let generation = UUID()
        self.generation = generation
        let token = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        statusText = "Starting local stream…"
        let worker = SensorStreamWorker(port: port, token: token, update: { [weak self] update in
            Task { @MainActor [weak self] in
                guard let self, self.generation == generation else { return }
                self.isRunning = update.running
                self.clientCount = update.clients
                self.statusText = update.text
                if let port = update.port {
                    self.endpointURL = URL(string: "http://127.0.0.1:\(port)/events?token=\(token)")
                }
                if update.stopped {
                    self.worker = nil
                    self.endpointURL = nil
                    self.onStopped?()
                }
            }
        }, subscribe: { [weak self] client in
            Task { @MainActor [weak self] in
                guard let self, self.generation == generation else { return }
                self.onSubscribe?(client)
            }
        }, haptic: { [weak self] milliseconds in
            Task { @MainActor [weak self] in
                guard let self, self.generation == generation else { return }
                self.onHaptic?(milliseconds)
            }
        })
        self.worker = worker
        worker.start()
    }

    func stop() {
        generation = UUID()
        worker?.stop()
        worker = nil
        isRunning = false
        clientCount = 0
        endpointURL = nil
        statusText = "Local stream is off."
        onStopped?()
    }

    func publish(_ sseFrame: Data) { worker?.publish(sseFrame) }

    /// Only this client receives the snapshot. Live samples start after it.
    func sendInitial(_ frames: [Data], to clientID: UUID) {
        worker?.sendInitial(frames, to: clientID)
    }

    deinit { worker?.stop() }
}

private struct SensorStreamUpdate: Sendable {
    var running = false
    var clients = 0
    var port: UInt16?
    var text: String
    var stopped = false
}

/// All connection state belongs to queue. The ingress lock bounds both bytes
/// and outstanding dispatch work before the producer returns to sensor input.
private final class SensorStreamWorker: @unchecked Sendable {
    private static let byteLimit = 512 * 1024
    private static let maximumClients = 4
    private let queue = DispatchQueue(label: "local.callbacked.kinesis.sensor-stream", qos: .userInitiated)
    private let ingressLock = NSLock()
    private var ingress: [Packet] = []
    private var ingressOrdinal: UInt64 = 0
    private var ingressBytes = 0
    private var ingressScheduled = false
    private var ingressOverflowed = false
    private var accepting = true
    private let requestedPort: UInt16
    private let token: String
    private let update: @Sendable (SensorStreamUpdate) -> Void
    private let subscribe: @Sendable (UUID) -> Void
    private let haptic: @Sendable (UInt64) -> Void
    private var listener: NWListener?
    private var timer: DispatchSourceTimer?
    private var clients: [UUID: Client] = [:]
    private var stopped = false
    private var ready = false
    private var boundPort: UInt16?

    private struct Packet {
        let data: Data
        let time: Double
        var ordinal: UInt64 = 0
    }
    private final class Client: @unchecked Sendable {
        let id = UUID()
        let connection: NWConnection
        let openedAt = ProcessInfo.processInfo.systemUptime
        var headers = Data()
        var streaming = false
        var active = false
        var skipThrough: UInt64 = 0
        var pending: [Packet] = []
        var bytes = 0
        var sendingAt: Double?
        var lastSent = ProcessInfo.processInfo.systemUptime
        init(_ connection: NWConnection) { self.connection = connection }
    }

    init(port: UInt16, token: String,
         update: @escaping @Sendable (SensorStreamUpdate) -> Void,
         subscribe: @escaping @Sendable (UUID) -> Void,
         haptic: @escaping @Sendable (UInt64) -> Void) {
        requestedPort = port
        self.token = token
        self.update = update
        self.subscribe = subscribe
        self.haptic = haptic
    }

    func start() {
        queue.async { [self] in
            guard !stopped else { return }
            do {
                let parameters = NWParameters.tcp
                parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: requestedPort)!)
                parameters.acceptLocalOnly = true
                parameters.allowLocalEndpointReuse = true
                let listener = try NWListener(using: parameters)
                self.listener = listener
                listener.newConnectionHandler = { [weak self] connection in self?.accept(connection) }
                listener.stateUpdateHandler = { [weak self] state in
                    guard let self, !self.stopped else { return }
                    switch state {
                    case .ready:
                        self.ready = true
                        self.boundPort = listener.port?.rawValue
                        self.report()
                    case .failed:
                        self.finish(text: "Could not open the local stream. Port may already be in use.")
                    case .waiting:
                        self.finish(text: "Local stream is unavailable. Try enabling it again.")
                    default: break
                    }
                }
                listener.start(queue: queue)
                let timer = DispatchSource.makeTimerSource(queue: queue)
                timer.schedule(deadline: .now() + .milliseconds(250), repeating: .milliseconds(250))
                timer.setEventHandler { [weak self] in self?.tick() }
                self.timer = timer
                timer.resume()
            } catch {
                finish(text: "Could not open the local stream.")
            }
        }
    }

    func stop() {
        ingressLock.lock()
        accepting = false
        ingress.removeAll()
        ingressBytes = 0
        ingressLock.unlock()
        queue.async { [self] in finish(text: "Local stream is off.") }
    }

    func publish(_ data: Data) {
        ingressLock.lock()
        guard accepting else { ingressLock.unlock(); return }
        if data.count > Self.byteLimit || ingressBytes > Self.byteLimit - data.count || ingress.count >= 1024 {
            ingressOverflowed = true
        } else {
            ingressOrdinal &+= 1
            ingress.append(Packet(data: data, time: ProcessInfo.processInfo.systemUptime, ordinal: ingressOrdinal))
            ingressBytes += data.count
        }
        let schedule = !ingressScheduled
        ingressScheduled = true
        ingressLock.unlock()
        if schedule { queue.async { [self] in drainIngress() } }
    }

    func sendInitial(_ frames: [Data], to id: UUID) {
        // Snapshot size is bounded before capturing it in a dispatch closure.
        guard frames.count <= 16, frames.reduce(0, { $0 + $1.count }) <= Self.byteLimit else { return }
        ingressLock.lock()
        let skipThrough = ingressOrdinal
        ingressLock.unlock()
        queue.async { [self] in
            guard let client = clients[id], client.streaming, !client.active else { return }
            client.skipThrough = skipThrough
            for frame in frames { enqueue(frame, client: client) }
            guard clients[id] != nil else { return }
            client.active = true
            pump(client)
            report()
        }
    }

    private func drainIngress() {
        ingressLock.lock()
        let data = ingress
        let overflow = ingressOverflowed
        ingress.removeAll(keepingCapacity: true)
        ingressBytes = 0
        ingressOverflowed = false
        ingressScheduled = false
        ingressLock.unlock()
        guard !stopped else { return }
        if overflow || data.first.map({ ProcessInfo.processInfo.systemUptime - $0.time > 1 }) == true {
            for id in Array(clients.keys) { close(id) }
            return
        }
        for frame in data {
            for client in Array(clients.values) where client.active && frame.ordinal > client.skipThrough {
                enqueue(frame.data, client: client)
            }
        }
    }

    private func accept(_ connection: NWConnection) {
        guard !stopped, clients.count < Self.maximumClients else { connection.cancel(); return }
        let client = Client(connection)
        clients[client.id] = client
        connection.stateUpdateHandler = { [weak self, weak client] state in
            guard let self, let client else { return }
            switch state {
            case .ready: self.receive(client)
            case .failed, .cancelled: self.close(client.id)
            default: break
            }
        }
        connection.start(queue: queue)
    }

    private func receive(_ client: Client) {
        client.connection.receive(minimumIncompleteLength: 1, maximumLength: 8192) { [weak self, weak client] data, _, complete, error in
            guard let self, let client, self.clients[client.id] != nil else { return }
            if complete || error != nil { self.close(client.id); return }
            if let data, !data.isEmpty {
                guard !client.streaming else { self.close(client.id); return }
                client.headers.append(data)
                guard client.headers.count <= 8192 else { self.reject(client, code: 431); return }
                if let end = client.headers.range(of: Data("\r\n\r\n".utf8)) {
                    guard end.upperBound == client.headers.endIndex else { self.reject(client, code: 400); return }
                    self.handshake(client)
                }
            }
            if self.clients[client.id] != nil { self.receive(client) }
        }
    }

    private func handshake(_ client: Client) {
        guard let request = String(data: client.headers, encoding: .ascii), let port = boundPort else {
            reject(client, code: 400); return
        }
        let lines = request.components(separatedBy: "\r\n")
        let first = lines[0].split(separator: " ", omittingEmptySubsequences: false)
        guard first.count == 3, first[2] == "HTTP/1.1" else { reject(client, code: 400); return }
        var fields: [String: String] = [:]
        for line in lines.dropFirst() where !line.isEmpty {
            guard let colon = line.firstIndex(of: ":"), !line.hasPrefix(" "), !line.hasPrefix("\t") else {
                reject(client, code: 400); return
            }
            let key = line[..<colon].lowercased()
            guard fields[key] == nil else { reject(client, code: 400); return }
            fields[key] = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
        }
        guard let host = fields["host"], ["127.0.0.1:\(port)", "localhost:\(port)"].contains(host.lowercased()),
              fields["transfer-encoding"] == nil,
              fields["content-length"] == nil || fields["content-length"] == "0" else {
            reject(client, code: 403); return
        }
        let target = String(first[1])
        guard target.hasPrefix("/"), !target.hasPrefix("//"), let components = URLComponents(string: target),
              ["/events", "/haptics"].contains(components.path) else {
            reject(client, code: 404); return
        }
        switch (first[0], components.path) {
        case ("GET", "/events"): openStream(client, query: components.queryItems ?? [], origin: fields["origin"])
        case ("POST", "/haptics"): playHaptic(client, query: components.queryItems ?? [], origin: fields["origin"])
        default: reject(client, code: 405)
        }
    }

    /// Only browser-free callers: a page on any origin could otherwise send this simple POST.
    private func playHaptic(_ client: Client, query: [URLQueryItem], origin: String?) {
        guard origin == nil, query.count == 2, query.first(where: { $0.name == "token" })?.value == token,
              let milliseconds = query.first(where: { $0.name == "ms" })?.value.flatMap({ UInt64($0) }) else {
            reject(client, code: 403); return
        }
        guard BandSession.hapticDurations.contains(milliseconds) else { reject(client, code: 400); return }
        haptic(milliseconds)
        respond(client, status: "202 Accepted")
    }

    private func openStream(_ client: Client, query: [URLQueryItem], origin: String?) {
        guard query.count == 1,
              query.first?.name == "token", query.first?.value == token else {
            reject(client, code: 403); return
        }
        var cors = ""
        if let origin {
            guard let originURL = URLComponents(string: origin), originURL.scheme == "http",
                  ["127.0.0.1", "localhost"].contains(originURL.host?.lowercased() ?? ""),
                  originURL.user == nil, originURL.password == nil,
                  originURL.path.isEmpty, originURL.query == nil, originURL.fragment == nil else {
                reject(client, code: 403); return
            }
            cors = "Access-Control-Allow-Origin: \(origin)\r\nVary: Origin\r\n"
        }
        client.headers.removeAll()
        client.streaming = true
        let response = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\n\(cors)\r\n: connected\n\n"
        enqueue(Data(response.utf8), client: client)
        report()
        subscribe(client.id)
    }

    private func reject(_ client: Client, code: Int) {
        respond(client, status: "\(code) Rejected")
    }

    private func respond(_ client: Client, status: String) {
        client.streaming = true // Prevent parsing another request during response.
        let bytes = Data("HTTP/1.1 \(status)\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".utf8)
        client.connection.send(content: bytes, completion: .contentProcessed { [weak self, weak client] _ in
            guard let self, let client else { return }
            self.close(client.id)
        })
    }

    private func enqueue(_ data: Data, client: Client) {
        guard clients[client.id] != nil else { return }
        guard data.count <= Self.byteLimit, client.bytes <= Self.byteLimit - data.count,
              client.pending.count < 1024 else { close(client.id); return }
        client.pending.append(Packet(data: data, time: ProcessInfo.processInfo.systemUptime))
        client.bytes += data.count
        pump(client)
    }

    private func pump(_ client: Client) {
        guard clients[client.id] != nil, client.sendingAt == nil, !client.pending.isEmpty else { return }
        let packet = client.pending.removeFirst()
        let now = ProcessInfo.processInfo.systemUptime
        guard now - packet.time <= 1 else { close(client.id); return }
        client.sendingAt = now
        client.connection.send(content: packet.data, completion: .contentProcessed { [weak self, weak client] error in
            guard let self, let client, self.clients[client.id] != nil else { return }
            guard error == nil else { self.close(client.id); return }
            client.bytes -= packet.data.count
            client.sendingAt = nil
            client.lastSent = ProcessInfo.processInfo.systemUptime
            self.pump(client)
        })
    }

    private func tick() {
        let now = ProcessInfo.processInfo.systemUptime
        for client in Array(clients.values) {
            if (!client.active && now - client.openedAt > 3)
                || client.sendingAt.map({ now - $0 > 2 }) == true
                || client.pending.first.map({ now - $0.time > 1 }) == true {
                close(client.id)
            } else if client.active && client.pending.isEmpty && client.sendingAt == nil && now - client.lastSent >= 1 {
                enqueue(Data(": keepalive\n\n".utf8), client: client)
            }
        }
    }

    private func close(_ id: UUID) {
        guard let client = clients.removeValue(forKey: id) else { return }
        client.connection.stateUpdateHandler = nil
        client.connection.cancel()
        report()
    }

    private func report() {
        guard !stopped else { return }
        let count = clients.values.filter(\.active).count
        update(SensorStreamUpdate(running: ready, clients: count, port: boundPort,
            text: count == 0 ? "Local stream ready. Waiting for a reader." : "Local stream live · \(count) reader\(count == 1 ? "" : "s")."))
    }

    private func finish(text: String) {
        guard !stopped else { return }
        stopped = true
        ready = false
        timer?.cancel()
        timer = nil
        listener?.stateUpdateHandler = nil
        listener?.newConnectionHandler = nil
        listener?.cancel()
        listener = nil
        for id in Array(clients.keys) { close(id) }
        ingressLock.lock()
        accepting = false
        ingress.removeAll()
        ingressBytes = 0
        ingressLock.unlock()
        update(SensorStreamUpdate(text: text, stopped: true))
    }
}
