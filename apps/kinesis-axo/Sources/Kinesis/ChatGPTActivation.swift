import AppKit
import Foundation
import KinesisCore

extension MacShortcuts {
    /// Match the app's name as well as its identifier: the current ChatGPT app
    /// and some Codex installations share an identifier.
    static func isChatGPTApplication(bundleURL: URL, bundleIdentifier: String?,
                                    bundleName: String?, displayName: String?) -> Bool {
        bundleURL.isFileURL && bundleURL.lastPathComponent == "ChatGPT.app"
            && ["com.openai.codex", "com.openai.chat"].contains(bundleIdentifier ?? "")
            && [bundleName, displayName].contains("ChatGPT")
    }

    static func validatedChatGPTApplicationURL(_ url: URL) -> URL? {
        guard url.isFileURL else { return nil }
        let url = url.standardizedFileURL.resolvingSymlinksInPath()
        guard let bundle = Bundle(url: url),
              isChatGPTApplication(bundleURL: url, bundleIdentifier: bundle.bundleIdentifier,
                  bundleName: bundle.object(forInfoDictionaryKey: "CFBundleName") as? String,
                  displayName: bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String) else { return nil }
        return url
    }

    /// Candidate selection is separate from launching so fixture bundles can
    /// exercise the identity check without opening an application.
    static func resolveChatGPTApplicationURL(candidates: [URL]) -> URL? {
        candidates.lazy.compactMap { validatedChatGPTApplicationURL($0) }.first
    }

    func activateChatGPT(destination: ChatGPTDestination, chatLink: String) async throws -> Int32 {
        try Task.checkCancellation()
        guard trusted else { throw KinesisError(message: "Allow Kinesis in Accessibility to use Mac controls.") }
        let conversationURL: URL?
        if destination == .myDot {
            if chatLink.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                conversationURL = URL(string: "codex://dots")
            } else {
                guard let url = ChatGPTDestination.conversationURL(from: chatLink) else {
                    throw KinesisError(message: "Paste the copied ChatGPT conversation link in Gestures, or clear it to open My Dot.")
                }
                conversationURL = url
            }
        } else {
            conversationURL = nil
        }
        let workspace = NSWorkspace.shared
        var candidates = [URL(fileURLWithPath: "/Applications/ChatGPT.app", isDirectory: true),
            URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
                .appendingPathComponent("Applications/ChatGPT.app", isDirectory: true)]
        for identifier in ["com.openai.codex", "com.openai.chat"] {
            candidates += workspace.urlsForApplications(withBundleIdentifier: identifier)
        }
        guard let url = Self.resolveChatGPTApplicationURL(candidates: candidates) else {
            throw KinesisError(message: "Install ChatGPT.app before using ChatGPT Dictation.")
        }
        let deadline = ProcessInfo.processInfo.systemUptime + 3
        let originalFrontmost = workspace.frontmostApplication?.processIdentifier
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = false
        configuration.allowsRunningApplicationSubstitution = false
        configuration.createsNewApplicationInstance = false
        configuration.promptsUserIfNeeded = false
        configuration.addsToRecentItems = false

        // Accepted launch/URL delivery cannot be cancelled. Request background
        // opening; our activation and subsequent shortcut remain cancellable.
        let request = ChatGPTLaunchRequest()
        let application = try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                request.begin(continuation, deadline: deadline)
                guard !Task.isCancelled else {
                    request.complete(.failure(CancellationError()))
                    return
                }
                let completion: @Sendable (NSRunningApplication?, (any Error)?) -> Void = { application, error in
                    Task { @MainActor in
                        if let error { request.complete(.failure(error)) }
                        else if let application { request.complete(.success(application)) }
                        else { request.complete(.failure(KinesisError(message: "ChatGPT could not be opened."))) }
                    }
                }
                if destination == .myDot {
                    guard let conversationURL else {
                        request.complete(.failure(KinesisError(message: "The My Dot link could not be opened.")))
                        return
                    }
                    workspace.open([conversationURL], withApplicationAt: url, configuration: configuration,
                                   completionHandler: completion)
                } else {
                    workspace.openApplication(at: url, configuration: configuration, completionHandler: completion)
                }
            }
        } onCancel: {
            Task { @MainActor in request.complete(.failure(CancellationError())) }
        }
        try Task.checkCancellation()
        guard let actualURL = application.bundleURL,
              actualURL.standardizedFileURL.resolvingSymlinksInPath() == url,
              Self.validatedChatGPTApplicationURL(actualURL) == url,
              application.bundleIdentifier == Bundle(url: url)?.bundleIdentifier,
              application.processIdentifier > 0, !application.isTerminated else {
            throw KinesisError(message: "The opened app was not the selected ChatGPT.app. No shortcut was sent.")
        }
        let processID = application.processIdentifier

        func checkContext() throws {
            try Task.checkCancellation()
            guard !application.isTerminated else {
                throw KinesisError(message: "ChatGPT quit before Dictation could start.")
            }
            guard ProcessInfo.processInfo.systemUptime < deadline else {
                throw KinesisError(message: "ChatGPT did not become ready within 3 seconds. Try the gesture again.")
            }
            if let frontmost = workspace.frontmostApplication?.processIdentifier,
               frontmost != originalFrontmost && frontmost != processID {
                throw KinesisError(message: "The focused app changed. No ChatGPT shortcut was sent.")
            }
        }
        while !application.isFinishedLaunching {
            try checkContext()
            try await Task.sleep(for: .milliseconds(25))
        }
        try checkContext()
        if workspace.frontmostApplication?.processIdentifier != processID {
            guard application.activate(options: []) else {
                throw KinesisError(message: "macOS could not activate ChatGPT. No shortcut was sent.")
            }
        }
        while true {
            try checkContext()
            if workspace.frontmostApplication?.processIdentifier == processID {
                if destination == .myDot {
                    // URL delivery has no external composer-load acknowledgement.
                    // This yield gives routing a best-effort turn, not a readiness guarantee.
                    try await Task.sleep(for: .milliseconds(250))
                    try checkContext()
                    guard workspace.frontmostApplication?.processIdentifier == processID else {
                        throw KinesisError(message: "The focused app changed. No ChatGPT shortcut was sent.")
                    }
                }
                return processID
            }
            try await Task.sleep(for: .milliseconds(25))
        }
    }
}

/// Exactly one terminal result wins across launch completion, timeout, and
/// cancellation. Late launch callbacks cannot activate an app or resume twice.
@MainActor private final class ChatGPTLaunchRequest {
    private var continuation: CheckedContinuation<NSRunningApplication, any Error>?
    private var result: Result<NSRunningApplication, any Error>?
    private var timeout: Task<Void, Never>?

    func begin(_ continuation: CheckedContinuation<NSRunningApplication, any Error>, deadline: Double) {
        if let result {
            continuation.resume(with: result)
            return
        }
        self.continuation = continuation
        timeout = Task { @MainActor [weak self] in
            let seconds = max(0, deadline - ProcessInfo.processInfo.systemUptime)
            do { try await Task.sleep(for: .seconds(seconds)) }
            catch { return }
            self?.complete(.failure(KinesisError(message: "ChatGPT did not open within 3 seconds. Try the gesture again.")))
        }
    }

    func complete(_ result: Result<NSRunningApplication, any Error>) {
        guard self.result == nil else { return }
        self.result = result
        timeout?.cancel()
        timeout = nil
        let continuation = continuation
        self.continuation = nil
        continuation?.resume(with: result)
    }
}
