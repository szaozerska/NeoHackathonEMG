import Foundation
import Testing
@testable import KinesisCore

@Suite("Phone navigation reports and arming")
struct PhoneNavigationTests {
    private let bindings: [RecognizedGesture: PhoneNavigationAction] = [
        .swipe(.right): .key(PhoneKeyboardChord(.tab)),
        .tap(.indexTap): .activate,
    ]

    private func gesture(_ sequence: UInt64 = 1, at time: Double = 100.1,
                         action: String = "right", derived: String = "unknown",
                         finger: String = "thumb", synthetic: Bool = false) -> BandGesture {
        BandGesture(sequence: sequence, timestampUs: sequence * 1_000, finger: finger,
                    action: action, derivedAction: derived, synthetic: synthetic, receivedAt: time)
    }

    @Test func keyboardChordsProduceOnePressFollowedByAllKeysReleased() {
        let action = PhoneNavigationAction.key(PhoneKeyboardChord(.tab, modifiers: [.command, .shift]))
        #expect(action.reports.map(\.kind) == [.keyboard, .keyboard])
        #expect(action.reports.map(\.bytes) == [Data([0x0a, 0, 0x2b, 0, 0, 0, 0, 0]), Data(repeating: 0, count: 8)])
        #expect(PhoneNavigationAction.activate.reports.first?.bytes == Data([0, 0, 0x2c, 0, 0, 0, 0, 0]))
    }

    @Test func navigationUsesHIDUsagesRatherThanMacVirtualKeys() {
        let expected: [PhoneNavigationKey: UInt8] = [
            .enter: 0x28, .escape: 0x29, .tab: 0x2b, .space: 0x2c,
            .home: 0x4a, .pageUp: 0x4b, .end: 0x4d, .pageDown: 0x4e,
            .right: 0x4f, .left: 0x50, .down: 0x51, .up: 0x52,
            .f13: 0x68, .f14: 0x69,
        ]
        for key in PhoneNavigationKey.allCases {
            #expect(PhoneNavigationAction.key(PhoneKeyboardChord(key)).reports[0].bytes[2] == expected[key])
        }
        #expect(PhoneKeyboardModifiers.control.rawValue == 0x01)
        #expect(PhoneKeyboardModifiers.shift.rawValue == 0x02)
        #expect(PhoneKeyboardModifiers.option.rawValue == 0x04)
        #expect(PhoneKeyboardModifiers.command.rawValue == 0x08)
    }

    @Test func scrollHasBoundedSignedWheelsAndNoPointerOrButtonMovement() throws {
        let scroll = try #require(PhoneScroll(vertical: -127, horizontal: 127))
        let reports = PhoneNavigationAction.scroll(scroll).reports
        #expect(reports.map(\.kind) == [.mouse])
        #expect(reports.map(\.bytes) == [Data([0, 0, 0, 0x81, 0x7f])])
        let horizontal = try #require(PhoneScroll(vertical: 0, horizontal: -1))
        #expect(PhoneNavigationAction.scroll(horizontal).reports[0].bytes == Data([0, 0, 0, 0, 0xff]))
    }

    @Test(arguments: [Int.min, -128, 128, Int.max])
    func rejectsOutOfRangeScrollWithoutClampingOrOverflow(value: Int) {
        #expect(PhoneScroll(vertical: value) == nil)
        #expect(PhoneScroll(vertical: 1, horizontal: value) == nil)
        #expect(PhoneScroll(vertical: 0) == nil)
    }

    @Test func pointerMovementHasBoundedSignedAxesAndNoClickOrScroll() throws {
        let movement = try #require(PhonePointerMove(dx: -127, dy: 127))
        let reports = PhoneNavigationAction.move(movement).reports
        #expect(reports.map(\.kind) == [.mouse])
        #expect(reports.map(\.bytes) == [Data([0, 0x81, 0x7f, 0, 0])])
        let down = try #require(PhonePointerMove(dx: 0, dy: 1))
        #expect(PhoneNavigationAction.move(down).reports[0].bytes == Data([0, 0, 1, 0, 0]))
        #expect(PhonePointerMove(dx: 0, dy: 0) == nil)
    }

    @Test func leftClickAlwaysReleasesWithoutMovementOrWheelReports() {
        let reports = PhoneNavigationAction.click.reports
        #expect(reports.map(\.kind) == [.mouse, .mouse])
        #expect(reports.map(\.bytes) == [Data([1, 0, 0, 0, 0]), Data(repeating: 0, count: 5)])
        #expect(reports.allSatisfy { $0.bytes.dropFirst().allSatisfy { $0 == 0 } })
    }

    @Test(arguments: [Int.min, -128, 128, Int.max])
    func rejectsOutOfRangePointerMovementWithoutClampingOrOverflow(value: Int) {
        #expect(PhonePointerMove(dx: value, dy: 1) == nil)
        #expect(PhonePointerMove(dx: 1, dy: value) == nil)
    }

    @Test func outputRequiresExplicitArmingAndExplicitMapping() {
        var session = PhoneNavigationSession()
        #expect(!session.isArmed)
        #expect(session.reports(for: gesture(), bindings: bindings, at: 100.1).isEmpty)
        #expect(session.arm(at: 100) == true)
        #expect(session.reports(for: gesture(), bindings: [:], at: 100.1).isEmpty)
        // An event seen while unassigned is not replayed when a mapping changes.
        #expect(session.reports(for: gesture(), bindings: bindings, at: 100.1).isEmpty)
        #expect(session.reports(for: gesture(2, at: 100.2), bindings: bindings, at: 100.2)
            == PhoneNavigationAction.key(PhoneKeyboardChord(.tab)).reports)
    }

    @Test func realFreshGestureIsRecognizedOnceAcrossRawAndDerivedMessages() {
        var session = PhoneNavigationSession()
        session.arm(at: 100)
        #expect(!session.reports(for: gesture(), bindings: bindings, at: 100.1).isEmpty)
        #expect(session.reports(for: gesture(), bindings: bindings, at: 100.11).isEmpty)
        let derived = gesture(2, at: 100.12, action: "unknown", derived: "buttonRight")
        #expect(session.reports(for: derived, bindings: bindings, at: 100.12).isEmpty)
        #expect(!session.reports(for: gesture(3, at: 100.4), bindings: bindings, at: 100.4).isEmpty)
    }

    @Test func syntheticPartialAndUnassignedGesturesCannotProduceReports() {
        var session = PhoneNavigationSession()
        session.arm(at: 100)
        #expect(session.reports(for: gesture(synthetic: true), bindings: bindings, at: 100.1).isEmpty)
        #expect(session.reports(for: gesture(2, at: 100.2, action: "partialRight"), bindings: bindings, at: 100.2).isEmpty)
        #expect(session.reports(for: gesture(3, at: 100.3, action: "left"), bindings: bindings, at: 100.3).isEmpty)
        let tap = gesture(4, at: 100.4, action: "tap", finger: "index")
        #expect(session.reports(for: tap, bindings: bindings, at: 100.4) == PhoneNavigationAction.activate.reports)
    }

    @Test func delayedFutureAndPreArmEventsAreRejectedAtTheWriteBoundary() {
        var session = PhoneNavigationSession()
        session.arm(at: 100)
        #expect(session.reports(for: gesture(at: 99.99), bindings: bindings, at: 100.1).isEmpty)
        #expect(session.reports(for: gesture(2, at: 100), bindings: bindings, at: 100.1).isEmpty)
        #expect(session.reports(for: gesture(3, at: 101), bindings: bindings, at: 100.1).isEmpty)
        #expect(session.reports(for: gesture(4, at: 100.1), bindings: bindings, at: 100.451).isEmpty)
        #expect(!session.reports(for: gesture(5, at: 100.5), bindings: bindings, at: 100.6).isEmpty)
    }

    @Test(arguments: [Double.nan, .infinity, -.infinity, -1])
    func nonfiniteAndNegativeTimesCannotArmOrDispatch(value: Double) {
        var session = PhoneNavigationSession()
        #expect(session.arm(at: value) == false)
        #expect(!session.isArmed)
        session.arm(at: 100)
        #expect(session.reports(for: gesture(at: value), bindings: bindings, at: 100.1).isEmpty)
        #expect(session.reports(for: gesture(), bindings: bindings, at: value).isEmpty)
        #expect(session.arm(at: value) == false)
        #expect(!session.isArmed)
    }

    @Test func disarmReleasesBothReportKindsAndDiscardsOldInput() {
        var session = PhoneNavigationSession()
        session.arm(at: 100)
        #expect(!session.reports(for: gesture(), bindings: bindings, at: 100.1).isEmpty)
        let released = session.disarm()
        #expect(!session.isArmed)
        #expect(released.map(\.kind) == [.keyboard, .mouse])
        #expect(released.map(\.bytes) == [Data(repeating: 0, count: 8), Data(repeating: 0, count: 5)])
        #expect(session.reports(for: gesture(2, at: 100.2), bindings: bindings, at: 100.2).isEmpty)
        #expect(session.arm(at: 101) == true)
        #expect(session.reports(for: gesture(2, at: 100.2), bindings: bindings, at: 101.1).isEmpty)
        #expect(!session.reports(for: gesture(3, at: 101.2), bindings: bindings, at: 101.2).isEmpty)
    }

    @Test func reconnectRequiresRearmingAndPermitsFreshRestartedBandSequences() {
        var session = PhoneNavigationSession()
        session.arm(at: 100)
        #expect(!session.reports(for: gesture(), bindings: bindings, at: 100.1).isEmpty)
        #expect(session.connectionChanged() == PhoneHIDReport.releaseReports)
        #expect(!session.isArmed)
        #expect(session.reports(for: gesture(at: 101.1), bindings: bindings, at: 101.1).isEmpty)
        #expect(session.arm(at: 102) == true)
        #expect(session.reports(for: gesture(), bindings: bindings, at: 102).isEmpty)
        #expect(!session.reports(for: gesture(at: 102.1), bindings: bindings, at: 102.1).isEmpty)
    }

    @Test func clockRewindCannotRearmOrReplayInput() {
        var session = PhoneNavigationSession()
        session.arm(at: 100)
        #expect(!session.reports(for: gesture(at: 101), bindings: bindings, at: 101).isEmpty)
        #expect(session.reports(for: gesture(2, at: 100.5), bindings: bindings, at: 100.5).isEmpty)
        _ = session.disarm()
        #expect(session.arm(at: 100.5) == false)
        #expect(!session.isArmed)
        #expect(session.arm(at: 101) == true)
        #expect(session.reports(for: gesture(at: 101), bindings: bindings, at: 101.1).isEmpty)
    }
}
