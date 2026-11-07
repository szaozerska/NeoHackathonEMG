import Foundation
import Testing
@testable import Kinesis

private func authDiagnostic(_ body: String, status: Int = 400,
                            step: MetaAuth.Step = .decryptBlob) throws -> String {
    var failure: Error?
    do {
        _ = try MetaAuth.responseJSON(data: Data(body.utf8), status: status, step: step)
    } catch {
        failure = error
    }
    let error = try #require(failure as? MetaAuthError)
    return error.localizedDescription
}

@Suite("Meta sign-in diagnostics")
struct MetaAuthDiagnosticsTests {
    @Test(arguments: ["fb-viewapp://frl_login?token=fixture&blob=fixture",
                      "oculus://frl_login/?token=fixture&blob=fixture"])
    func acceptsDocumentedCustomSchemeCallbacks(text: String) throws {
        #expect(MetaAuth.isLoginCallback(try #require(URL(string: text))))
    }

    @Test(arguments: ["https://auth.meta.com/frl_login?token=fixture&blob=fixture",
                      "https://auth.meta.com/?redirect=fb-viewapp://frl_login",
                      "fb-viewapp://other/frl_login", "fb-viewapp://frl_login/extra",
                      "fb-viewapp://user@frl_login", "fb-viewapp://frl_login:443",
                      "fb-viewapp://frl_login#fragment"])
    func doesNotTreatIntermediatePagesAsAuthenticationCallbacks(text: String) throws {
        #expect(!MetaAuth.isLoginCallback(try #require(URL(string: text))))
    }

    @Test func stagesHaveDistinctUserFacingLabels() {
        #expect(MetaAuth.Step.tokensQuery.label == "opening sign-in")
        #expect(MetaAuth.Step.decryptBlob.label == "confirming browser sign-in")
        #expect(MetaAuth.Step.accountLogin.label == "creating the band account session")
        #expect(Set(MetaAuth.Step.allCases.map(\.label)).count == 3)
    }

    @Test(arguments: MetaAuth.Step.allCases)
    func httpFailureIdentifiesItsStageAndNumericGraphCodes(step: MetaAuth.Step) throws {
        let message = try authDiagnostic(#"{"error":{"code":190,"error_subcode":463}}"#, step: step)
        #expect(message.contains(step.label))
        #expect(message.contains("400"))
        #expect(message.contains("190"))
        #expect(message.contains("463"))
    }

    @Test func nonJSONHTTPFailureKeepsTheStageWithoutShowingTheBody() throws {
        let message = try authDiagnostic("<html>fixture-response-private-marker</html>",
                                         step: .accountLogin)
        #expect(message.contains(MetaAuth.Step.accountLogin.label))
        #expect(message.contains("400"))
        #expect(!message.contains("fixture-response-private-marker"))
        #expect(!message.contains("<html>"))
    }

    @Test(arguments: ["not-json", "[]", "null", "\"fixture-string-response\""])
    func malformedSuccessPayloadIsAStageSpecificFailure(body: String) throws {
        let message = try authDiagnostic(body, status: 200, step: .tokensQuery)
        #expect(message.contains(MetaAuth.Step.tokensQuery.label))
        #expect(message.contains("200"))
        #expect(!message.contains("fixture-string-response"))
    }

    @Test func graphErrorInHTTPSuccessStillFails() throws {
        let message = try authDiagnostic(#"{"error":{"code":100,"error_subcode":4221}}"#,
                                         status: 200, step: .accountLogin)
        #expect(message.contains(MetaAuth.Step.accountLogin.label))
        #expect(message.contains("200"))
        #expect(message.contains("100"))
        #expect(message.contains("4221"))
    }

    @Test func successfulDictionaryIsReturnedWithoutChangingItsValues() throws {
        let result = try MetaAuth.responseJSON(
            data: Data(#"{"access_token":"fixture-token","user_id":"fixture-user","count":7}"#.utf8),
            status: 200, step: .accountLogin)
        #expect(result["access_token"] as? String == "fixture-token")
        #expect(result["user_id"] as? String == "fixture-user")
        #expect(result["count"] as? Int == 7)
    }

    @Test(arguments: [
        #"{"error":{"code":"190","error_subcode":"463"}}"#,
        #"{"error":{"code":true,"error_subcode":false}}"#,
        #"{"error":{"code":190.5,"error_subcode":463.5}}"#,
        #"{"error":{"code":null,"error_subcode":null}}"#,
        #"{"error":{"code":{},"error_subcode":[]}}"#,
        #"{"error":{"code":2147483648,"error_subcode":-2147483648}}"#,
        #"{"error":{"code":1e100,"error_subcode":-1e100}}"#,
    ])
    func diagnosticDoesNotCoerceOrDisplayUnboundedCodes(body: String) throws {
        let baseline = try authDiagnostic(#"{"error":{}}"#)
        let message = try authDiagnostic(body)
        #expect(message == baseline)
    }

    @Test func boundedSignedIntegerCodesAreRetained() throws {
        let message = try authDiagnostic(#"{"error":{"code":2147483647,"error_subcode":-2147483647}}"#)
        #expect(message.contains("2147483647"))
        #expect(message.contains("-2147483647"))
    }

    @Test func arbitraryFailureFieldsNeverReachTheDiagnostic() throws {
        let body = #"{"error":{"code":190,"error_subcode":463,"message":"fixture-message-private","error_user_msg":"fixture-user-message-private","type":"fixture-type-private","fbtrace_id":"fixture-trace-private","url":"https://example.invalid/?access_token=fixture-url-private"},"access_token":"fixture-token-private","blob":"fixture-blob-private","phone":"fixture-phone-private","email":"fixture-email-private","user_id":"fixture-user-private"}"#
        let message = try authDiagnostic(body)
        #expect(message.contains("190"))
        #expect(message.contains("463"))
        #expect(!message.contains("fixture-"))
        #expect(!message.contains("example.invalid"))
        #expect(!message.contains("access_token"))
        #expect(!message.contains("fbtrace_id"))
    }

    @Test(arguments: [#"{"error":"fixture-private-error"}"#,
                      #"{"error":["fixture-private-error"]}"#,
                      #"{"error":true}"#])
    func unexpectedGraphErrorShapesRemainGeneric(body: String) throws {
        let message = try authDiagnostic(body, status: 200)
        #expect(message.contains(MetaAuth.Step.decryptBlob.label))
        #expect(message.contains("200"))
        #expect(!message.contains("fixture-private-error"))
    }
}
