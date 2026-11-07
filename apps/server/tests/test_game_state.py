import numpy as np
import pytest

from spellgame import protocol as p
from spellgame.game_state import GameState, Item, PlayerInput, Projectile, Tuning
from spellgame.sim import THROW_DURATION_S, standing_pose, throw_hand_offset

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

    def step(self, p1_hand=None, p1_facing=0.0, snap=False):
        self.t += DT
        self.inputs["P1"].pose = standing_pose("P1", self.t, (0.0, 0.0), p1_facing, p1_hand)
        self.inputs["P2"].pose = standing_pose("P2", self.t, self.p2_position, 180.0)
        self.inputs["P1"].snapped = snap
        events = self.game.step(self.inputs, DT)
        self.inputs["P1"].snapped = False
        return events

    def run(self, seconds, **kwargs):
        events = []
        for _ in range(round(seconds / DT)):
            events += self.step(**kwargs)
        return events

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
    hp_after = match.game.tuning.max_hp - match.game.tuning.fireball_damage
    assert [(d.target_id, d.source_id, d.hp_after) for d in of_type(events, p.Damage)] == [("P2", "P1", hp_after)]
    assert [(i.reason, i.target_id) for i in of_type(events, p.Impact)] == [("hit", "P2")]
    assert match.p2.hp == hp_after
    assert not match.game.projectiles


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

    events = match.run(match.game.tuning.fireball_lifetime_s + 0.1, p1_facing=90.0)
    assert not of_type(events, p.Damage)
    assert [i.reason for i in of_type(events, p.Impact)] == ["expired"]
    assert match.p2.hp == match.game.tuning.max_hp


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
    assert match.p1.throw_peak == pytest.approx([0.0, 0.0, 6.0])


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
