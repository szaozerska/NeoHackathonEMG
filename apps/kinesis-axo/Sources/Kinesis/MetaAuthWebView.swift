import AppKit
import SwiftUI
import WebKit

/// A private sign-in browser that preserves WebKit's opener relationship for login pop-ups.
struct MetaAuthWebView: NSViewRepresentable {
    let url: URL
    var onHost: @MainActor (String) -> Void = { _ in }
    /// The production policy permits HTTPS only. A local fixture can inject its own allowlist.
    var allowNavigation: (URL) -> Bool = MetaAuthWebView.standardNavigation
    let onCallback: @MainActor (URL) -> Void

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let webview = WKWebView(frame: .zero, configuration: configuration)
        context.coordinator.attachRoot(webview)
        webview.load(URLRequest(url: url))
        return webview
    }

    func updateNSView(_ webview: WKWebView, context: Context) {}

    static func dismantleNSView(_ webview: WKWebView, coordinator: Coordinator) {
        coordinator.dispose()
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(onHost: onHost, allowNavigation: allowNavigation, onCallback: onCallback)
    }

    nonisolated static func standardNavigation(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https" || url.absoluteString == "about:blank"
    }

    @MainActor final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, NSWindowDelegate {
        private struct Popup {
            let webview: WKWebView
            let window: NSWindow
        }

        static let maximumPopups = 4
        private let onHost: @MainActor (String) -> Void
        private let onCallback: @MainActor (URL) -> Void
        private let allowNavigation: (URL) -> Bool
        private let presentPopup: @MainActor (NSWindow, NSWindow?) -> Void
        private weak var root: WKWebView?
        private var popups: [ObjectIdentifier: Popup] = [:]
        private var finished = false

        var popupCount: Int { popups.count }

        init(onHost: @escaping @MainActor (String) -> Void = { _ in },
             allowNavigation: @escaping (URL) -> Bool = MetaAuthWebView.standardNavigation,
             presentPopup: @escaping @MainActor (NSWindow, NSWindow?) -> Void = Coordinator.showPopup,
             onCallback: @escaping @MainActor (URL) -> Void) {
            self.onHost = onHost
            self.onCallback = onCallback
            self.allowNavigation = allowNavigation
            self.presentPopup = presentPopup
        }

        func attachRoot(_ webview: WKWebView) {
            root = webview
            webview.navigationDelegate = self
            webview.uiDelegate = self
        }

        func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
            guard !finished, let host = webView.url?.host else { return }
            if let popup = popups[ObjectIdentifier(webView)] { popup.window.title = host + " — Meta sign-in" }
            onHost(host)
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
            decideNavigation(to: action.request.url, decision: decisionHandler)
        }

        /// Resolve WebKit's navigation decision before closing a callback's source window.
        func decideNavigation(to url: URL?, decision: @MainActor (WKNavigationActionPolicy) -> Void) {
            guard !finished, let url else { decision(.cancel); return }
            if MetaAuth.isLoginCallback(url) {
                decision(.cancel)
                complete(with: url)
            } else {
                decision(allowNavigation(url) ? .allow : .cancel)
            }
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            guard !finished, action.targetFrame == nil, let url = action.request.url else { return nil }
            if MetaAuth.isLoginCallback(url) { complete(with: url); return nil }
            guard allowNavigation(url) else { return nil }
            return makePopup(configuration: configuration, opener: webView)
        }

        func makePopup(configuration: WKWebViewConfiguration, opener: WKWebView) -> WKWebView? {
            guard !finished, popups.count < Self.maximumPopups else { return nil }
            // WebKit supplies related-view state in this exact configuration and loads the request
            // itself after this view is returned. Replacing the configuration or loading twice
            // breaks the opener/session relationship used by authentication pages.
            let webview = WKWebView(frame: .zero, configuration: configuration)
            webview.navigationDelegate = self
            webview.uiDelegate = self
            let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 640, height: 620),
                                  styleMask: [.titled, .closable, .miniaturizable, .resizable],
                                  backing: .buffered, defer: false)
            window.title = "Meta sign-in"
            window.isReleasedWhenClosed = false
            window.delegate = self
            window.contentView = webview
            popups[ObjectIdentifier(webview)] = Popup(webview: webview, window: window)
            presentPopup(window, opener.window ?? root?.window)
            return webview
        }

        func webViewDidClose(_ webView: WKWebView) {
            closePopup(ObjectIdentifier(webView))
        }

        func windowWillClose(_ notification: Notification) {
            guard let window = notification.object as? NSWindow,
                  let id = popups.first(where: { $0.value.window === window })?.key else { return }
            closePopup(id, alreadyClosing: true)
        }

        func dispose() {
            finished = true
            root?.stopLoading()
            root?.navigationDelegate = nil
            root?.uiDelegate = nil
            root = nil
            closeAllPopups()
        }

        private func complete(with url: URL) {
            guard !finished else { return }
            finished = true
            root?.stopLoading()
            closeAllPopups()
            onCallback(url)
        }

        private func closePopup(_ id: ObjectIdentifier, alreadyClosing: Bool = false) {
            guard let popup = popups.removeValue(forKey: id) else { return }
            release(popup, closeWindow: !alreadyClosing)
        }

        private func closeAllPopups() {
            let current = Array(popups.values)
            popups.removeAll()
            for popup in current { release(popup, closeWindow: true) }
        }

        private func release(_ popup: Popup, closeWindow: Bool) {
            popup.window.delegate = nil
            popup.window.parent?.removeChildWindow(popup.window)
            popup.webview.stopLoading()
            popup.webview.navigationDelegate = nil
            popup.webview.uiDelegate = nil
            popup.window.contentView = nil
            if closeWindow { popup.window.close() }
        }

        private static func showPopup(_ window: NSWindow, parent: NSWindow?) {
            window.center()
            parent?.addChildWindow(window, ordered: .above)
            window.makeKeyAndOrderFront(nil)
        }
    }
}
