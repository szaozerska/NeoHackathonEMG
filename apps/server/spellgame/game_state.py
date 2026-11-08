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
    body_forward,
    normalize,
    segment_disc_contact,
    vec,
)
from .hitboxes import Contact, HitboxSizes, body_contact, body_hitboxes


@dataclass
class Tuning:
    max_hp: float = 150.0
    hitboxes: HitboxSizes = field(default_factory=HitboxSizes)
    """Players are hit-tested per body part: head sphere, torso, shoulders, arms and legs."""

    velocity_window_s: float = 0.04
    hand_history_s: float = 0.3

    fireball_damage_per_speed: float = 2.0
    """Damage per m/s of fireball speed, so the slowest throw (2.5 m/s) deals 5 and a 6 m/s throw deals 12."""
    fireball_radius: float = 0.1
    """Collision radius; the drawn orb may be larger."""
    fireball_max_range_m: float = 8.0
    """A fireball that hits nothing fizzles after flying this far."""
    fireball_hold_timeout_s: float = 8.0
    fireball_cooldown_s: float = 0.75
    fireball_inertia_s: float = 0.05
    """Time constant of the held fireball following the hand: it picks up 63% of a steady hand velocity in this long,
    so a quick wrist flick barely moves it while a real throw does. Hand velocity is already smoothed by the server's
    finite difference over two ticks, so much more than this keeps ordinary 0.2 s throws below `throw_min_speed` and
    the fireball never leaves the hand."""
    throw_min_speed: float = 2.5
    """m/s of the held fireball's velocity. Slower, it never leaves the hand."""
    throw_max_speed: float = 10.0
    """Harder throws fly at this speed (0.3 s across a 3 m room), which also caps fireball damage."""
    throw_min_forward: float = 0.3
    """Minimum cosine between the held fireball's velocity and the thrower's facing, so the backswing doesn't throw."""
    aim_assist_cone_deg: float = 20.0
    aim_assist_strength: float = 0.5
    """0 disables aim assist; 1 snaps throws within the cone straight at the opponent's chest."""

    sword_length: float = 0.9
    """The blade extends from the hand along the forearm (elbow to hand)."""
    sword_radius: float = 0.04
    sword_min_tip_speed: float = 2.0
    """m/s. A slower blade touches without hurting."""
    sword_full_damage_tip_speed: float = 8.0
    sword_min_damage: float = 6.0
    sword_max_damage: float = 15.0
    # Grip tension: 0 relaxed, 0.7 = the comfortably firm clench the player calibrated, up to 1.2 squeezing harder.
    # Fireball: overall tension at release, damage × 0.85–1.15, no extra gain past `tension_full_at`.
    tension_min_multiplier: float = 0.85
    tension_max_multiplier: float = 1.15
    tension_full_at: float = 0.9
    # Sword: fist tension scales damage linearly (× 0.7 relaxed, ~1.1 at the calibrated clench, 1.3 from
    # `sword_tension_full_at`) and sharpens the hit grade the same way.
    sword_tension_min_multiplier: float = 0.7
    sword_tension_max_multiplier: float = 1.3
    sword_tension_full_at: float = 1.0
    # Shield: shield-hand tension caps the share a raised shield can block, from `shield_min_block` with a relaxed
    # hand to all of it from `shield_full_block_tension` (the calibrated clench) up. The usual fade still applies.
    shield_min_block: float = 0.5
    shield_full_block_tension: float = 0.7
    sword_rehit_s: float = 0.5
    """A swing hits each target at most once in this window, so one pass isn't counted every tick."""

    shield_radius: float = 0.3
    shield_full_block_s: float = 0.5
    """A freshly raised shield blocks all damage for this long."""
    shield_fade_s: float = 3.5
    """After full block, the blocked fraction falls along a logistic curve from 1 to 0 over this time."""
    shield_fade_steepness: float = 10.0
    """Logistic steepness across the fade; higher keeps the shield strong longer and drops it more sharply mid-fade."""
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

    domain_expand_s: float = 5.0
    """Infinite Void: how long the streaks take to reach the targets."""
    domain_stun_s: float = 5.0
    """After the streaks land, targets can't attack for this long."""
    domain_void_hold_s: float = 2.0
    """Holding the band's Infinite Void sign this long expands the domain; brief misreads of the sign do nothing."""


@dataclass
class PlayerInput:
    """Latest inputs for one player, written by the network layer between ticks."""

    pose: p.Pose | None = None
    sign: str = p.Sign.NONE
    hand: str = p.Hand.RIGHT
    """The hand wearing the Neural Band; all gestures are performed with it."""
    snapped: bool = False
    """A snap started since the previous tick. The network layer sets it; the server clears it after `step`."""
    domain_expanded: bool = False
    """The player asked to expand their domain since the previous tick; cleared after `step` like `snapped`."""
    band_paired: bool = False
    connected: bool = True
    aligned: bool = False
    tension: float | None = None
    """Calibrated grip tension (0 relaxed, 0.7 comfortable clench) from the band, or None (uncalibrated → neutral)."""
    fist_tension: float | None = None
    """The same against the fist calibration alone (sword)."""
    palm_tension: float | None = None
    """The same against the shield-hand calibration alone (shield)."""


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
    tension: float | None = None
    fist_tension: float | None = None
    palm_tension: float | None = None
    cooldown_until: float = 0.0
    held_fireball_velocity: np.ndarray = field(default_factory=lambda: np.zeros(3))
    """The held fireball lags the hand by `Tuning.fireball_inertia_s`; this is its velocity."""
    throw_velocity: np.ndarray | None = None
    """The fastest forward velocity the held fireball reached at throw speed; it leaves at this once the hand slows."""
    sword_tip: np.ndarray | None = None
    sword_hits: dict[str, float] = field(default_factory=dict)
    """Target ID to the time the sword last hit or was blocked by them."""
    sword_locked_until: float = 0.0
    shield_boost: float = 0.0
    stunned_until: float = 0.0
    """Caught in an opponent's domain: no spells until then."""
    void_since: float | None = None
    """When the current unbroken Infinite Void hold started; each hold expands the domain at most once."""
    void_cast: bool = False

    @property
    def alive(self) -> bool:
        return self.hp > 0.0

    @property
    def band_hand_tracker(self) -> HandTracker:
        return self.hands[self.band_hand]

    def contact(self, a: np.ndarray, b: np.ndarray, radius: float, tuning: Tuning) -> Contact | None:
        """The body part a capsule a-b of `radius` hits, if any."""
        if self.pose is None:
            return None
        return body_contact(body_hitboxes(self.pose.joints, tuning.hitboxes), a, b, radius)

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
    traveled: float = 0.0
    power: float = 1.0
    """The thrower's grip-tension damage multiplier at release (`GameState._tension_multiplier`)."""


@dataclass
class GameState:
    tuning: Tuning = field(default_factory=Tuning)
    time: float = 0.0
    tick: int = 0
    players: dict[str, PlayerState] = field(default_factory=dict)
    projectiles: list[Projectile] = field(default_factory=list)
    _next_projectile_id: int = 1
    domain_until: float = 0.0
    """The running domain expansion ends then; only one runs at a time."""

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
            events.extend(self._step_fireball(player, dt))
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
                    max_hp=self.tuning.max_hp,
                    connected=player.connected,
                    band_paired=player.band_paired,
                    sign=player.sign,
                    item=player.item,
                    band_hand=player.band_hand,
                    cooldown=round(max(0.0, player.cooldown_until - self.time), 3),
                    shield_boost=round(player.shield_boost, 3),
                    shield_strength=round(self._shield_block_fraction(player), 3)
                    if player.item == Item.SHIELD
                    else 0.0,
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
        player.tension = player_input.tension
        player.fist_tension = player_input.fist_tension
        player.palm_tension = player_input.palm_tension
        player.band_hand = player_input.hand if player_input.hand in player.hands else p.Hand.RIGHT
        stunned = self.time < player.stunned_until
        if stunned:
            player.sign = p.Sign.NONE
        if player_input.pose is not None:
            player.pose = player_input.pose
            for hand, joint_name in ((p.Hand.LEFT, "l_hand"), (p.Hand.RIGHT, "r_hand")):
                joint = player_input.pose.joints.get(joint_name)
                if joint is not None:
                    player.hands[hand].add(player_input.pose.t, joint)
        if stunned:
            return []
        if player_input.domain_expanded or self._void_held(player):
            return self._expand_domain(player)
        if player_input.snapped:
            return self._on_snap(player)
        return []

    def _void_held(self, player: PlayerState) -> bool:
        if player.sign != p.Sign.INFINITE_VOID:
            player.void_since = None
            return False
        if player.void_since is None:
            player.void_since, player.void_cast = self.time, False
        if player.void_cast or self.time - player.void_since < self.tuning.domain_void_hold_s:
            return False
        player.void_cast = True
        return True

    def _expand_domain(self, caster: PlayerState) -> list[p.Message]:
        """Infinite Void: every opponent is stunned from now until the streaks land plus `domain_stun_s`."""
        targets = self._targets(caster.player_id)
        if not caster.alive or not caster.connected or not targets or self.time < self.domain_until:
            return []
        tuning = self.tuning
        self.domain_until = self.time + tuning.domain_expand_s + tuning.domain_stun_s
        for target in targets:
            target.stunned_until = self.domain_until
        return [
            p.DomainExpansion(
                caster_id=caster.player_id,
                target_ids=[target.player_id for target in targets],
                expand_s=tuning.domain_expand_s,
                stun_s=tuning.domain_stun_s,
            )
        ]

    def _on_snap(self, player: PlayerState) -> list[p.Message]:
        if not player.alive or not player.connected or player.item != Item.NONE or self.time < player.cooldown_until:
            return []
        player.item = Item.FIREBALL
        player.item_since = self.time
        player.held_fireball_velocity = np.zeros(3)
        player.throw_velocity = None
        return [self._spell_event(player, p.SpellState.CHARGING, None)]

    def _step_fireball(self, player: PlayerState, dt: float) -> list[p.Message]:
        events: list[p.Message] = []
        if player.item != Item.FIREBALL:
            return events
        if (
            not player.alive
            or not player.connected
            or self.time < player.stunned_until
            or self.time - player.item_since > self.tuning.fireball_hold_timeout_s
        ):
            player.item = Item.NONE
            events.append(self._spell_event(player, p.SpellState.CANCELLED, None))
            return events

        if (throw_velocity := self._released_throw(player, dt)) is not None:
            events.append(self._throw_fireball(player, throw_velocity))
        return events

    def _released_throw(self, player: PlayerState, dt: float) -> np.ndarray | None:
        """Drag the held fireball after the hand. Once it has moved fast and forward, it leaves at its fastest such
        velocity as soon as the hand slows below that. Remembering the peak matters: at the server's tick rate the hand
        often slows below the fireball only on the tick after the fireball itself dropped under `throw_min_speed`."""
        tuning = self.tuning
        hand_velocity = player.band_hand_tracker.velocity()
        if hand_velocity is None or player.pose is None:
            return None
        follow = 1.0 - float(np.exp(-dt / tuning.fireball_inertia_s))
        held = player.held_fireball_velocity + (hand_velocity - player.held_fireball_velocity) * follow
        player.held_fireball_velocity = held
        held_speed = float(np.linalg.norm(held))
        forwardness = float(normalize(held) @ body_forward(player.pose.joints))
        fast_and_forward = held_speed >= tuning.throw_min_speed and forwardness >= tuning.throw_min_forward
        fastest = player.throw_velocity is None or held_speed > float(np.linalg.norm(player.throw_velocity))
        if fast_and_forward and fastest:
            player.throw_velocity = held
        if player.throw_velocity is None:
            return None
        if float(np.linalg.norm(hand_velocity)) >= float(np.linalg.norm(player.throw_velocity)):
            return None
        return player.throw_velocity

    def _throw_fireball(self, player: PlayerState, velocity: np.ndarray) -> p.Spell:
        tuning = self.tuning
        direction = self._aim_assist(player, normalize(velocity))
        speed = min(float(np.linalg.norm(velocity)), tuning.throw_max_speed)
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
                power=self._tension_multiplier(player),
            )
        )
        self._next_projectile_id += 1
        player.item = Item.NONE
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
            step = projectile.vel * dt
            step_length = float(np.linalg.norm(step))
            range_left = tuning.fireball_max_range_m - projectile.traveled
            out_of_range = step_length >= range_left
            if out_of_range and step_length > 0.0:
                step = step * (range_left / step_length)
            start, end = projectile.pos, projectile.pos + step
            blocked = self._shield_contact(projectile.owner_id, start, end, tuning.fireball_radius, projectile.vel)
            hit = self._first_hit(projectile, start, end) if blocked is None else None
            if blocked is not None:
                shielder, contact = blocked
                damage = self._fireball_damage(projectile)
                events.extend(self._shield_leak(shielder, projectile.owner_id, damage, Item.FIREBALL, contact))
                impact = self._impact(projectile, contact, "blocked", shielder.player_id)
                impact.grade = self._block_grade(shielder)
                events.append(impact)
            elif hit is not None:
                target, body = hit
                damage = self._fireball_damage(projectile)
                hit_event = self._damage(target, projectile.owner_id, damage, Item.FIREBALL, body.pos, body.zone)
                hit_event.grade = self._fireball_grade(projectile, target, body)
                events.append(hit_event)
                events.append(self._impact(projectile, body.pos, "hit", target.player_id))
            elif out_of_range:
                events.append(self._impact(projectile, end, "expired", None))
            else:
                projectile.pos = end
                projectile.traveled += step_length
                remaining.append(projectile)
        self.projectiles = remaining
        return events

    def _fireball_damage(self, projectile: Projectile) -> float:
        return round(
            self.tuning.fireball_damage_per_speed * float(np.linalg.norm(projectile.vel)) * projectile.power, 1
        )

    def _step_sword(self, player: PlayerState, dt: float) -> list[p.Message]:
        """The sword is out exactly while the fist is held (unless a parry knocked it away recently)."""
        able = player.alive and player.connected and player.sign == p.Sign.FIST
        if player.item == Item.SWORD:
            return self._swing(player, dt) if able else [self._sheathe(player)]
        if not able or player.item != Item.NONE or self.time < player.sword_locked_until:
            return []
        return [self._draw_sword(player)]

    def _draw_sword(self, player: PlayerState) -> p.Spell:
        player.item = Item.SWORD
        player.item_since = self.time
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
        for target in self._targets(player.player_id):
            last_hit = player.sword_hits.get(target.player_id)
            rehit_ready = last_hit is None or self.time - last_hit >= tuning.sword_rehit_s
            shield_contact = self._shield_contact_with(target, hilt, tip, tuning.sword_radius, tip - hilt)
            if shield_contact is not None:
                if target.shield_boost >= tuning.shield_parry_min_boost:
                    player.sword_locked_until = self.time + tuning.shield_parry_lock_s
                    parry = self._sword_impact(player, shield_contact, "parried", target.player_id)
                    parry.grade = p.Grade.PERFECT
                    events.append(parry)
                    events.append(self._sheathe(player))
                    return events
                if fast and rehit_ready:
                    player.sword_hits[target.player_id] = self.time
                    damage = round(self._sword_damage(tip_speed) * self._sword_tension_multiplier(player), 1)
                    events.extend(self._shield_leak(target, player.player_id, damage, Item.SWORD, shield_contact))
                    block = self._sword_impact(player, shield_contact, "blocked", target.player_id)
                    block.grade = self._block_grade(target)
                    events.append(block)
                continue
            if not fast or not rehit_ready:
                continue
            body = target.contact(hilt, tip, tuning.sword_radius, tuning)
            if body is None:
                continue
            player.sword_hits[target.player_id] = self.time
            sharpness = self._sword_tension_multiplier(player)
            damage = round(self._sword_damage(tip_speed) * sharpness, 1)
            hit_event = self._damage(target, player.player_id, damage, Item.SWORD, body.pos, body.zone)
            hit_event.grade = self._sword_grade(tip_speed, body.zone, sharpness)
            events.append(hit_event)
        return events

    @staticmethod
    def _grade(score: float) -> str:
        if score >= 0.75:
            return p.Grade.EXCELLENT
        if score >= 0.4:
            return p.Grade.GREAT
        return p.Grade.GOOD

    def _fireball_grade(self, projectile: Projectile, target: PlayerState, body: Contact) -> str:
        """Half throw speed, half how close to the target's centre line it landed; a headshot is perfect."""
        if body.zone == p.Zone.HEAD:
            return p.Grade.PERFECT
        speed = min(1.0, float(np.linalg.norm(projectile.vel)) / self.tuning.throw_max_speed)
        chest = target.chest_position()
        offset = 0.5 if chest is None else float(np.linalg.norm((body.pos - chest)[[0, 2]]))
        centred = float(np.clip(1.0 - offset / 0.35, 0.0, 1.0))
        return self._grade(0.5 * speed + 0.5 * centred)

    def _sword_grade(self, tip_speed: float, zone: str, sharpness: float = 1.0) -> str:
        """Faster swings grade higher; a firm fist (`sharpness` above 1) lifts the grade, a slack one lowers it."""
        if zone == p.Zone.HEAD:
            return p.Grade.PERFECT
        tuning = self.tuning
        speed_range = tuning.sword_full_damage_tip_speed - tuning.sword_min_tip_speed
        speed = float(np.clip((tip_speed - tuning.sword_min_tip_speed) / speed_range, 0.0, 1.0))
        return self._grade(float(np.clip(speed * sharpness, 0.0, 1.0)))

    def _block_grade(self, shielder: PlayerState) -> str:
        """Late, last-moment blocks score higher than a shield held up all along."""
        held = self.time - shielder.item_since
        return self._grade(float(np.clip(1.0 - (held - 0.15) / 1.5, 0.0, 1.0)))

    def _sword_damage(self, tip_speed: float) -> float:
        tuning = self.tuning
        speed_range = tuning.sword_full_damage_tip_speed - tuning.sword_min_tip_speed
        strength = float(np.clip((tip_speed - tuning.sword_min_tip_speed) / speed_range, 0.0, 1.0))
        return round(tuning.sword_min_damage + (tuning.sword_max_damage - tuning.sword_min_damage) * strength, 1)

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

    def _tension_multiplier(self, player: PlayerState) -> float:
        """1 without calibrated tension; otherwise eases from min to max, flat from `tension_full_at` up."""
        tuning = self.tuning
        if player.tension is None:
            return 1.0
        effort = float(np.clip(player.tension / tuning.tension_full_at, 0.0, 1.0))
        eased = 1.0 - (1.0 - effort) ** 2
        return tuning.tension_min_multiplier + (tuning.tension_max_multiplier - tuning.tension_min_multiplier) * eased

    def _sword_tension_multiplier(self, player: PlayerState) -> float:
        """1 without calibrated fist tension; otherwise linear from min (relaxed) to max at `sword_tension_full_at`."""
        tuning = self.tuning
        if player.fist_tension is None:
            return 1.0
        effort = float(np.clip(player.fist_tension / tuning.sword_tension_full_at, 0.0, 1.0))
        return (
            tuning.sword_tension_min_multiplier
            + (tuning.sword_tension_max_multiplier - tuning.sword_tension_min_multiplier) * effort
        )

    def _shield_block_fraction(self, shielder: PlayerState) -> float:
        """`_base_shield_block_fraction`, capped by how firmly the shield hand is held (no cap without calibration)."""
        tuning = self.tuning
        base = self._base_shield_block_fraction(shielder)
        if shielder.palm_tension is None:
            return base
        firmness = float(np.clip(shielder.palm_tension / tuning.shield_full_block_tension, 0.0, 1.0))
        return base * (tuning.shield_min_block + (1.0 - tuning.shield_min_block) * firmness)

    def _base_shield_block_fraction(self, shielder: PlayerState) -> float:
        """Share of damage the raised shield blocks: 1 while fresh, then a logistic fade to 0 over `shield_fade_s`."""
        tuning = self.tuning
        fade_progress = (self.time - shielder.item_since - tuning.shield_full_block_s) / tuning.shield_fade_s
        if fade_progress <= 0.0:
            return 1.0
        if fade_progress >= 1.0:
            return 0.0
        start, end = (
            _logistic_fall(0.0, tuning.shield_fade_steepness),
            _logistic_fall(1.0, tuning.shield_fade_steepness),
        )
        return (_logistic_fall(fade_progress, tuning.shield_fade_steepness) - end) / (start - end)

    def _shield_leak(
        self, shielder: PlayerState, source_id: str, damage: float, kind: str, contact: np.ndarray
    ) -> list[p.Damage]:
        """The part of `damage` a fading shield lets through, dealt to the shielding arm."""
        leaked = round(damage * (1.0 - self._shield_block_fraction(shielder)), 1)
        if leaked <= 0.0:
            return []
        return [self._damage(shielder, source_id, leaked, kind, contact, p.Zone.ARM)]

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

    def _damage(
        self, target: PlayerState, source_id: str, amount: float, kind: str, pos: np.ndarray, zone: str
    ) -> p.Damage:
        target.hp = max(0.0, target.hp - amount)
        return p.Damage(
            target_id=target.player_id,
            source_id=source_id,
            amount=amount,
            hp_after=target.hp,
            kind=kind,
            pos=_round(pos),
            zone=zone,
        )

    def _first_hit(
        self, projectile: Projectile, start: np.ndarray, end: np.ndarray
    ) -> tuple[PlayerState, Contact] | None:
        for target in self._targets(projectile.owner_id):
            contact = target.contact(start, end, self.tuning.fireball_radius, self.tuning)
            if contact is not None:
                return target, contact
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


def _logistic_fall(x: float, steepness: float) -> float:
    """Logistic curve falling from near 1 to near 0, centred on x = 0.5."""
    return 1.0 / (1.0 + float(np.exp(steepness * (x - 0.5))))


def _round(values: np.ndarray) -> list[float]:
    return [round(float(v), 4) for v in values]
