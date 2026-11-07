import Foundation

public enum ChatGPTDestination: String, CaseIterable, Identifiable, Sendable {
    case currentChat, myDot

    public var id: String { rawValue }
    public var title: String {
        switch self {
        case .currentChat: "Current chat"
        case .myDot: "My Dot"
        }
    }

    /// Accepts only a copied conversation route, without prompt or navigation
    /// parameters. An empty setting is handled separately as the account's Dot.
    public static func conversationURL(from text: String) -> URL? {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.hasPrefix("codex://threads/"),
              let components = URLComponents(string: value),
              components.scheme == "codex", components.host == "threads",
              components.user == nil, components.password == nil, components.port == nil,
              components.fragment == nil else { return nil }
        let identifier = String(components.percentEncodedPath.dropFirst())
        guard identifier.count == 36, UUID(uuidString: identifier) != nil else { return nil }
        if let query = components.percentEncodedQuery {
            guard let items = components.queryItems, items.count == 1,
                  items[0].name == "hostId", let host = items[0].value,
                  let first = host.first, first.isLetter || first.isNumber,
                  host.count <= 128 else { return nil }
            let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
            guard host.unicodeScalars.allSatisfy({ allowed.contains($0) }),
                  query == "hostId=\(host)" else { return nil }
        }
        return components.url
    }
}
