import Testing
@testable import KinesisCore

@Suite("Phone scroll motion")
struct PhoneScrollMotionTests {
    @Test func flickIsDistributedAndConservesDistance() {
        var motion = PhoneScrollMotion()
        motion.flick(direction: -1, distance: 48, at: 100)
        var steps: [Int] = []
        for frame in 1...40 {
            let amount = motion.step(at: 100 + Double(frame) * 0.025)
            if amount != 0 { steps.append(amount); motion.commit(amount) }
        }
        #expect(steps.reduce(0, +) == -48)
        #expect(steps.count > 12 && steps.allSatisfy { (-8 ... -1).contains($0) })
        #expect(!motion.isActive)
        #expect(steps.prefix(5).reduce(0, +) < steps.suffix(5).reduce(0, +))
    }

    @Test func reversalReplacesUnsentMovementAndStopClearsIt() {
        var motion = PhoneScrollMotion()
        motion.flick(direction: 1, distance: 48, at: 10)
        let first = motion.step(at: 10.025)
        motion.commit(first)
        motion.flick(direction: -1, distance: 48, at: 10.04)
        #expect(motion.step(at: 10.065) < 0)
        motion.stop()
        #expect(motion.step(at: 10.08) == 0)
    }

    @Test func stallDropsPendingTravelInsteadOfCatchingUp() {
        var motion = PhoneScrollMotion()
        motion.flick(direction: 1, distance: 120, at: 10)
        #expect(motion.step(at: 10.2) == 0)
        #expect(!motion.isActive)
        #expect(motion.step(at: 10.21) == 0)
    }

    @Test func busyTransportDoesNotConsumeOrAccumulateUnboundedMovement() {
        var motion = PhoneScrollMotion()
        motion.flick(direction: 1, distance: 48, at: 10)
        // No commit: a busy transport has sent no output.
        for frame in 1...5 { #expect(motion.step(at: 10 + Double(frame) * 0.025) <= 8) }
        var sum = 0
        for frame in 6...40 {
            let amount = motion.step(at: 10 + Double(frame) * 0.025)
            sum += amount
            motion.commit(amount)
        }
        #expect(sum == 48 && !motion.isActive)
    }

    @Test func repeatedFlicksReplaceTravelAndInvalidTimeCancels() {
        var motion = PhoneScrollMotion()
        for frame in 0...10 { motion.flick(direction: 1, distance: 120, at: 10 + Double(frame) * 0.01) }
        var sum = 0
        for frame in 1...55 {
            let amount = motion.step(at: 10.1 + Double(frame) * 0.025)
            #expect(amount <= 8)
            sum += amount
            motion.commit(amount)
        }
        #expect(sum == 120)
        motion.flick(direction: 1, distance: 48, at: .nan)
        #expect(!motion.isActive)
    }

    @Test func sameDirectionFlickAfterPartialTravelStartsExactlyTheConfiguredDistance() {
        var motion = PhoneScrollMotion()
        motion.flick(direction: 1, distance: 48, at: 10)
        let first = motion.step(at: 10.025)
        motion.commit(first)
        #expect(first > 0 && first < 48)
        motion.flick(direction: 1, distance: 48, at: 10.04)
        var replacementTotal = 0
        for frame in 1...40 {
            let amount = motion.step(at: 10.04 + Double(frame) * 0.025)
            replacementTotal += amount
            motion.commit(amount)
        }
        #expect(replacementTotal == 48)
        #expect(!motion.isActive)
        // A later completed gesture has exactly the same distance.
        motion.flick(direction: 1, distance: 48, at: 12)
        var nextTotal = 0
        for frame in 1...40 {
            let amount = motion.step(at: 12 + Double(frame) * 0.025)
            nextTotal += amount
            motion.commit(amount)
        }
        #expect(nextTotal == replacementTotal)
    }

    @Test func minimumDistanceRespondsOnFirstNormalTickAndCommitsExactlyOneUnit() {
        for interval in [0.02, 0.025] {
            for direction in [-1, 1] {
                var motion = PhoneScrollMotion()
                motion.flick(direction: direction, distance: 1, at: 10)
                #expect(motion.step(at: 10) == 0)
                let first = motion.step(at: 10 + interval)
                #expect(first == direction)
                // A busy transport does not consume the proposed unit.
                let retry = motion.step(at: 10 + interval * 2)
                #expect(retry == direction)
                motion.commit(retry)
                #expect(!motion.isActive)
                #expect(motion.step(at: 10 + interval * 3) == 0)
            }
        }
    }

    @Test func distanceClampsToOneUnitInsteadOfTheOldTwelveUnitMinimum() {
        var motion = PhoneScrollMotion()
        motion.flick(direction: -1, distance: 0, at: 10)
        let amount = motion.step(at: 10.02)
        #expect(amount == -1)
        motion.commit(amount)
        #expect(!motion.isActive)
    }
}
