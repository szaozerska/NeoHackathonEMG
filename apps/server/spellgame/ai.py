"""The AI opponent of a solo match: a scripted player that sends poses and band signs into `GameState` like any other.

It stands in front of its target, strafes, throws fireballs on a timer with some aim error, and sometimes raises its
shield against an incoming fireball. Outside `playing` it just stands and sways (and celebrates if it won). Caught in a
domain expansion (stunned), it freezes in its last pose.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np

from . import protocol as p
from .game_state import GameState, Item, PlayerInput
from .geometry import body_forward, vec
from .sim import HAND_IDLE, THROW_DURATION_S, standing_pose, throw_hand_offset

SHIELD_HAND = np.array([0.0, 1.3, 0.35])
VICTORY_HAND = np.array([0.2, 1.95, 0.1])


@dataclass
class AiTuning:
    distance: float = 2.5
    """Metres in front of the target it stands."""
    strafe_amplitude: float = 0.6
    strafe_period_s: float = 6.0
    attack_interval_s: tuple[float, float] = (1.8, 3.2)
    first_attack_s: float = 1.5
    """Seconds into the match before its first fireball."""
    charge_hold_s: float = 0.4
    aim_error_deg: float = 8.0
    shield_chance: float = 0.45
    """Chance it blocks a given incoming fireball."""
    shield_react_distance: float = 3.0
    shield_hold_s: float = 0.4
    """How long the shield stays up after the fireball it blocked is gone."""
    fallback_target: tuple[float, float] = (0.0, 0.0)
    """Floor point it faces when its target has no pose yet."""


class AiOpponent:
    def __init__(
        self, player_id: str = p.AI_PLAYER_ID, tuning: AiTuning | None = None, rng: random.Random | None = None
    ) -> None:
        self.player_id = player_id
        self.tuning = tuning or AiTuning()
        self.rng = rng or random.Random()
        self.home = np.array([0.0, self.tuning.distance])
        self.facing_deg = 180.0
        self._attack: str | None = None
        """None, "charging" or "throwing"."""
        self._attack_started = 0.0
        self._aim_offset_deg = 0.0
        self._next_attack = math.inf
        self._shield_until = -math.inf
        self._judged: set[int] = set()
        self._blocking: set[int] = set()
        self._last_pose: p.Pose | None = None
        self._strafe_clock = 0.0
        """Seconds of strafing so far; it pauses while frozen so the AI picks up where it stopped."""
        self._last_time: float | None = None

    def place_facing(self, game: GameState, target_id: str | None) -> None:
        """Stand `distance` in front of the target, facing it, and reset the attack timer."""
        target = self._target_head(game, target_id)
        forward = np.array([0.0, 1.0])
        player = game.players.get(target_id) if target_id else None
        if player is not None and player.pose is not None:
            flat = body_forward(player.pose.joints)[[0, 2]]
            if np.linalg.norm(flat) > 1e-3:
                forward = flat / np.linalg.norm(flat)
        origin = target if target is not None else np.array(self.tuning.fallback_target)
        self.home = origin + forward * self.tuning.distance
        self.facing_deg = _yaw_towards(self.home, origin)
        self._attack = None
        self._shield_until = -math.inf
        self._judged.clear()
        self._blocking.clear()
        self._next_attack = game.time + self.tuning.first_attack_s

    def input(self, game: GameState, target_id: str | None, fighting: bool, won: bool = False) -> PlayerInput:
        now = game.time
        me = game.players.get(self.player_id)
        elapsed_since_last = 0.0 if self._last_time is None else now - self._last_time
        self._last_time = now
        if me is not None and now < me.stunned_until and self._last_pose is not None:
            self._attack = None
            return PlayerInput(pose=self._last_pose, band_paired=True, connected=True, aligned=True)

        self._strafe_clock += elapsed_since_last
        target = self._target_head(game, target_id)
        position = self.home.copy()
        if fighting:
            side = np.array([math.cos(math.radians(self.facing_deg)), -math.sin(math.radians(self.facing_deg))])
            strafe_phase = 2 * math.pi * self._strafe_clock / self.tuning.strafe_period_s
            position += side * self.tuning.strafe_amplitude * math.sin(strafe_phase)
        facing = _yaw_towards(position, target) if target is not None else self.facing_deg
        sign, snapped, hand = p.Sign.NONE, False, None
        bob = 0.02 * math.sin(2 * math.pi * now / 2.5)
        idle_hand = HAND_IDLE + np.array([0.0, bob, 0.0])

        if not fighting or me is None or not me.alive:
            self._attack = None
            hand = VICTORY_HAND if won else idle_hand
        elif self._attack == "charging":
            hand = idle_hand
            if now - self._attack_started >= self.tuning.charge_hold_s:
                self._attack, self._attack_started = "throwing", now
        elif self._attack == "throwing":
            elapsed = now - self._attack_started
            hand = throw_hand_offset(elapsed)
            facing += self._aim_offset_deg
            if elapsed >= THROW_DURATION_S:
                self._attack = None
                self._next_attack = now + self.rng.uniform(*self.tuning.attack_interval_s)
        elif self._should_shield(game, position, now):
            sign, hand = p.Sign.OPEN_PALM, SHIELD_HAND
        elif now >= self._next_attack and me.item == Item.NONE and now >= me.cooldown_until:
            sign, snapped, hand = p.Sign.SNAP, True, idle_hand
            self._attack, self._attack_started = "charging", now
            self._aim_offset_deg = self.rng.uniform(-self.tuning.aim_error_deg, self.tuning.aim_error_deg)
        else:
            hand = idle_hand

        pose = standing_pose(self.player_id, now, (float(position[0]), float(position[1])), facing, hand)
        self._last_pose = pose
        return PlayerInput(pose=pose, sign=sign, snapped=snapped, band_paired=True, connected=True, aligned=True)

    def _should_shield(self, game: GameState, position: np.ndarray, now: float) -> bool:
        me = np.array([position[0], 1.3, position[1]])
        for projectile in game.projectiles:
            if projectile.owner_id == self.player_id or projectile.kind != Item.FIREBALL:
                continue
            to_me = me - projectile.pos
            if float(np.linalg.norm(to_me)) > self.tuning.shield_react_distance or float(projectile.vel @ to_me) <= 0:
                continue
            if projectile.id not in self._judged:
                self._judged.add(projectile.id)
                if self.rng.random() < self.tuning.shield_chance:
                    self._blocking.add(projectile.id)
            if projectile.id in self._blocking:
                self._shield_until = now + self.tuning.shield_hold_s
        return now < self._shield_until

    @staticmethod
    def _target_head(game: GameState, target_id: str | None) -> np.ndarray | None:
        player = game.players.get(target_id) if target_id else None
        if player is None or player.pose is None:
            return None
        joint = player.pose.joints.get("head") or player.pose.joints.get("chest")
        return vec(joint.pos)[[0, 2]] if joint is not None else None


def _yaw_towards(origin: np.ndarray, target: np.ndarray) -> float:
    dx, dz = target - origin
    return math.degrees(math.atan2(dx, dz))
