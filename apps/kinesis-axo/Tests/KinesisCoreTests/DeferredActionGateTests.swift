import Testing
@testable import KinesisCore

@Test func deferredActionRetainsOriginalFreshEnqueueTimestampDuringIntentionalDelay() {
    var immediate = ActionGate()
    immediate.arm(at: 100)
    let allowed1 = immediate.allows(eventTime: 100, now: 100.5, live: true, trusted: true)
    #expect(!allowed1)

    var deferred = ActionGate()
    deferred.arm(at: 100)
    let allowed2 = deferred.allowsDeferred(eventTime: 100, queuedAt: 100.1, now: 100.5,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(allowed2)
}

@Test func deferredActionRejectsInputThatWasAlreadyStaleOrTooFarInTheFutureWhenQueued() {
    for (eventTime, queuedAt) in [(0.0, 0.351), (0.101, 0.0)] {
        var gate = ActionGate()
        gate.arm(at: -1)
        let allowed3 = gate.allowsDeferred(eventTime: eventTime, queuedAt: queuedAt, now: queuedAt + 0.4,
            maximumDelay: 0.75, live: true, trusted: true)
        #expect(!allowed3)
    }
    for (eventTime, queuedAt) in [(0.0, 0.35), (0.1, 0.0)] {
        var gate = ActionGate()
        gate.arm(at: -1)
        let allowed4 = gate.allowsDeferred(eventTime: eventTime, queuedAt: queuedAt, now: queuedAt + 0.4,
            maximumDelay: 0.75, live: true, trusted: true)
        #expect(allowed4)
    }
}

@Test func deferredActionRequiresBothSourceAndEnqueueAfterTheCurrentArming() {
    var gate = ActionGate()
    let allowed5 = gate.allowsDeferred(eventTime: 10, queuedAt: 10.1, now: 10.5,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(!allowed5)
    gate.arm(at: 10)
    let allowed6 = gate.allowsDeferred(eventTime: 9.99, queuedAt: 10.1, now: 10.5,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(!allowed6)
    let allowed7 = gate.allowsDeferred(eventTime: 10, queuedAt: 9.99, now: 10.5,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(!allowed7)
    let allowed8 = gate.allowsDeferred(eventTime: 10.1, queuedAt: 10.2, now: 10.6,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(allowed8)
    gate.pause()
    let allowed9 = gate.allowsDeferred(eventTime: 10.7, queuedAt: 10.8, now: 11.2,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(!allowed9)
    gate.arm(at: 11)
    let allowed10 = gate.allowsDeferred(eventTime: 10.9, queuedAt: 11.1, now: 11.5,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(!allowed10)
    let allowed11 = gate.allowsDeferred(eventTime: 11.1, queuedAt: 11.2, now: 11.6,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(allowed11)
}

@Test func deferredActionRejectsLateOrBackwardCallbacksAndRequiresAPositiveBudget() {
    for (queuedAt, now, maximumDelay) in [(1.0, 1.751, 0.75), (1.0, 0.99, 0.75),
                                          (1.0, 1.0, 0.0), (1.0, 1.0, -0.75)] {
        var gate = ActionGate()
        gate.arm(at: 0)
        let allowed12 = gate.allowsDeferred(eventTime: 1, queuedAt: queuedAt, now: now,
            maximumDelay: maximumDelay, live: true, trusted: true)
        #expect(!allowed12)
    }
    var gate = ActionGate()
    gate.arm(at: 0)
    let allowed13 = gate.allowsDeferred(eventTime: 0, queuedAt: 0, now: 0.75,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(allowed13)
}

@Test func deferredActionRequiresCurrentLiveConnectionAndPermissionWithoutConsumingCooldown() {
    var gate = ActionGate()
    gate.arm(at: 0)
    for (live, trusted) in [(false, false), (false, true), (true, false)] {
        let allowed14 = gate.allowsDeferred(eventTime: 1, queuedAt: 1.1, now: 1.5,
            maximumDelay: 0.75, live: live, trusted: trusted)
        #expect(!allowed14)
    }
    let allowed15 = gate.allowsDeferred(eventTime: 1, queuedAt: 1.1, now: 1.5,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(allowed15)
}

@Test func immediateAndDeferredActionsShareOneDispatchCooldown() {
    var gate = ActionGate(minimumInterval: 0.5)
    gate.arm(at: 0)
    let allowed16 = gate.allows(eventTime: 1, now: 1, live: true, trusted: true)
    #expect(allowed16)
    let allowed17 = gate.allowsDeferred(eventTime: 1.1, queuedAt: 1.125, now: 1.375,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(!allowed17)
    let allowed18 = gate.allowsDeferred(eventTime: 1.25, queuedAt: 1.25, now: 1.5,
        maximumDelay: 0.75, live: true, trusted: true)
    #expect(allowed18)
    let allowed19 = gate.allows(eventTime: 1.75, now: 1.75, live: true, trusted: true)
    #expect(!allowed19)
    let allowed20 = gate.allows(eventTime: 2, now: 2, live: true, trusted: true)
    #expect(allowed20)
}

@Test func deferredActionRejectsEveryNonfiniteTimestampOrBudgetWithoutDispatching() {
    for invalid in [Double.nan, Double.infinity, -Double.infinity] {
        let inputs = [(invalid, 1.1, 1.5, 0.75), (1.0, invalid, 1.5, 0.75),
                      (1.0, 1.1, invalid, 0.75), (1.0, 1.1, 1.5, invalid)]
        for (eventTime, queuedAt, now, maximumDelay) in inputs {
            var gate = ActionGate()
            gate.arm(at: 0)
            let allowed21 = gate.allowsDeferred(eventTime: eventTime, queuedAt: queuedAt, now: now,
                maximumDelay: maximumDelay, live: true, trusted: true)
            #expect(!allowed21)
            let allowed22 = gate.allowsDeferred(eventTime: 1, queuedAt: 1.1, now: 1.5,
                maximumDelay: 0.75, live: true, trusted: true)
            #expect(allowed22)
        }
    }
}
