"""Game simulation (architecture.md §2.3), kept free of networking so it can be tested with fake inputs.

The server calls `GameState.step(inputs, dt)` once per tick and broadcasts the returned events plus `snapshot()`.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from . import protocol as p
from .geometry import (
    UP,
    body_forward,
    body_right,
    closest_point_on_segment,
    normalize,
    segment_disc_contact,
    segment_distance,
    vec,
)


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

    sword_pocket_offset: float = 0.15
    """The pocket is the hips moved this far toward the side opposite the band hand."""
    sword_pocket_radius: float = 0.2
    """A fist must start within this distance of the pocket for the pull to draw the sword."""
    sword_draw_min_distance: float = 0.3
    sword_draw_window_s: float = 0.6
    """The pull must cover `sword_draw_min_distance` within this time of the hand leaving the pocket."""
    sword_draw_cone_deg: float = 50.0
    """How far the pull may stray from the ideal 45-degree up-and-across diagonal."""
    sword_length: float = 0.9
    """The blade extends from the hand along the forearm (elbow to hand)."""
    sword_radius: float = 0.04
    sword_min_tip_speed: float = 2.0
    """m/s. A slower blade touches without hurting."""
    sword_full_damage_tip_speed: float = 8.0
    sword_min_damage: float = 6.0
    sword_max_damage: float = 15.0
    sword_rehit_s: float = 0.5
    """A swing hits each target at most once in this window, so one pass isn't counted every tick."""

    shield_radius: float = 0.3
    shield_offset: float = 0.08
    """The disc sits this far in front of the palm."""
    shield_push_min_speed: float = 1.0
    """m/s of hand speed along the shield normal. Slower pushes give no boost."""
    shield_push_full_speed: float = 3.0
    shield_boost_decay_s: float = 0.3
    """A full boost fades to zero over this time."""
    shield_parry_min_boost: float = 0.3
    shield_parry_lock_s: float = 1.5
    """After a parry the attacker can't draw a sword for this long."""


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
    aligned: bool = False


class Item:
    NONE = "none"
    FIREBALL = "fireball"
    SWORD = "sword"
    SHIELD = "shield"


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
    aligned: bool = False
    sign: str = p.Sign.NONE
    band_hand: str = p.Hand.RIGHT
    item: str = Item.NONE
    item_since: float = 0.0
    cooldown_until: float = 0.0
    throw_peak: np.ndarray | None = None
    throw_peak_time: float = 0.0
    draw_start: tuple[float, np.ndarray] | None = None
    """Time and hand position of the last fist sample in the pocket, while a draw is possible."""
    sword_tip: np.ndarray | None = None
    sword_hits: dict[str, float] = field(default_factory=dict)
    """Target ID to the time the sword last hit or was blocked by them."""
    sword_locked_until: float = 0.0
    shield_boost: float = 0.0

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
            events.extend(self._step_sword(player, dt))
            events.extend(self._step_shield(player, dt))
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
                    shield_boost=round(player.shield_boost, 3),
                    aligned=player.aligned,
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
        player.aligned = player_input.aligned
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
            blocked = self._shield_contact(projectile.owner_id, start, end, tuning.fireball_radius, projectile.vel)
            target = self._first_hit(projectile, start, end) if blocked is None else None
            if blocked is not None:
                shielder, contact = blocked
                events.append(self._impact(projectile, contact, "blocked", shielder.player_id))
            elif target is not None:
                events.append(self._damage(target, projectile.owner_id, tuning.fireball_damage, Item.FIREBALL, end))
                events.append(self._impact(projectile, end, "hit", target.player_id))
            elif self.time - projectile.born >= tuning.fireball_lifetime_s:
                events.append(self._impact(projectile, end, "expired", None))
            else:
                projectile.pos = end
                remaining.append(projectile)
        self.projectiles = remaining
        return events

    def _step_sword(self, player: PlayerState, dt: float) -> list[p.Message]:
        able = player.alive and player.connected and player.sign == p.Sign.FIST
        if player.item == Item.SWORD:
            return self._swing(player, dt) if able else [self._sheathe(player)]
        if not able or player.item != Item.NONE or self.time < player.sword_locked_until:
            player.draw_start = None
            return []

        hand, pocket = player.band_hand_tracker.position, self._pocket(player)
        if hand is None or pocket is None:
            return []
        if float(np.linalg.norm(hand - pocket)) <= self.tuning.sword_pocket_radius:
            player.draw_start = (self.time, hand.copy())
            return []
        if player.draw_start is None:
            return []
        start_time, start_hand = player.draw_start
        if self.time - start_time > self.tuning.sword_draw_window_s:
            player.draw_start = None
            return []
        return [self._draw_sword(player)] if self._is_draw_pull(player, hand - start_hand) else []

    def _pocket(self, player: PlayerState) -> np.ndarray | None:
        if player.pose is None or "hips" not in player.pose.joints:
            return None
        toward_band_side = body_right(player.pose.joints) * (1.0 if player.band_hand == p.Hand.RIGHT else -1.0)
        return vec(player.pose.joints["hips"].pos) - toward_band_side * self.tuning.sword_pocket_offset

    def _is_draw_pull(self, player: PlayerState, pull: np.ndarray) -> bool:
        """Up and across the body toward the band side; motion toward or away from the opponent is ignored."""
        assert player.pose is not None
        forward = body_forward(player.pose.joints)
        pull = pull - forward * float(pull @ forward)
        if float(np.linalg.norm(pull)) < self.tuning.sword_draw_min_distance:
            return False
        across = body_right(player.pose.joints) * (1.0 if player.band_hand == p.Hand.RIGHT else -1.0)
        diagonal = normalize(UP + across)
        return float(normalize(pull) @ diagonal) >= np.cos(np.radians(self.tuning.sword_draw_cone_deg))

    def _draw_sword(self, player: PlayerState) -> p.Spell:
        player.item = Item.SWORD
        player.item_since = self.time
        player.draw_start = None
        player.sword_tip = None
        player.sword_hits.clear()
        blade = self._blade(player)
        direction = normalize(blade[1] - blade[0]) if blade else None
        return self._spell_event(player, p.SpellState.CAST, direction, spell=Item.SWORD)

    def _sheathe(self, player: PlayerState) -> p.Spell:
        player.item = Item.NONE
        player.sword_tip = None
        return self._spell_event(player, p.SpellState.SHEATHED, None, spell=Item.SWORD)

    def _blade(self, player: PlayerState) -> tuple[np.ndarray, np.ndarray] | None:
        """Hilt and tip of the drawn sword."""
        hand = player.band_hand_tracker.position
        if hand is None or player.pose is None:
            return None
        side = "l" if player.band_hand == p.Hand.LEFT else "r"
        joints = player.pose.joints
        base = joints.get(f"{side}_elbow") or joints.get(f"{side}_wrist")
        direction = normalize(hand - vec(base.pos)) if base else np.zeros(3)
        if not direction.any():
            direction = body_forward(joints)
        return hand, hand + direction * self.tuning.sword_length

    def _swing(self, player: PlayerState, dt: float) -> list[p.Message]:
        tuning = self.tuning
        blade = self._blade(player)
        if blade is None:
            return []
        hilt, tip = blade
        previous_tip, player.sword_tip = player.sword_tip, tip
        if previous_tip is None or dt <= 0.0:
            return []
        tip_speed = float(np.linalg.norm(tip - previous_tip)) / dt
        fast = tip_speed >= tuning.sword_min_tip_speed

        events: list[p.Message] = []
        reach = tuning.sword_radius + tuning.body_radius
        for target in self._targets(player.player_id):
            last_hit = player.sword_hits.get(target.player_id)
            rehit_ready = last_hit is None or self.time - last_hit >= tuning.sword_rehit_s
            shield_contact = self._shield_contact_with(target, hilt, tip, tuning.sword_radius, tip - hilt)
            if shield_contact is not None:
                if target.shield_boost >= tuning.shield_parry_min_boost:
                    player.sword_locked_until = self.time + tuning.shield_parry_lock_s
                    events.append(self._sword_impact(player, shield_contact, "parried", target.player_id))
                    events.append(self._sheathe(player))
                    return events
                if fast and rehit_ready:
                    player.sword_hits[target.player_id] = self.time
                    events.append(self._sword_impact(player, shield_contact, "blocked", target.player_id))
                continue
            if not fast or not rehit_ready:
                continue
            capsule = target.body_capsule(tuning)
            if capsule is None or segment_distance(hilt, tip, *capsule) > reach:
                continue
            player.sword_hits[target.player_id] = self.time
            speed_range = tuning.sword_full_damage_tip_speed - tuning.sword_min_tip_speed
            strength = float(np.clip((tip_speed - tuning.sword_min_tip_speed) / speed_range, 0.0, 1.0))
            amount = round(tuning.sword_min_damage + (tuning.sword_max_damage - tuning.sword_min_damage) * strength, 1)
            on_body = closest_point_on_segment((hilt + tip) / 2.0, *capsule)
            contact = closest_point_on_segment(on_body, hilt, tip)
            events.append(self._damage(target, player.player_id, amount, Item.SWORD, contact))
        return events

    def _step_shield(self, player: PlayerState, dt: float) -> list[p.Message]:
        tuning = self.tuning
        player.shield_boost = max(0.0, player.shield_boost - dt / tuning.shield_boost_decay_s)
        able = player.alive and player.connected and player.sign == p.Sign.OPEN_PALM
        if player.item == Item.SHIELD and not able:
            player.item = Item.NONE
            player.shield_boost = 0.0
            return [self._spell_event(player, p.SpellState.SHEATHED, None, spell=Item.SHIELD)]
        if player.item == Item.NONE and able:
            player.item = Item.SHIELD
            player.item_since = self.time
            disc = self._shield_disc(player)
            return [self._spell_event(player, p.SpellState.CAST, disc[1] if disc else None, spell=Item.SHIELD)]
        if player.item != Item.SHIELD:
            return []

        disc, velocity = self._shield_disc(player), player.band_hand_tracker.velocity()
        if disc is not None and velocity is not None:
            push = float(velocity @ disc[1])
            speed_range = tuning.shield_push_full_speed - tuning.shield_push_min_speed
            if push >= tuning.shield_push_min_speed:
                strength = float(np.clip((push - tuning.shield_push_min_speed) / speed_range, 0.0, 1.0))
                player.shield_boost = max(player.shield_boost, strength)
        return []

    def _shield_disc(self, player: PlayerState) -> tuple[np.ndarray, np.ndarray] | None:
        """Centre and outward normal. The palm is taken to face away from the chest, through the hand."""
        if player.item != Item.SHIELD:
            return None
        hand, chest = player.band_hand_tracker.position, player.chest_position()
        if hand is None or chest is None or player.pose is None:
            return None
        normal = normalize(hand - chest)
        if not normal.any():
            normal = body_forward(player.pose.joints)
        return hand + normal * self.tuning.shield_offset, normal

    def _shield_contact_with(
        self, shielder: PlayerState, a: np.ndarray, b: np.ndarray, margin: float, incoming: np.ndarray
    ) -> np.ndarray | None:
        """Where segment a-b touches `shielder`'s raised shield from the front, or None."""
        disc = self._shield_disc(shielder)
        if disc is None:
            return None
        center, normal = disc
        if float((a - center) @ normal) < -margin or float(incoming @ normal) >= 0.0:
            return None
        return segment_disc_contact(a, b, center, normal, self.tuning.shield_radius, margin)

    def _shield_contact(
        self, attacker_id: str, a: np.ndarray, b: np.ndarray, margin: float, incoming: np.ndarray
    ) -> tuple[PlayerState, np.ndarray] | None:
        for target in self._targets(attacker_id):
            contact = self._shield_contact_with(target, a, b, margin, incoming)
            if contact is not None:
                return target, contact
        return None

    def _sword_impact(self, player: PlayerState, pos: np.ndarray, reason: str, target_id: str) -> p.Impact:
        return p.Impact(
            projectile_id=0,
            kind=Item.SWORD,
            owner_id=player.player_id,
            pos=_round(pos),
            reason=reason,
            target_id=target_id,
        )

    def _damage(self, target: PlayerState, source_id: str, amount: float, kind: str, pos: np.ndarray) -> p.Damage:
        target.hp = max(0.0, target.hp - amount)
        return p.Damage(
            target_id=target.player_id,
            source_id=source_id,
            amount=amount,
            hp_after=target.hp,
            kind=kind,
            pos=_round(pos),
        )

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

    def _spell_event(
        self, player: PlayerState, state: str, direction: np.ndarray | None, spell: str = Item.FIREBALL
    ) -> p.Spell:
        origin = player.band_hand_tracker.position
        return p.Spell(
            caster_id=player.player_id,
            spell=spell,
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
