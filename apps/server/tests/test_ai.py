import random

import numpy as np

from spellgame import protocol as p
from spellgame.ai import AiOpponent, AiTuning
from spellgame.game_state import GameState, Item, PlayerInput, Projectile
from spellgame.sim import standing_pose

DT = 1 / 30


def arena(**tuning):
    game = GameState()
    ai = AiOpponent(tuning=AiTuning(**tuning), rng=random.Random(1))
    human = PlayerInput(band_paired=True)
    human.pose = standing_pose("P1", 0.0)
    game.step({"P1": human}, DT)
    ai.place_facing(game, "P1")
    return game, ai, human


def run(game, ai, human, seconds, fighting=True):
    events = []
    for _ in range(round(seconds / DT)):
        human.pose = standing_pose("P1", game.time + DT)
        events += game.step({"P1": human, ai.player_id: ai.input(game, "P1", fighting)}, DT)
    return events


def test_ai_stands_in_front_of_its_target_facing_it():
    game, ai, _ = arena()
    assert np.allclose(ai.home, [0.0, 2.5])
    assert abs(ai.facing_deg) == 180.0


def test_ai_throws_fireballs_that_hit_a_standing_target():
    game, ai, human = arena(aim_error_deg=0.0, strafe_amplitude=0.0)
    events = run(game, ai, human, 8.0)
    casts = [e for e in events if isinstance(e, p.Spell) and e.caster_id == ai.player_id and e.state == "cast"]
    damage = [e for e in events if isinstance(e, p.Damage) and e.source_id == ai.player_id]
    assert len(casts) >= 2
    assert damage and damage[0].target_id == "P1"
    assert game.players["P1"].hp < game.tuning.max_hp


def test_ai_does_not_attack_outside_play():
    game, ai, human = arena()
    events = run(game, ai, human, 5.0, fighting=False)
    assert not [e for e in events if isinstance(e, p.Spell)]


def test_ai_raises_its_shield_against_an_incoming_fireball():
    game, ai, human = arena(shield_chance=1.0, first_attack_s=10.0)
    run(game, ai, human, 0.2)
    game.projectiles.append(
        Projectile(
            id=99,
            kind=Item.FIREBALL,
            owner_id="P1",
            pos=np.array([0.0, 1.3, 0.6]),
            vel=np.array([0.0, 0.0, 6.0]),
            born=game.time,
        )
    )
    events = run(game, ai, human, 1.0)
    assert game.players[ai.player_id].item == Item.SHIELD or any(
        isinstance(e, p.Impact) and e.reason == "blocked" for e in events
    )
    assert game.players[ai.player_id].hp == game.tuning.max_hp
