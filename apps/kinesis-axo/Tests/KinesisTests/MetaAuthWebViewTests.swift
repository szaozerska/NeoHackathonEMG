import AppKit
import Foundation
import Testing
import WebKit
@testable import Kinesis

@MainActor private func privateAuthWebView() -> WKWebView {
    _ = NSApplication.shared
    let configuration = WKWebViewConfiguration()
    configuration.websiteDataStore = .nonPersistent()
    return WKWebView(frame: .zero, configuration: configuration)
}

@Suite("Meta sign-in pop-ups", .serialized) @MainActor
struct MetaAuthWebViewTests {
    @Test func productionNavigationKeepsHTTPAndLocalFilesOutOfSignIn() throws {
        for text in ["https://auth.meta.com/", "https://www.facebook.com/", "about:blank"] {
            #expect(MetaAuthWebView.standardNavigation(try #require(URL(string: text))))
        }
        for text in ["http://auth.meta.com/", "http://127.0.0.1:8899/", "file:///tmp/fixture",
                     "javascript:alert(1)", "data:text/html,fixture", "fb-viewapp://other/frl_login"] {
            #expect(!MetaAuthWebView.standardNavigation(try #require(URL(string: text))))
        }
    }

    @Test func aPopupKeepsWebKitsProvidedPrivateConfiguration() throws {
        let root = privateAuthWebView()
        var windows: [NSWindow] = []
        let coordinator = MetaAuthWebView.Coordinator(presentPopup: { window, _ in windows.append(window) },
                                                       onCallback: { _ in })
        coordinator.attachRoot(root)
        defer { coordinator.dispose() }
        let provided = WKWebViewConfiguration()
        provided.websiteDataStore = root.configuration.websiteDataStore
        let child = try #require(coordinator.makePopup(configuration: provided, opener: root))
        #expect(child !== root)
        #expect(child.configuration.websiteDataStore === provided.websiteDataStore)
        #expect(!child.configuration.websiteDataStore.isPersistent)
        #expect(child.configuration.userContentController === provided.userContentController)
        #expect(child.navigationDelegate === coordinator)
        #expect(child.uiDelegate === coordinator)
        #expect(coordinator.popupCount == 1)
        #expect(windows.count == 1)
        #expect(windows.first?.contentView === child)
        #expect(windows.first?.isReleasedWhenClosed == false)
        #expect(root.url == nil)
        #expect(child.url == nil)
    }

    @Test func callbackCancelsNavigationBeforeClosingPopupsAndCompletesOnce() throws {
        let root = privateAuthWebView()
        var events: [String] = []
        var windows: [NSWindow] = []
        let callback = try #require(URL(string: "fb-viewapp://frl_login?token=fixture&blob=fixture"))
        let coordinator = MetaAuthWebView.Coordinator(presentPopup: { window, _ in windows.append(window) },
                                                       onCallback: { url in
            #expect(url == callback)
            events.append("callback")
        })
        coordinator.attachRoot(root)
        let first = try #require(coordinator.makePopup(configuration: root.configuration, opener: root))
        let second = try #require(coordinator.makePopup(configuration: first.configuration, opener: first))
        coordinator.decideNavigation(to: callback) { policy in
            events.append(policy == .cancel ? "cancel" : "allow")
        }
        #expect(events == ["cancel", "callback"])
        #expect(coordinator.popupCount == 0)
        #expect(first.navigationDelegate == nil && first.uiDelegate == nil)
        #expect(second.navigationDelegate == nil && second.uiDelegate == nil)
        #expect(windows.allSatisfy { $0.contentView == nil && $0.delegate == nil })
        coordinator.decideNavigation(to: callback) { policy in
            events.append(policy == .cancel ? "cancel" : "allow")
        }
        #expect(events == ["cancel", "callback", "cancel"])
        #expect(coordinator.makePopup(configuration: root.configuration, opener: root) == nil)
        coordinator.dispose()
    }

    @Test func ordinaryHTTPSContainingTheCallbackNameDoesNotCompleteSignIn() throws {
        let root = privateAuthWebView()
        var callbacks = 0
        let coordinator = MetaAuthWebView.Coordinator(presentPopup: { _, _ in }, onCallback: { _ in callbacks += 1 })
        coordinator.attachRoot(root)
        defer { coordinator.dispose() }
        let url = try #require(URL(string: "https://auth.meta.com/?redirect=fb-viewapp://frl_login"))
        var decision: WKNavigationActionPolicy?
        coordinator.decideNavigation(to: url) { decision = $0 }
        #expect(decision == .allow)
        #expect(callbacks == 0)
        coordinator.decideNavigation(to: nil) { decision = $0 }
        #expect(decision == .cancel)
        #expect(callbacks == 0)
    }

    @Test func javascriptCloseAndDisposalReleaseOwnedWindows() throws {
        let root = privateAuthWebView()
        var callbacks = 0
        var windows: [NSWindow] = []
        let coordinator = MetaAuthWebView.Coordinator(presentPopup: { window, _ in windows.append(window) },
                                                       onCallback: { _ in callbacks += 1 })
        coordinator.attachRoot(root)
        let first = try #require(coordinator.makePopup(configuration: root.configuration, opener: root))
        coordinator.webViewDidClose(first)
        #expect(coordinator.popupCount == 0)
        #expect(first.navigationDelegate == nil && first.uiDelegate == nil)
        #expect(windows.first?.contentView == nil)
        _ = try #require(coordinator.makePopup(configuration: root.configuration, opener: root))
        coordinator.dispose()
        coordinator.dispose()
        #expect(coordinator.popupCount == 0)
        #expect(root.navigationDelegate == nil && root.uiDelegate == nil)
        #expect(windows.allSatisfy { $0.contentView == nil && $0.delegate == nil })
        let callback = try #require(URL(string: "oculus://frl_login/?token=fixture&blob=fixture"))
        var decision: WKNavigationActionPolicy?
        coordinator.decideNavigation(to: callback) { decision = $0 }
        #expect(decision == .cancel)
        #expect(callbacks == 0)
    }

    @Test func boundedPopupCountReleasesCapacityWhenAChildCloses() throws {
        let root = privateAuthWebView()
        let coordinator = MetaAuthWebView.Coordinator(presentPopup: { _, _ in }, onCallback: { _ in })
        coordinator.attachRoot(root)
        defer { coordinator.dispose() }
        var children: [WKWebView] = []
        for _ in 0..<MetaAuthWebView.Coordinator.maximumPopups {
            children.append(try #require(coordinator.makePopup(configuration: root.configuration, opener: root)))
        }
        #expect(coordinator.popupCount == MetaAuthWebView.Coordinator.maximumPopups)
        #expect(coordinator.makePopup(configuration: root.configuration, opener: root) == nil)
        coordinator.webViewDidClose(try #require(children.first))
        #expect(coordinator.popupCount == MetaAuthWebView.Coordinator.maximumPopups - 1)
        _ = try #require(coordinator.makePopup(configuration: root.configuration, opener: root))
        #expect(coordinator.popupCount == MetaAuthWebView.Coordinator.maximumPopups)
    }

    @Test func aLocalFixturePolicyDoesNotBroadenTheProductionDefault() throws {
        let fixture = try #require(URL(string: "http://127.0.0.1:8899/popup?scheme=fb-viewapp"))
        let coordinator = MetaAuthWebView.Coordinator(allowNavigation: { url in
            MetaAuthWebView.standardNavigation(url)
                || (url.scheme == "http" && url.host == "127.0.0.1" && url.port == 8899)
        }, presentPopup: { _, _ in }, onCallback: { _ in })
        var decision: WKNavigationActionPolicy?
        coordinator.decideNavigation(to: fixture) { decision = $0 }
        #expect(decision == .allow)
        #expect(!MetaAuthWebView.standardNavigation(fixture))
        coordinator.dispose()
    }
}
