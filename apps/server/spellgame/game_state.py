"""Game simulation (architecture.md §2.3), kept free of networking so it can be tested with fake inputs.

The server calls `GameState.step(inputs, dt)` once per tick and broadcasts the returned events plus `snapshot()`.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from . import protocol as p
from .geometry import body_forward, normalize, segment_distance, vec


@dataclass
class Tuning:
    max_hp: float = 100.0
    body_radius: float = 0.2
    """Players are hit-tested as one capsule from head to hips."""
    torso_length: float = 0.65
    """Head-to-hips distance used when the pose has no hips joint."""

    velocity_window_s: float = 0.04
    hand_history_s: float = 0.3

    fireball_damage: float = 8.0
    """100 HP / 8 is about 13 hits, roughly a minute of steady fireball exchange."""
    fireball_radius: float = 0.15
    fireball_lifetime_s: float = 4.0
    fireball_hold_timeout_s: float = 8.0
    fireball_cooldown_s: float = 0.75
    throw_min_hand_speed: float = 2.5
    """m/s. Slower hand movement never releases a held fireball."""
    throw_min_forward: float = 0.3
    """Minimum cosine between the hand velocity and the thrower's facing, so the backswing doesn't throw."""
    throw_release_ratio: float = 0.85
    """Release once hand speed falls below this fraction of its peak (the peak velocity is the throw)."""
    throw_release_timeout_s: float = 0.15
    throw_speed_scale: float = 2.0
    throw_min_speed: float = 6.0
    throw_max_speed: float = 10.0
    """m/s. Slow enough to see, dodge or block across a 3-5 m room (about 0.4-0.7 s in flight)."""
    aim_assist_cone_deg: float = 20.0
    aim_assist_strength: float = 0.5
    """0 disables aim assist; 1 snaps throws within the cone straight at the opponent's chest."""


@dataclass
class PlayerInput:
    """Latest inputs for one player, written by the network layer between ticks."""

    pose: p.Pose | None = None
    sign: str = p.Sign.NONE
    hand: str = p.Hand.RIGHT
    """The hand wearing the Neural Band; all gestures are performed with it."""
    snapped: bool = False
    """A snap started since the previous tick. The network layer sets it; the server clears it after `step`."""
    band_paired: bool = False
    connected: bool = True


class Item:
    NONE = "none"
    FIREBALL = "fireball"


class HandTracker:
    """Short position history for one hand, used to estimate velocity when the headset doesn't send it."""

    def __init__(self, tuning: Tuning) -> None:
        self._tuning = tuning
        self._samples: deque[tuple[float, np.ndarray]] = deque()
        self._reported_velocity: np.ndarray | None = None

    def add(self, t: float, joint: p.Joint) -> None:
        if self._samples and t <= self._samples[-1][0]:
            return
        self._samples.append((t, vec(joint.pos)))
        self._reported_velocity = vec(joint.vel) if joint.vel is not None else None
        while self._samples and t - self._samples[0][0] > self._tuning.hand_history_s:
            self._samples.popleft()

    @property
    def position(self) -> np.ndarray | None:
        return self._samples[-1][1] if self._samples else None

    def velocity(self) -> np.ndarray | None:
        if self._reported_velocity is not None:
            return self._reported_velocity
        if len(self._samples) < 2:
            return None
        t_new, p_new = self._samples[-1]
        t_old, p_old = self._samples[-2]
        for t_sample, p_sample in reversed(self._samples):
            t_old, p_old = t_sample, p_sample
            if t_new - t_sample >= self._tuning.velocity_window_s:
                break
        return (p_new - p_old) / (t_new - t_old)


@dataclass
class PlayerState:
    player_id: str
    hp: float
    hands: dict[str, HandTracker]
    pose: p.Pose | None = None
    connected: bool = True
    band_paired: bool = False
    sign: str = p.Sign.NONE
    band_hand: str = p.Hand.RIGHT
    item: str = Item.NONE
    item_since: float = 0.0
    cooldown_until: float = 0.0
    throw_peak: np.ndarray | None = None
    throw_peak_time: float = 0.0

    @property
    def alive(self) -> bool:
        return self.hp > 0.0

    @property
    def band_hand_tracker(self) -> HandTracker:
        return self.hands[self.band_hand]

    def body_capsule(self, tuning: Tuning) -> tuple[np.ndarray, np.ndarray] | None:
        if self.pose is None:
            return None
        joints = self.pose.joints
        top_joint = joints.get("head") or joints.get("chest")
        if top_joint is None:
            return None
        top = vec(top_joint.pos)
        bottom = vec(joints["hips"].pos) if "hips" in joints else top - np.array([0.0, tuning.torso_length, 0.0])
        return top, bottom

    def chest_position(self) -> np.ndarray | None:
        if self.pose is None:
            return None
        joint = self.pose.joints.get("chest") or self.pose.joints.get("head")
        return vec(joint.pos) if joint else None


@dataclass
class Projectile:
    id: int
    kind: str
    owner_id: str
    pos: np.ndarray
    vel: np.ndarray
    born: float


@dataclass
class GameState:
    tuning: Tuning = field(default_factory=Tuning)
    time: float = 0.0
    tick: int = 0
    players: dict[str, PlayerState] = field(default_factory=dict)
    projectiles: list[Projectile] = field(default_factory=list)
    _next_projectile_id: int = 1

    def add_player(self, player_id: str) -> PlayerState:
        if player_id not in self.players:
            hands = {p.Hand.LEFT: HandTracker(self.tuning), p.Hand.RIGHT: HandTracker(self.tuning)}
            self.players[player_id] = PlayerState(player_id=player_id, hp=self.tuning.max_hp, hands=hands)
        return self.players[player_id]

    def step(self, inputs: Mapping[str, PlayerInput], dt: float) -> list[p.Message]:
        self.time += dt
        self.tick += 1
        events: list[p.Message] = []
        for player_id, player_input in inputs.items():
            events.extend(self._apply_input(self.add_player(player_id), player_input))
        for player in self.players.values():
            events.extend(self._step_fireball(player))
        events.extend(self._step_projectiles(dt))
        return events

    def snapshot(self) -> p.State:
        return p.State(
            tick=self.tick,
            players=[
                p.PlayerSnapshot(
                    player_id=player.player_id,
                    hp=player.hp,
                    connected=player.connected,
                    band_paired=player.band_paired,
                    sign=player.sign,
                    item=player.item,
                    band_hand=player.band_hand,
                    cooldown=round(max(0.0, player.cooldown_until - self.time), 3),
                )
                for player in self.players.values()
            ],
            projectiles=[
                p.ProjectileSnapshot(
                    id=projectile.id,
                    kind=projectile.kind,
                    owner_id=projectile.owner_id,
                    pos=_round(projectile.pos),
                    vel=_round(projectile.vel),
                )
                for projectile in self.projectiles
            ],
        )

    def _apply_input(self, player: PlayerState, player_input: PlayerInput) -> list[p.Message]:
        player.connected = player_input.connected
        player.band_paired = player_input.band_paired
        player.sign = player_input.sign
        player.band_hand = player_input.hand if player_input.hand in player.hands else p.Hand.RIGHT
        if player_input.pose is not None:
            player.pose = player_input.pose
            for hand, joint_name in ((p.Hand.LEFT, "l_hand"), (p.Hand.RIGHT, "r_hand")):
                joint = player_input.pose.joints.get(joint_name)
                if joint is not None:
                    player.hands[hand].add(player_input.pose.t, joint)
        if player_input.snapped:
            return self._on_snap(player)
        return []

    def _on_snap(self, player: PlayerState) -> list[p.Message]:
        if not player.alive or not player.connected or player.item != Item.NONE or self.time < player.cooldown_until:
            return []
        player.item = Item.FIREBALL
        player.item_since = self.time
        player.throw_peak = None
        return [self._spell_event(player, p.SpellState.CHARGING, None)]

    def _step_fireball(self, player: PlayerState) -> list[p.Message]:
        events: list[p.Message] = []
        if player.item != Item.FIREBALL:
            return events
        if (
            not player.alive
            or not player.connected
            or self.time - player.item_since > self.tuning.fireball_hold_timeout_s
        ):
            player.item = Item.NONE
            events.append(self._spell_event(player, p.SpellState.CANCELLED, None))
            return events

        throw_velocity = self._detect_throw(player)
        if throw_velocity is not None:
            events.append(self._throw_fireball(player, throw_velocity))
        return events

    def _detect_throw(self, player: PlayerState) -> np.ndarray | None:
        tuning = self.tuning
        velocity = player.band_hand_tracker.velocity()
        if velocity is None or player.pose is None:
            return None
        speed = float(np.linalg.norm(velocity))
        forwardness = float(normalize(velocity) @ body_forward(player.pose.joints))
        fast_and_forward = speed >= tuning.throw_min_hand_speed and forwardness >= tuning.throw_min_forward

        peak = player.throw_peak
        if fast_and_forward and (peak is None or speed > float(np.linalg.norm(peak))):
            player.throw_peak, player.throw_peak_time = velocity, self.time
            return None
        if peak is None:
            return None
        released = (
            not fast_and_forward
            or speed < tuning.throw_release_ratio * float(np.linalg.norm(peak))
            or self.time - player.throw_peak_time >= tuning.throw_release_timeout_s
        )
        return peak if released else None

    def _throw_fireball(self, player: PlayerState, hand_velocity: np.ndarray) -> p.Spell:
        tuning = self.tuning
        direction = self._aim_assist(player, normalize(hand_velocity))
        speed = float(
            np.clip(
                np.linalg.norm(hand_velocity) * tuning.throw_speed_scale, tuning.throw_min_speed, tuning.throw_max_speed
            )
        )
        origin = player.band_hand_tracker.position
        assert origin is not None
        self.projectiles.append(
            Projectile(
                id=self._next_projectile_id,
                kind=Item.FIREBALL,
                owner_id=player.player_id,
                pos=origin.copy(),
                vel=direction * speed,
                born=self.time,
            )
        )
        self._next_projectile_id += 1
        player.item = Item.NONE
        player.throw_peak = None
        player.cooldown_until = self.time + tuning.fireball_cooldown_s
        return self._spell_event(player, p.SpellState.CAST, direction)

    def _aim_assist(self, player: PlayerState, direction: np.ndarray) -> np.ndarray:
        tuning = self.tuning
        origin = player.band_hand_tracker.position
        if tuning.aim_assist_strength <= 0.0 or origin is None:
            return direction
        min_cosine = np.cos(np.radians(tuning.aim_assist_cone_deg))
        best: tuple[float, np.ndarray] | None = None
        for target in self._targets(player.player_id):
            chest = target.chest_position()
            if chest is None:
                continue
            to_target = normalize(chest - origin)
            cosine = float(direction @ to_target)
            if cosine >= min_cosine and (best is None or cosine > best[0]):
                best = (cosine, to_target)
        if best is None:
            return direction
        return normalize(direction + (best[1] - direction) * tuning.aim_assist_strength)

    def _step_projectiles(self, dt: float) -> list[p.Message]:
        tuning = self.tuning
        events: list[p.Message] = []
        remaining: list[Projectile] = []
        for projectile in self.projectiles:
            start, end = projectile.pos, projectile.pos + projectile.vel * dt
            target = self._first_hit(projectile, start, end)
            if target is not None:
                target.hp = max(0.0, target.hp - tuning.fireball_damage)
                events.append(
                    p.Damage(
                        target_id=target.player_id,
                        source_id=projectile.owner_id,
                        amount=tuning.fireball_damage,
                        hp_after=target.hp,
                    )
                )
                events.append(self._impact(projectile, end, "hit", target.player_id))
            elif self.time - projectile.born >= tuning.fireball_lifetime_s:
                events.append(self._impact(projectile, end, "expired", None))
            else:
                projectile.pos = end
                remaining.append(projectile)
        self.projectiles = remaining
        return events

    def _first_hit(self, projectile: Projectile, start: np.ndarray, end: np.ndarray) -> PlayerState | None:
        reach = self.tuning.fireball_radius + self.tuning.body_radius
        for target in self._targets(projectile.owner_id):
            capsule = target.body_capsule(self.tuning)
            if capsule is not None and segment_distance(start, end, *capsule) <= reach:
                return target
        return None

    def _targets(self, attacker_id: str) -> list[PlayerState]:
        return [
            player
            for player in self.players.values()
            if player.player_id != attacker_id and player.alive and player.connected
        ]

    def _spell_event(self, player: PlayerState, state: str, direction: np.ndarray | None) -> p.Spell:
        origin = player.band_hand_tracker.position
        return p.Spell(
            caster_id=player.player_id,
            spell=Item.FIREBALL,
            state=state,
            charge=1.0,
            origin=_round(origin) if origin is not None else None,
            direction=_round(direction) if direction is not None else None,
        )

    def _impact(self, projectile: Projectile, pos: np.ndarray, reason: str, target_id: str | None) -> p.Impact:
        return p.Impact(
            projectile_id=projectile.id,
            kind=projectile.kind,
            owner_id=projectile.owner_id,
            pos=_round(pos),
            reason=reason,
            target_id=target_id,
        )


def _round(values: np.ndarray) -> list[float]:
    return [round(float(v), 4) for v in values]
