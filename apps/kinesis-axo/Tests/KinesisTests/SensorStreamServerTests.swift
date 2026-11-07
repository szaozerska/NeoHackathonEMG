import Foundation
import Network
import Testing
@testable import Kinesis

/// Real loopback TCP only. This never connects to Bluetooth, serial, or Keychain.
private final class SensorStreamReader: @unchecked Sendable {
    private let connection: NWConnection
    private let queue = DispatchQueue(label: "kinesis.sensor-stream-test-reader")
    private let lock = NSLock()
    private var received = Data()
    private var ended = false
    var text: String { lock.withLock { String(decoding: received, as: UTF8.self) } }
    var closed: Bool { lock.withLock { ended } }

    init(port: UInt16, request: String, readResponse: Bool = true) {
        connection = NWConnection(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: port)!, using: .tcp)
        connection.stateUpdateHandler = { [weak self] state in
            guard let self else { return }
            switch state {
            case .ready:
                self.connection.send(content: Data(request.utf8), completion: .contentProcessed { _ in })
                if readResponse { self.receive() }
            case .failed, .cancelled: self.lock.withLock { self.ended = true }
            default: break
            }
        }
        connection.start(queue: queue)
    }

    private func receive() {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, complete, error in
            guard let self else { return }
            self.lock.withLock {
                if let data { self.received.append(data) }
                if complete || error != nil { self.ended = true }
            }
            if !complete && error == nil { self.receive() }
        }
    }

    func stop() { connection.cancel() }
    deinit { connection.cancel() }
}

@MainActor
private func sensorEventually(_ predicate: () -> Bool) async -> Bool {
    let deadline = ProcessInfo.processInfo.systemUptime + 4
    while ProcessInfo.processInfo.systemUptime < deadline {
        if predicate() { return true }
        try? await Task.sleep(for: .milliseconds(10))
    }
    return predicate()
}

@MainActor
private func sensorServer() async throws -> SensorStreamServer {
    let server = SensorStreamServer()
    server.onSubscribe = { [weak server] id in
        server?.sendInitial([Data("event: hello\ndata: {\"version\":1}\n\n".utf8)], to: id)
    }
    server.start(port: 0)
    #expect(await sensorEventually { server.isRunning })
    _ = try #require(server.endpointURL)
    return server
}

private func sensorRequest(_ url: URL, method: String = "GET", target: String? = nil,
                           host: String? = nil, extra: String = "") -> String {
    let components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
    return "\(method) \(target ?? (components.path + "?" + components.percentEncodedQuery!)) HTTP/1.1\r\nHost: \(host ?? "127.0.0.1:\(components.port!)")\r\n\(extra)\r\n"
}

@Suite("Local sensor stream transport", .serialized)
@MainActor
struct SensorStreamServerTests {
    @Test func servesLiveSSEWithSnapshotBeforeSamplesAndClosesOnStop() async throws {
        let server = try await sensorServer()
        defer { server.stop() }
        let url = try #require(server.endpointURL)
        server.publish(Data("event: old\ndata: old\n\n".utf8))
        let reader = SensorStreamReader(port: UInt16(url.port!), request: sensorRequest(url))
        defer { reader.stop() }
        #expect(await sensorEventually { server.clientCount == 1 && reader.text.contains("event: hello") })
        server.publish(Data("event: gyro\ndata: live\n\n".utf8))
        #expect(await sensorEventually { reader.text.contains("data: live") })
        let text = reader.text
        #expect(text.hasPrefix("HTTP/1.1 200 OK\r\n"))
        #expect(text.contains("Content-Type: text/event-stream\r\n"))
        #expect(text.contains("Cache-Control: no-store\r\n"))
        #expect(!text.contains("event: old"))
        #expect(try #require(text.range(of: "event: hello")).lowerBound < #require(text.range(of: "event: gyro")).lowerBound)
        server.stop()
        #expect(await sensorEventually { reader.closed })
        #expect(server.clientCount == 0)
        #expect(!server.isRunning)
        #expect(server.endpointURL == nil)
    }

    @Test func rejectsMissingTokenForeignOriginHostAndWriteRequests() async throws {
        let server = try await sensorServer()
        defer { server.stop() }
        let url = try #require(server.endpointURL)
        let cases: [(String, Int)] = [
            (sensorRequest(url, target: "/events"), 403),
            (sensorRequest(url, target: "/events?token=wrong"), 403),
            (sensorRequest(url, extra: "Origin: https://example.com\r\n"), 403),
            (sensorRequest(url, extra: "Origin: null\r\n"), 403),
            (sensorRequest(url, host: "example.com:\(url.port!)"), 403),
            (sensorRequest(url, method: "POST"), 405),
            (sensorRequest(url, target: "/control"), 404),
            (sensorRequest(url, extra: "Transfer-Encoding: chunked\r\n"), 403),
            (sensorRequest(url, extra: "Content-Length: 1\r\n"), 403),
            (sensorRequest(url, extra: "Host: localhost:\(url.port!)\r\n"), 400),
        ]
        for (request, code) in cases {
            let reader = SensorStreamReader(port: UInt16(url.port!), request: request)
            #expect(await sensorEventually { reader.closed })
            #expect(reader.text.hasPrefix("HTTP/1.1 \(code) "))
            #expect(!reader.text.contains("event: hello"))
            reader.stop()
        }
        #expect(server.clientCount == 0)
    }

    @Test func hapticsRequestsNeedTheTokenAValidDurationAndNoBrowserOrigin() async throws {
        let server = try await sensorServer()
        defer { server.stop() }
        var played: [UInt64] = []
        server.onHaptic = { played.append($0) }
        let url = try #require(server.endpointURL)
        let token = try #require(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first?.value)
        let cases: [(String, Int)] = [
            (sensorRequest(url, method: "POST", target: "/haptics?token=\(token)&ms=120"), 202),
            (sensorRequest(url, method: "POST", target: "/haptics?token=wrong&ms=120"), 403),
            (sensorRequest(url, method: "POST", target: "/haptics?token=\(token)"), 403),
            (sensorRequest(url, method: "POST", target: "/haptics?token=\(token)&ms=0"), 400),
            (sensorRequest(url, method: "POST", target: "/haptics?token=\(token)&ms=2001"), 400),
            (sensorRequest(url, method: "POST", target: "/haptics?token=\(token)&ms=120",
                           extra: "Origin: http://localhost:3000\r\n"), 403),
            (sensorRequest(url, target: "/haptics?token=\(token)&ms=120"), 405),
        ]
        for (request, code) in cases {
            let reader = SensorStreamReader(port: UInt16(url.port!), request: request)
            #expect(await sensorEventually { reader.closed })
            #expect(reader.text.hasPrefix("HTTP/1.1 \(code) "))
            reader.stop()
        }
        #expect(await sensorEventually { played == [120] })
    }

    @Test func allowsOnlyExplicitLocalHTTPOriginAndReflectsIt() async throws {
        let server = try await sensorServer()
        defer { server.stop() }
        let url = try #require(server.endpointURL)
        let reader = SensorStreamReader(port: UInt16(url.port!),
            request: sensorRequest(url, host: "localhost:\(url.port!)", extra: "Origin: http://localhost:3000\r\n"))
        defer { reader.stop() }
        #expect(await sensorEventually { reader.text.contains("event: hello") })
        #expect(reader.text.contains("Access-Control-Allow-Origin: http://localhost:3000\r\n"))
        #expect(!reader.text.contains("Access-Control-Allow-Origin: *"))
    }

    @Test func holdsLiveDataUntilClientSnapshotAndNeverReplaysEarlierSamples() async throws {
        let server = try await sensorServer()
        defer { server.stop() }
        var subscribed: UUID?
        server.onSubscribe = { subscribed = $0 }
        let url = try #require(server.endpointURL)
        let reader = SensorStreamReader(port: UInt16(url.port!), request: sensorRequest(url))
        defer { reader.stop() }
        #expect(await sensorEventually { subscribed != nil })
        server.publish(Data("event: before\ndata: stale\n\n".utf8))
        server.sendInitial([Data("event: snapshot\ndata: current\n\n".utf8)], to: try #require(subscribed))
        #expect(await sensorEventually { reader.text.contains("event: snapshot") })
        server.publish(Data("event: after\ndata: fresh\n\n".utf8))
        #expect(await sensorEventually { reader.text.contains("event: after") })
        #expect(!reader.text.contains("event: before"))
    }

    @Test func oversizedIngressDisconnectsInsteadOfAccumulatingOrReplaying() async throws {
        let server = try await sensorServer()
        defer { server.stop() }
        let url = try #require(server.endpointURL)
        let reader = SensorStreamReader(port: UInt16(url.port!), request: sensorRequest(url))
        defer { reader.stop() }
        #expect(await sensorEventually { server.clientCount == 1 })
        server.publish(Data(repeating: 65, count: 512 * 1024 + 1))
        #expect(await sensorEventually { reader.closed && server.clientCount == 0 })
        #expect(server.isRunning)
        let next = SensorStreamReader(port: UInt16(url.port!), request: sensorRequest(url))
        defer { next.stop() }
        #expect(await sensorEventually { next.text.contains("event: hello") })
        #expect(next.text.count < 1024)
    }

    @Test func oversizedHeadersAreRejectedWithoutStartingStream() async throws {
        let server = try await sensorServer()
        defer { server.stop() }
        let url = try #require(server.endpointURL)
        let reader = SensorStreamReader(port: UInt16(url.port!), request:
            sensorRequest(url, extra: "X-Padding: \(String(repeating: "a", count: 9000))\r\n"))
        defer { reader.stop() }
        #expect(await sensorEventually { reader.closed })
        #expect(reader.text.hasPrefix("HTTP/1.1 431 "))
        #expect(server.clientCount == 0)
    }

    @Test func nonReadingClientCannotBuildAnUnboundedOutputQueue() async throws {
        let server = try await sensorServer()
        defer { server.stop() }
        let url = try #require(server.endpointURL)
        let reader = SensorStreamReader(port: UInt16(url.port!), request: sensorRequest(url), readResponse: false)
        defer { reader.stop() }
        #expect(await sensorEventually { server.clientCount == 1 })
        let frame = Data(repeating: 65, count: 128 * 1024)
        for _ in 0..<200 {
            guard server.clientCount > 0 else { break }
            server.publish(frame)
            // Give ingress time to drain: this exercises client output bounds,
            // rather than the independent producer-side overflow guard.
            try? await Task.sleep(for: .milliseconds(10))
        }
        #expect(await sensorEventually { server.clientCount == 0 })
        #expect(server.isRunning)
    }

    @Test func restartRotatesCapabilityAndStopReportsBoundaryOnce() async throws {
        let server = try await sensorServer()
        defer { server.stop() }
        let oldURL = try #require(server.endpointURL)
        var stopped = 0
        server.onStopped = { stopped += 1 }
        server.stop()
        #expect(stopped == 1)
        server.start(port: 0)
        #expect(await sensorEventually { server.isRunning })
        let newURL = try #require(server.endpointURL)
        #expect(oldURL.query != newURL.query)
        let oldTarget = oldURL.path + "?" + oldURL.query!
        let reader = SensorStreamReader(port: UInt16(newURL.port!), request: sensorRequest(newURL, target: oldTarget))
        defer { reader.stop() }
        #expect(await sensorEventually { reader.closed })
        #expect(reader.text.hasPrefix("HTTP/1.1 403 "))
    }

    @Test func clientLimitRecoversAfterDisconnectAndSendsKeepalive() async throws {
        let server = try await sensorServer()
        defer { server.stop() }
        let url = try #require(server.endpointURL)
        var readers: [SensorStreamReader] = []
        defer { for reader in readers { reader.stop() } }
        for expected in 1...4 {
            readers.append(SensorStreamReader(port: UInt16(url.port!), request: sensorRequest(url)))
            #expect(await sensorEventually { server.clientCount == expected })
        }
        let excess = SensorStreamReader(port: UInt16(url.port!), request: sensorRequest(url))
        defer { excess.stop() }
        #expect(await sensorEventually { excess.closed })
        #expect(server.clientCount == 4)
        readers[0].stop()
        #expect(await sensorEventually { server.clientCount == 3 })
        readers.append(SensorStreamReader(port: UInt16(url.port!), request: sensorRequest(url)))
        #expect(await sensorEventually { server.clientCount == 4 })
        #expect(await sensorEventually { readers[1].text.contains(": keepalive\n\n") })
    }
}
