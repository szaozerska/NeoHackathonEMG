import numpy as np
import pytest

from spellgame import protocol as p
from spellgame.game_state import GameState, Item, PlayerInput, Projectile, Tuning
from spellgame.sim import (
    HAND_IDLE,
    SWORD_DRAW_DURATION_S,
    SWORD_DRAWN_HAND,
    THROW_DURATION_S,
    standing_pose,
    sword_draw_hand_offset,
    sword_swing_hand_offset,
    throw_hand_offset,
)

DT = 1 / 60


class Match:
    """P1 at the origin facing +z, P2 three metres away facing back at P1."""

    def __init__(self, tuning: Tuning | None = None, p2_position=(0.0, 3.0)):
        self.game = GameState(tuning=tuning or Tuning(aim_assist_strength=0.0))
        self.t = 0.0
        self.p2_position = p2_position
        self.inputs = {
            "P1": PlayerInput(band_paired=True),
            "P2": PlayerInput(band_paired=True),
        }
        for player_id in self.inputs:
            self.game.add_player(player_id)

    def step(self, p1_hand=None, p1_facing=0.0, snap=False, sign=None, p2_hand=None):
        self.t += DT
        if sign is not None:
            self.inputs["P1"].sign = sign
        self.inputs["P1"].pose = standing_pose("P1", self.t, (0.0, 0.0), p1_facing, p1_hand)
        self.inputs["P2"].pose = standing_pose("P2", self.t, self.p2_position, 180.0, p2_hand)
        self.inputs["P1"].snapped = snap
        events = self.game.step(self.inputs, DT)
        self.inputs["P1"].snapped = False
        return events

    def run(self, seconds, **kwargs):
        events = []
        for _ in range(round(seconds / DT)):
            events += self.step(**kwargs)
        return events

    def motion(self, hand_offset, duration_s, **kwargs):
        events = []
        elapsed = 0.0
        while elapsed < duration_s:
            events += self.step(p1_hand=hand_offset(elapsed), **kwargs)
            elapsed += DT
        return events

    def draw_sword(self):
        self.step(p1_hand=sword_draw_hand_offset(0.0), sign=p.Sign.FIST)
        return self.motion(sword_draw_hand_offset, SWORD_DRAW_DURATION_S + 0.05)

    def throw(self, p1_facing=0.0):
        events = []
        elapsed = 0.0
        while elapsed < THROW_DURATION_S:
            events += self.step(p1_hand=throw_hand_offset(elapsed), p1_facing=p1_facing)
            elapsed += DT
        return events

    @property
    def p1(self):
        return self.game.players["P1"]

    @property
    def p2(self):
        return self.game.players["P2"]


def of_type(events, cls):
    return [event for event in events if isinstance(event, cls)]


def test_snap_conjures_a_held_fireball():
    match = Match()
    events = match.step(snap=True)

    assert match.p1.item == Item.FIREBALL
    assert [(e.caster_id, e.state) for e in of_type(events, p.Spell)] == [("P1", p.SpellState.CHARGING)]
    assert match.game.snapshot().players[0].item == Item.FIREBALL


def test_without_a_snap_a_throw_does_nothing():
    match = Match()
    events = match.throw()
    assert not match.game.projectiles
    assert not of_type(events, p.Spell)


def test_throw_launches_fireball_forward_and_hits_opponent():
    match = Match()
    match.step(snap=True)
    events = match.throw()

    cast = of_type(events, p.Spell)[-1]
    assert cast.state == p.SpellState.CAST
    assert cast.direction[2] > 0.9
    assert match.p1.item == Item.NONE

    events += match.run(1.0)
    [damage] = of_type(events, p.Damage)
    hp_after = match.game.tuning.max_hp - damage.amount
    assert damage.amount > 0
    assert (damage.target_id, damage.source_id, damage.hp_after) == ("P2", "P1", hp_after)
    assert [(i.reason, i.target_id) for i in of_type(events, p.Impact)] == [("hit", "P2")]
    assert match.p2.hp == hp_after
    assert not match.game.projectiles


def push_hand(match, speed, duration_s):
    """Snap, then move P1's hand straight forward at `speed` m/s (headset-reported) for `duration_s` and stop."""
    match.step(snap=True)
    events = []
    elapsed = 0.0
    while elapsed < duration_s + 1.0:
        match.t += DT
        pose = standing_pose("P1", match.t)
        pose.joints["r_hand"].vel = [0.0, 0.0, speed if elapsed < duration_s else 0.0]
        match.inputs["P1"].pose = pose
        match.inputs["P2"].pose = standing_pose("P2", match.t, match.p2_position, 180.0)
        events += match.game.step(match.inputs, DT)
        elapsed += DT
    return events


def test_fireball_damage_is_proportional_to_its_speed():
    [slow] = of_type(push_hand(Match(), 4.0, 0.3), p.Damage)
    [fast] = of_type(push_hand(Match(), 8.0, 0.3), p.Damage)
    assert fast.amount == pytest.approx(2 * slow.amount, abs=0.1)


def test_heavy_fireball_ignores_a_wrist_flick_but_follows_a_full_swing():
    flick = Match()
    push_hand(flick, 3.0, 0.05)
    assert flick.p1.item == Item.FIREBALL

    swing = Match()
    push_hand(swing, 8.0, 0.3)
    assert swing.p1.item == Item.NONE


def test_a_quick_overhand_throw_tracked_by_position_alone_releases():
    """Headsets send no hand velocity: a 0.2 s forward swing peaking at 5 m/s must still leave the hand."""
    match = Match()
    match.step(snap=True)
    duration, peak = 0.2, 5.0
    elapsed = 0.0
    while elapsed < duration + 0.3:
        t = min(elapsed, duration)
        forward = peak * (t / 2.0 - duration / (4.0 * np.pi) * np.sin(2.0 * np.pi * t / duration))
        match.step(p1_hand=HAND_IDLE + np.array([0.0, 0.0, forward]))
        elapsed += DT
    assert match.p1.item == Item.NONE
    assert match.game.projectiles


def test_backswing_alone_does_not_throw():
    match = Match()
    match.step(snap=True)
    elapsed = 0.0
    while elapsed < 0.4 * THROW_DURATION_S:
        match.step(p1_hand=throw_hand_offset(elapsed))
        elapsed += DT
    assert match.p1.item == Item.FIREBALL
    assert not match.game.projectiles


def test_throw_direction_follows_facing_and_misses_when_aimed_away():
    match = Match()
    match.step(snap=True)
    events = match.throw(p1_facing=90.0)
    cast = of_type(events, p.Spell)[-1]
    assert cast.direction[0] > 0.9

    events = match.run(5.0, p1_facing=90.0)
    assert not of_type(events, p.Damage)
    impacts = of_type(events, p.Impact)
    assert [i.reason for i in impacts] == ["expired"]
    assert match.p2.hp == match.game.tuning.max_hp

    flown = float(np.linalg.norm(np.array(impacts[0].pos) - np.array(cast.origin)))
    assert flown == pytest.approx(match.game.tuning.fireball_max_range_m, abs=0.05)


def test_aim_assist_bends_a_slightly_off_throw_onto_the_target():
    match = Match(tuning=Tuning(aim_assist_strength=1.0, aim_assist_cone_deg=25.0))
    match.step(snap=True)
    events = match.throw(p1_facing=15.0)
    events += match.run(1.0, p1_facing=15.0)
    assert [d.target_id for d in of_type(events, p.Damage)] == ["P2"]


def test_fireball_never_hits_its_caster():
    match = Match()
    match.step()
    match.game.projectiles.append(
        Projectile(
            id=99,
            kind=Item.FIREBALL,
            owner_id="P1",
            pos=np.array([0.0, 1.3, -0.5]),
            vel=np.array([0.0, 0.0, 4.0]),
            born=match.game.time,
        )
    )
    events = match.run(0.5)
    assert not of_type(events, p.Damage)
    assert match.game.projectiles[0].pos[2] > 0.0


def test_snap_while_holding_or_on_cooldown_is_ignored():
    match = Match()
    match.step(snap=True)
    assert len(of_type(match.step(snap=True), p.Spell)) == 0
    match.throw()
    assert match.p1.item == Item.NONE
    assert not of_type(match.step(snap=True), p.Spell)
    match.run(match.game.tuning.fireball_cooldown_s)
    assert of_type(match.step(snap=True), p.Spell)[0].state == p.SpellState.CHARGING


def test_held_fireball_fizzles_after_timeout():
    match = Match(tuning=Tuning(fireball_hold_timeout_s=0.5))
    match.step(snap=True)
    events = match.run(0.6)
    assert [e.state for e in of_type(events, p.Spell)] == [p.SpellState.CANCELLED]
    assert match.p1.item == Item.NONE


def test_headset_velocity_is_preferred_over_position_history():
    match = Match()
    match.step(snap=True)
    match.t += DT
    pose = standing_pose("P1", match.t)
    pose.joints["r_hand"].vel = [0.0, 0.0, 6.0]
    match.inputs["P1"].pose = pose
    match.game.step(match.inputs, DT)
    follow = 1.0 - np.exp(-DT / match.game.tuning.fireball_inertia_s)
    assert match.p1.held_fireball_velocity == pytest.approx([0.0, 0.0, 6.0 * follow])


def test_knocked_out_player_cannot_cast_or_be_hit():
    match = Match()
    match.p2.hp = 0.0
    match.step(snap=True)
    events = match.throw() + match.run(1.0)
    assert not of_type(events, p.Damage)
    match.inputs["P2"].snapped = True
    match.game.step(match.inputs, DT)
    assert match.p2.item == Item.NONE


def test_snapshot_reports_band_hand_and_cooldown_after_a_throw():
    match = Match()
    match.step(snap=True)
    match.throw()

    snapshot = next(pl for pl in match.game.snapshot().players if pl.player_id == "P1")
    assert snapshot.band_hand == p.Hand.RIGHT
    assert 0.0 < snapshot.cooldown <= match.game.tuning.fireball_cooldown_s


def sword_match():
    """P2 within sword reach, one metre in front of P1."""
    return Match(p2_position=(0.0, 1.0))


def test_fist_at_pocket_pulled_diagonally_draws_the_sword():
    match = sword_match()
    events = match.draw_sword()

    assert match.p1.item == Item.SWORD
    assert [(e.spell, e.state) for e in of_type(events, p.Spell)] == [(Item.SWORD, p.SpellState.CAST)]
    assert match.game.snapshot().players[0].item == Item.SWORD


def test_same_pull_without_starting_at_the_pocket_does_not_draw():
    match = sword_match()
    away = np.array([0.4, 0.3, 0.2])
    events = match.motion(lambda t: sword_draw_hand_offset(t) + away, SWORD_DRAW_DURATION_S + 0.05, sign=p.Sign.FIST)
    assert match.p1.item == Item.NONE
    assert not of_type(events, p.Spell)


def test_pull_from_pocket_without_a_fist_does_not_draw():
    match = sword_match()
    match.motion(sword_draw_hand_offset, SWORD_DRAW_DURATION_S + 0.05, sign=p.Sign.NONE)
    assert match.p1.item == Item.NONE


def test_too_slow_or_wrong_direction_pull_does_not_draw():
    slow = sword_match()
    slow.motion(lambda t: sword_draw_hand_offset(t / 6.0), 6 * SWORD_DRAW_DURATION_S, sign=p.Sign.FIST)
    assert slow.p1.item == Item.NONE

    downward = sword_match()
    start = sword_draw_hand_offset(0.0)
    downward.motion(lambda t: start + np.array([-0.4, -0.3, 0.0]) * min(t / 0.3, 1.0), 0.35, sign=p.Sign.FIST)
    assert downward.p1.item == Item.NONE


def test_releasing_the_fist_sheathes_the_sword_at_once():
    match = sword_match()
    match.draw_sword()
    events = match.step(p1_hand=SWORD_DRAWN_HAND, sign=p.Sign.NONE)

    assert match.p1.item == Item.NONE
    assert [(e.spell, e.state) for e in of_type(events, p.Spell)] == [(Item.SWORD, p.SpellState.SHEATHED)]


def test_swing_through_the_opponent_hits_once_with_speed_scaled_damage():
    match = sword_match()
    match.draw_sword()
    events = match.motion(sword_swing_hand_offset, 0.3)

    tuning = match.game.tuning
    [damage] = of_type(events, p.Damage)
    assert (damage.target_id, damage.source_id, damage.kind) == ("P2", "P1", Item.SWORD)
    assert tuning.sword_min_damage <= damage.amount <= tuning.sword_max_damage
    assert match.p2.hp == tuning.max_hp - damage.amount
    assert damage.pos is not None


def test_faster_swing_hits_harder():
    def swing_damage(duration_s):
        match = sword_match()
        match.draw_sword()
        events = match.motion(lambda t: sword_swing_hand_offset(t, duration_s), duration_s + 0.05)
        return of_type(events, p.Damage)[0].amount

    assert swing_damage(0.15) > swing_damage(0.6)


def test_blade_resting_in_the_opponent_does_no_damage():
    match = sword_match()
    match.draw_sword()
    inside_opponent = np.array([0.0, 1.25, 0.4])
    match.step(p1_hand=inside_opponent)
    events = match.run(1.0, p1_hand=inside_opponent)
    assert not of_type(events, p.Damage)


def test_swing_back_and_forth_rehits_only_after_the_cooldown():
    match = sword_match()
    match.draw_sword()
    back = lambda t: sword_swing_hand_offset(0.25 - t)  # noqa: E731
    quick = match.motion(sword_swing_hand_offset, 0.25) + match.motion(back, 0.2)
    assert len(of_type(quick, p.Damage)) == 1

    match.run(match.game.tuning.sword_rehit_s, p1_hand=sword_swing_hand_offset(0.0))
    assert len(of_type(match.motion(sword_swing_hand_offset, 0.3), p.Damage)) == 1


def test_cannot_draw_while_holding_a_fireball():
    match = sword_match()
    match.step(p1_hand=sword_draw_hand_offset(0.0), snap=True)
    events = match.draw_sword()
    assert match.p1.item != Item.SWORD
    assert not [e for e in of_type(events, p.Spell) if e.spell == Item.SWORD]


SHIELD_HAND = np.array([0.0, 1.3, 0.35])


def raise_shield(match, hand=SHIELD_HAND):
    return match.step(p1_hand=hand, sign=p.Sign.OPEN_PALM)


def incoming_fireball(match, z=2.5, speed=-6.0):
    match.game.projectiles.append(
        Projectile(
            id=7,
            kind=Item.FIREBALL,
            owner_id="P2",
            pos=np.array([0.0, 1.3, z]),
            vel=np.array([0.0, 0.0, speed]),
            born=match.game.time,
        )
    )


def give_p2_sword(match):
    match.inputs["P2"].sign = p.Sign.FIST
    match.p2.item = Item.SWORD


def test_open_palm_raises_the_shield_and_releasing_lowers_it():
    match = Match()
    events = raise_shield(match)
    assert match.p1.item == Item.SHIELD
    assert [(e.spell, e.state) for e in of_type(events, p.Spell)] == [(Item.SHIELD, p.SpellState.CAST)]

    events = match.step(p1_hand=SHIELD_HAND, sign=p.Sign.NONE)
    assert match.p1.item == Item.NONE
    assert [(e.spell, e.state) for e in of_type(events, p.Spell)] == [(Item.SHIELD, p.SpellState.SHEATHED)]


def test_raised_shield_blocks_a_fireball_from_the_front():
    match = Match()
    raise_shield(match)
    incoming_fireball(match)
    events = match.run(1.0, p1_hand=SHIELD_HAND)

    assert not of_type(events, p.Damage)
    assert [(i.reason, i.target_id) for i in of_type(events, p.Impact)] == [("blocked", "P1")]
    assert match.p1.hp == match.game.tuning.max_hp


def fireball_through_shield_held_for(seconds):
    """Damage events from a 6 m/s fireball that reaches P1's shield about `seconds` after it was raised."""
    match = Match()
    raise_shield(match)
    match.run(seconds, p1_hand=SHIELD_HAND)
    incoming_fireball(match, z=0.6)
    events = match.run(0.5, p1_hand=SHIELD_HAND)
    assert [(i.reason, i.target_id) for i in of_type(events, p.Impact)] == [("blocked", "P1")]
    return of_type(events, p.Damage)


def test_shield_fades_after_its_full_block_window():
    tuning = Tuning()
    assert not fireball_through_shield_held_for(tuning.shield_full_block_s - 0.1)

    full_damage = 6.0 * tuning.fireball_damage_per_speed
    [mid_fade] = fireball_through_shield_held_for(tuning.shield_full_block_s + tuning.shield_fade_s / 2)
    assert mid_fade.amount == pytest.approx(full_damage / 2, rel=0.1)

    [faded] = fireball_through_shield_held_for(tuning.shield_full_block_s + tuning.shield_fade_s + 0.1)
    assert (faded.target_id, faded.source_id, faded.amount, faded.zone) == ("P1", "P2", full_damage, p.Zone.ARM)


def test_snapshot_reports_shield_strength_fading_while_raised():
    match = Match()
    assert match.game.snapshot().players[0].shield_strength == 0.0

    raise_shield(match)
    assert match.game.snapshot().players[0].shield_strength == 1.0

    tuning = match.game.tuning
    match.run(tuning.shield_full_block_s + tuning.shield_fade_s / 2, p1_hand=SHIELD_HAND)
    assert match.game.snapshot().players[0].shield_strength == pytest.approx(0.5, abs=0.05)

    match.run(tuning.shield_fade_s, p1_hand=SHIELD_HAND)
    assert match.game.snapshot().players[0].shield_strength == 0.0


def test_fireball_hits_without_a_shield_or_from_behind_it():
    unshielded = Match()
    incoming_fireball(unshielded)
    assert [i.reason for i in of_type(unshielded.run(1.0, p1_hand=SHIELD_HAND), p.Impact)] == ["hit"]

    behind = Match()
    raise_shield(behind)
    incoming_fireball(behind, z=-2.0, speed=6.0)
    assert [i.reason for i in of_type(behind.run(1.0, p1_hand=SHIELD_HAND), p.Impact)] == ["hit"]


def test_forceful_push_boosts_the_shield_and_the_boost_fades():
    match = Match()
    start = np.array([0.0, 1.3, 0.15])
    raise_shield(match, start)
    match.motion(lambda t: start + np.array([0.0, 0.0, 0.3]) * min(t / 0.1, 1.0), 0.1, sign=p.Sign.OPEN_PALM)
    assert match.game.snapshot().players[0].shield_boost > 0.5

    match.run(match.game.tuning.shield_boost_decay_s + 0.05, p1_hand=start + np.array([0.0, 0.0, 0.3]))
    assert match.p1.shield_boost == 0.0


def test_gentle_push_gives_no_boost():
    match = Match()
    start = np.array([0.0, 1.3, 0.15])
    raise_shield(match, start)
    match.motion(lambda t: start + np.array([0.0, 0.0, 0.3]) * min(t, 1.0), 1.0, sign=p.Sign.OPEN_PALM)
    assert match.p1.shield_boost == 0.0


def test_raised_shield_blocks_a_sword_swing():
    match = sword_match()
    raise_shield(match)
    give_p2_sword(match)
    events = []
    elapsed = 0.0
    while elapsed < 0.3:
        events += match.step(p1_hand=SHIELD_HAND, p2_hand=sword_swing_hand_offset(elapsed))
        elapsed += DT

    assert not of_type(events, p.Damage)
    assert [(i.kind, i.reason, i.target_id) for i in of_type(events, p.Impact)] == [(Item.SWORD, "blocked", "P1")]
    assert match.p2.item == Item.SWORD


def test_boosted_push_into_a_sword_parries_it():
    match = sword_match()
    resting_blade_hand = np.array([0.0, 1.25, 0.4])
    start = np.array([0.0, 1.3, 0.2])
    raise_shield(match, start)
    give_p2_sword(match)
    match.step(p1_hand=start, p2_hand=resting_blade_hand)

    events = []
    elapsed = 0.0
    while elapsed < 0.15:
        hand = start + np.array([0.0, 0.0, 0.2]) * min(elapsed / 0.08, 1.0)
        events += match.step(p1_hand=hand, p2_hand=resting_blade_hand)
        elapsed += DT

    assert [(i.reason, i.target_id) for i in of_type(events, p.Impact)] == [("parried", "P1")]
    assert [(e.caster_id, e.spell, e.state) for e in of_type(events, p.Spell)] == [
        ("P2", Item.SWORD, p.SpellState.SHEATHED)
    ]
    assert match.p2.item == Item.NONE
    assert match.p2.sword_locked_until > match.game.time
    assert not of_type(events, p.Damage)


def test_damage_reports_the_body_part_hit():
    match = Match()
    match.step(snap=True)
    events = match.throw() + match.run(1.0)
    damage = of_type(events, p.Damage)
    assert len(damage) == 1
    assert damage[0].zone in (p.Zone.HEAD, p.Zone.TORSO, p.Zone.ARM, p.Zone.LEG)


def expand_domain(match: Match, caster: str = "P1") -> list[p.Message]:
    match.inputs[caster].domain_expanded = True
    events = match.step()
    match.inputs[caster].domain_expanded = False
    return events


def test_domain_expansion_stuns_the_opponent_until_the_streaks_land_plus_the_stun():
    match = Match()
    tuning = match.game.tuning
    events = expand_domain(match)

    domains = [e for e in events if isinstance(e, p.DomainExpansion)]
    assert domains == [p.DomainExpansion("P1", ["P2"], tuning.domain_expand_s, tuning.domain_stun_s)]
    match.inputs["P2"].sign = p.Sign.OPEN_PALM
    match.run(tuning.domain_expand_s + tuning.domain_stun_s - 0.1)
    assert match.game.players["P2"].item == Item.NONE
    match.run(0.2)
    assert match.game.players["P2"].item == Item.SHIELD


def test_domain_expansion_cancels_a_held_fireball_and_blocks_snaps():
    match = Match()
    match.inputs["P2"].snapped = True
    match.step()
    assert match.game.players["P2"].item == Item.FIREBALL

    events = expand_domain(match)
    assert any(isinstance(e, p.Spell) and e.state == p.SpellState.CANCELLED and e.caster_id == "P2" for e in events)
    match.inputs["P2"].snapped = True
    match.step()
    assert match.game.players["P2"].item == Item.NONE


def test_only_one_domain_runs_at_a_time_and_a_stunned_player_cannot_expand():
    match = Match()
    expand_domain(match)
    assert not [e for e in expand_domain(match, "P1") if isinstance(e, p.DomainExpansion)]
    assert not [e for e in expand_domain(match, "P2") if isinstance(e, p.DomainExpansion)]
