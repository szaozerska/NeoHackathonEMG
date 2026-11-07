import Foundation
import Testing
import KinesisCore
@testable import Kinesis

private struct ChatGPTApplicationIdentity: Sendable {
    let name: String
    let url: URL
    let identifier: String?
    let bundleName: String?
    let displayName: String?
    let accepted: Bool
}

@MainActor private func chatGPTApplicationFixture(in directory: URL, name: String = "ChatGPT.app",
                                                 identifier: String = "com.openai.codex",
                                                 bundleName: String = "ChatGPT") throws -> URL {
    let app = directory.appendingPathComponent(name, isDirectory: true)
    let contents = app.appendingPathComponent("Contents", isDirectory: true)
    try FileManager.default.createDirectory(at: contents.appendingPathComponent("MacOS", isDirectory: true),
                                            withIntermediateDirectories: true)
    let metadata = ["CFBundleIdentifier": identifier, "CFBundleName": bundleName,
                    "CFBundlePackageType": "APPL", "CFBundleExecutable": "ChatGPT"]
    let data = try PropertyListSerialization.data(fromPropertyList: metadata, format: .xml, options: 0)
    try data.write(to: contents.appendingPathComponent("Info.plist"))
    // The fixture is never launched; an empty resource makes its bundle layout
    // realistic without providing an executable program or posting any events.
    try Data().write(to: contents.appendingPathComponent("MacOS/ChatGPT"))
    return app
}

@Suite("ChatGPT application identity")
struct ChatGPTApplicationTests {
    private static let identities: [ChatGPTApplicationIdentity] = [
        .init(name: "current ChatGPT", url: URL(fileURLWithPath: "/Applications/ChatGPT.app"),
              identifier: "com.openai.codex", bundleName: "ChatGPT", displayName: nil, accepted: true),
        .init(name: "legacy ChatGPT", url: URL(fileURLWithPath: "/Applications/ChatGPT.app"),
              identifier: "com.openai.chat", bundleName: "ChatGPT", displayName: nil, accepted: true),
        .init(name: "display name", url: URL(fileURLWithPath: "/Applications/ChatGPT.app"),
              identifier: "com.openai.codex", bundleName: nil, displayName: "ChatGPT", accepted: true),
        .init(name: "shared Codex identifier", url: URL(fileURLWithPath: "/Applications/Codex.app"),
              identifier: "com.openai.codex", bundleName: "Codex", displayName: "Codex", accepted: false),
        .init(name: "misleading app filename", url: URL(fileURLWithPath: "/Applications/Codex.app"),
              identifier: "com.openai.codex", bundleName: "ChatGPT", displayName: "ChatGPT", accepted: false),
        .init(name: "misleading metadata", url: URL(fileURLWithPath: "/Applications/ChatGPT.app"),
              identifier: "com.openai.codex", bundleName: "Codex", displayName: "Codex", accepted: false),
        .init(name: "unrelated identifier", url: URL(fileURLWithPath: "/Applications/ChatGPT.app"),
              identifier: "example.other.app", bundleName: "ChatGPT", displayName: "ChatGPT", accepted: false),
        .init(name: "missing identifier", url: URL(fileURLWithPath: "/Applications/ChatGPT.app"),
              identifier: nil, bundleName: "ChatGPT", displayName: "ChatGPT", accepted: false),
        .init(name: "missing names", url: URL(fileURLWithPath: "/Applications/ChatGPT.app"),
              identifier: "com.openai.codex", bundleName: nil, displayName: nil, accepted: false),
        .init(name: "remote URL", url: URL(string: "https://example.invalid/ChatGPT.app")!,
              identifier: "com.openai.codex", bundleName: "ChatGPT", displayName: "ChatGPT", accepted: false),
    ]

    @Test(arguments: identities) @MainActor
    private func chatGPTIdentityRequiresAFileBundleNameAndSupportedIdentifier(identity: ChatGPTApplicationIdentity) {
        let result = MacShortcuts.isChatGPTApplication(bundleURL: identity.url,
            bundleIdentifier: identity.identifier, bundleName: identity.bundleName, displayName: identity.displayName)
        #expect(result == identity.accepted)
    }

    @Test @MainActor func chatGPTResolverSkipsAnUnrelatedBundleAndSelectsALaterValidCandidate() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("kinesis-chatgpt-validation-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let unrelated = try chatGPTApplicationFixture(in: directory.appendingPathComponent("wrong"),
            identifier: "example.other.app")
        let codex = try chatGPTApplicationFixture(in: directory.appendingPathComponent("codex"),
            name: "Codex.app", bundleName: "Codex")
        let chatGPT = try chatGPTApplicationFixture(in: directory.appendingPathComponent("valid"))
        let expected = chatGPT.standardizedFileURL.resolvingSymlinksInPath()
        #expect(MacShortcuts.validatedChatGPTApplicationURL(unrelated) == nil)
        #expect(MacShortcuts.validatedChatGPTApplicationURL(codex) == nil)
        #expect(MacShortcuts.resolveChatGPTApplicationURL(candidates: [unrelated, codex, chatGPT]) == expected)
        #expect(MacShortcuts.resolveChatGPTApplicationURL(candidates: [unrelated, codex]) == nil)
    }

    @Test @MainActor func chatGPTValidationChecksTheCanonicalBundleBehindASymlink() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("kinesis-chatgpt-symlink-validation-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let codex = try chatGPTApplicationFixture(in: directory.appendingPathComponent("codex"),
            name: "Codex.app", bundleName: "ChatGPT")
        let chatGPT = try chatGPTApplicationFixture(in: directory.appendingPathComponent("valid"),
            identifier: "com.openai.chat")
        let falseAliasDirectory = directory.appendingPathComponent("misleading", isDirectory: true)
        try FileManager.default.createDirectory(at: falseAliasDirectory, withIntermediateDirectories: true)
        let falseAlias = falseAliasDirectory.appendingPathComponent("ChatGPT.app", isDirectory: true)
        try FileManager.default.createSymbolicLink(at: falseAlias, withDestinationURL: codex)
        #expect(MacShortcuts.validatedChatGPTApplicationURL(falseAlias) == nil)

        let validAlias = directory.appendingPathComponent("ChatGPT.app", isDirectory: true)
        try FileManager.default.createSymbolicLink(at: validAlias, withDestinationURL: chatGPT)
        let expected = chatGPT.standardizedFileURL.resolvingSymlinksInPath()
        #expect(MacShortcuts.validatedChatGPTApplicationURL(validAlias) == expected)
        #expect(MacShortcuts.resolveChatGPTApplicationURL(candidates: [falseAlias, validAlias]) == expected)
    }

    @Test @MainActor func chatGPTValidationRejectsMissingAndNonFileBundles() {
        let missing = FileManager.default.temporaryDirectory
            .appendingPathComponent("missing-chatgpt-\(UUID().uuidString)/ChatGPT.app", isDirectory: true)
        #expect(MacShortcuts.validatedChatGPTApplicationURL(missing) == nil)
        #expect(MacShortcuts.validatedChatGPTApplicationURL(URL(string: "https://example.invalid/ChatGPT.app")!) == nil)
        #expect(MacShortcuts.resolveChatGPTApplicationURL(candidates: []) == nil)
    }

    @Test(arguments: [
        "codex://threads/11111111-2222-4333-8444-555555555555",
        "codex://threads/11111111-2222-4333-8444-555555555555?hostId=durable",
        "codex://threads/11111111-2222-4333-8444-555555555555?hostId=local",
    ])
    func chatGPTConversationURLAcceptsOnlyAThreadLinkWithAnOptionalHost(link: String) throws {
        let url = try #require(ChatGPTDestination.conversationURL(from: link))
        #expect(url.absoluteString == link)
    }

    @Test(arguments: [
        "",
        "https://example.invalid/threads/11111111-2222-4333-8444-555555555555",
        "codex://dots/11111111-2222-4333-8444-555555555555",
        "codex://threads/not-a-thread-id",
        "codex://threads/11111111-2222-4333-8444-555555555555/extra",
        "codex://threads/11111111-2222-4333-8444-555555555555/",
        "codex://user@threads/11111111-2222-4333-8444-555555555555",
        "codex://threads:123/11111111-2222-4333-8444-555555555555",
        "codex://threads/11111111-2222-4333-8444-555555555555#other",
        "codex://threads/11111111-2222-4333-8444-555555555555?other=durable",
        "codex://threads/11111111-2222-4333-8444-555555555555?hostId=durable&hostId=local",
        "codex://threads/11111111-2222-4333-8444-555555555555?hostId=durable&other=1",
        "codex://threads/11111111-2222-4333-8444-555555555555?hostId=",
    ])
    func chatGPTConversationURLRejectsUnrelatedOrAmbiguousNavigation(link: String) {
        #expect(ChatGPTDestination.conversationURL(from: link) == nil)
    }
}
