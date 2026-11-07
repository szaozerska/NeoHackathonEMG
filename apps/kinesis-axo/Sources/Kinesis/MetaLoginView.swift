import KinesisCore
import SwiftUI

/// The Meta sign-in sheet. It first says what is about to happen and why.
/// Nothing contacts Meta until the person continues. It then runs the tokens
/// query, opens the validated auth.meta.com entry page, intercepts the
/// fb-viewapp://frl_login callback, and exchanges the blob for the ar session.
struct MetaLoginView: View {
    var onSession: (MetaSession) -> Void
    var onCancel: () -> Void
    /// Keeps the already-sanitized failure visible after this sheet is closed.
    var onFailure: (String?) -> Void = { _ in }
    enum Phase { case intro, querying, signingIn, exchanging, failed }
    @State private var phase: Phase = .intro
    @State private var error: String?
    @State private var tokens: MetaAuth.SSOTokens?
    @State private var host = "auth.meta.com"
    @State private var attempt = UUID()
    @State private var task: Task<Void, Never>?

    var body: some View {
        VStack(spacing: 0) {
            if phase == .intro { intro } else { signIn }
        }
        .frame(width: 640, height: 620)
        .background(KinesisStyle.paper).foregroundStyle(KinesisStyle.ink)
        .onDisappear { invalidateAttempt() }
    }

    private var intro: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("sign in with meta").font(.system(size: 34)).tracking(-1.3)
            Text("your band is tied to your meta account, so kinesis needs it once to claim the band for this Mac.")
                .font(.system(size: 14)).foregroundStyle(KinesisStyle.secondary).lineSpacing(5)
                .fixedSize(horizontal: false, vertical: true).padding(.top, 14)
            VStack(alignment: .leading, spacing: 26) {
                promise("lock.shield", "you sign in on meta’s page",
                        "kinesis opens auth.meta.com. it gets a session token back, not your password.")
                promise("key", "token lives in your keychain",
                        "kinesis uses it to claim your band. forget this band removes it.")
                promise("arrow.uturn.backward", "your band stays on your account",
                        "a factory reset undoes all of this: \(OwnershipCeremony.factoryResetHint).")
            }.frame(maxWidth: .infinity, alignment: .leading).padding(.top, 34)
            Spacer(minLength: 0)
            HStack(spacing: 14) {
                Spacer()
                Button("not now") { cancelSignIn() }.buttonStyle(.plain)
                    .font(.system(size: 12)).foregroundStyle(KinesisStyle.secondary)
                Button { begin() } label: {
                    HStack(spacing: 22) {
                        Text("continue to meta")
                        Image(systemName: "arrow.right")
                    }
                }.buttonStyle(KinesisButtonStyle(prominent: true)).keyboardShortcut(.defaultAction)
            }
        }.padding(.horizontal, 44).padding(.top, 44).padding(.bottom, 32)
    }

    private func promise(_ symbol: String, _ title: String, _ detail: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: symbol).font(.system(size: 17, weight: .light)).frame(width: 24)
                .foregroundStyle(KinesisStyle.secondary)
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.system(size: 13, weight: .medium))
                Text(detail).font(.system(size: 12)).foregroundStyle(KinesisStyle.secondary)
                    .lineSpacing(3).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var signIn: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                // The page's real host, so it is plain where the password goes.
                Image(systemName: "lock.fill").font(.system(size: 10))
                Text(host).font(.system(size: 12, weight: .medium))
                Spacer()
                Button("cancel") { cancelSignIn() }
                    .buttonStyle(.plain).font(.system(size: 12)).foregroundStyle(KinesisStyle.secondary)
            }.foregroundStyle(KinesisStyle.secondary)
                .padding(.horizontal, 22).padding(.vertical, 14)
                .overlay(alignment: .bottom) { Rectangle().fill(KinesisStyle.line).frame(height: 1) }
            ZStack {
                switch phase {
                case .intro: EmptyView()
                case .querying: waiting("opening meta’s sign-in…")
                case .signingIn:
                    if let url = tokens?.authEntryURL {
                        MetaAuthWebView(url: url, onHost: { [current = attempt] value in
                            guard attempt == current else { return }
                            host = value
                        }) { [current = attempt] callback in
                            guard attempt == current else { return }
                            handleCallback(callback)
                        }
                    }
                case .exchanging: waiting("finishing the sign-in…")
                case .failed: waiting("sign-in didn’t finish. try again to start a fresh session.")
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            if let error {
                HStack {
                    ErrorNote(text: error)
                    Spacer()
                    if phase == .querying || phase == .failed {
                        Button("try again") { begin() }.buttonStyle(KinesisButtonStyle())
                    }
                }.padding(.horizontal, 22).padding(.vertical, 12)
            }
        }
    }

    private func waiting(_ text: String) -> some View {
        VStack(spacing: 14) {
            if error == nil { ProgressView().controlSize(.regular) }
            Text(text).font(.system(size: 12)).foregroundStyle(KinesisStyle.secondary)
        }
    }

    private func begin() {
        invalidateAttempt()
        let current = attempt
        error = nil
        onFailure(nil)
        tokens = nil
        host = "auth.meta.com"
        phase = .querying
        task = Task {
            do {
                let result = try await MetaAuth.tokensQuery()
                guard !Task.isCancelled, attempt == current else { return }
                tokens = result
                phase = .signingIn
            } catch {
                guard !Task.isCancelled, attempt == current else { return }
                self.error = error.localizedDescription
                onFailure(self.error)
                tokens = nil
                phase = .failed
            }
        }
    }

    private func invalidateAttempt() {
        task?.cancel()
        task = nil
        attempt = UUID()
        tokens = nil
    }

    private func cancelSignIn() {
        invalidateAttempt()
        onCancel()
    }

    private func handleCallback(_ url: URL) {
        guard phase == .signingIn, let tokens else { return }
        guard MetaAuth.isLoginCallback(url) else {
            error = "meta returned an unexpected sign-in redirect. try again."
            onFailure(error)
            self.tokens = nil
            phase = .failed
            return
        }
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let token = items.first(where: { $0.name == "token" })?.value
        let blob = items.first(where: { $0.name == "blob" })?.value
        guard let blob, !blob.isEmpty, MetaAuth.callbackMatches(token, nativeSSOToken: tokens.nativeSSOToken) else {
            error = "meta didn't confirm this sign-in. try again."
            onFailure(error)
            self.tokens = nil
            phase = .failed
            return
        }
        phase = .exchanging
        let current = attempt
        task = Task {
            do {
                let frl = try await MetaAuth.decryptBlob(blob, requestToken: tokens.nativeSSOToken)
                guard !Task.isCancelled, attempt == current else { return }
                let session = try await MetaAuth.login(frlAccessToken: frl)
                guard !Task.isCancelled, attempt == current else { return }
                onSession(session)
            } catch {
                guard !Task.isCancelled, attempt == current else { return }
                self.error = error.localizedDescription
                onFailure(self.error)
                self.tokens = nil
                phase = .failed
            }
        }
    }
}
