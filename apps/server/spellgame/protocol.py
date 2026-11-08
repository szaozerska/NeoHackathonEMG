"""Wire protocol (architecture.md §4.2 and §6): newline-delimited JSON, one message per line.

Shared by the server, the hand-sign client and the fake clients so the message format can't drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar

# Not 9000: Quest OS refuses outgoing TCP to port 9000 (connect fails with EACCES).
GAME_PORT = 9100
DISCOVERY_PORT = 47777
BEACON_PREFIX = "SPELLGAME "

JOINT_NAMES = (
    "head",
    "chest",
    "hips",
    "l_shoulder",
    "r_shoulder",
    "l_elbow",
    "r_elbow",
    "l_wrist",
    "r_wrist",
    "l_hand",
    "r_hand",
    "l_knee",
    "r_knee",
    "l_ankle",
    "r_ankle",
    "l_foot",
    "r_foot",
)


class Role:
    VR = "vr"
    CLASSIFIER = "classifier"


class Hand:
    LEFT = "left"
    RIGHT = "right"


class Sign:
    """Gesture labels the Neural Band side reports. `snap` is momentary; the others are held."""

    NONE = "none"
    FIST = "fist"
    OPEN_PALM = "open_palm"
    SNAP = "snap"
    INFINITE_VOID = "infinite_void"
    """Held for `Tuning.domain_void_hold_s`, it expands the player's domain like the headset's `DomainExpand`."""


class Finger:
    THUMB = "thumb"
    INDEX = "index"
    MIDDLE = "middle"


class GestureAction:
    """The band's built-in decoded gestures, one per physical contact (the hand-sign client deduplicates them)."""

    TAP = "tap"
    DOUBLE_TAP = "double_tap"
    PRESS = "press"
    RELEASE = "release"
    HOLD = "hold"
    SWIPE_UP = "swipe_up"
    SWIPE_DOWN = "swipe_down"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"


class SpellState:
    CHARGING = "charging"
    CAST = "cast"
    CANCELLED = "cancelled"
    SHEATHED = "sheathed"
    """The sword or shield was put away (the fist or open palm was released)."""


class ProtocolError(ValueError):
    pass


_REGISTRY: dict[str, type[Message]] = {}


@dataclass
class Message:
    TYPE: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.TYPE:
            _REGISTRY[cls.TYPE] = cls

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.TYPE, **{f.name: _to_json(getattr(self, f.name)) for f in fields(self)}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})


def _to_json(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {key: _to_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json(item) for item in value]
    return value


@dataclass
class Joint:
    pos: list[float]
    rot: list[float]
    """[w, x, y, z]"""
    vel: list[float] | None = None
    """Optional linear velocity in m/s, measured on the headset at its frame rate."""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"pos": list(self.pos), "rot": list(self.rot)}
        if self.vel is not None:
            data["vel"] = list(self.vel)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Joint:
        return cls(pos=list(data["pos"]), rot=list(data["rot"]), vel=data.get("vel"))


@dataclass
class DeviceInfo:
    """Identifies the machine behind a connection, for the server's monitor."""

    name: str
    model: str | None = None
    id: str | None = None
    """A stable unique identifier, e.g. the Quest's SystemInfo.deviceUniqueIdentifier."""

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class Hello(Message):
    TYPE: ClassVar[str] = "hello"
    role: str
    player_id: str | None = None
    """Optional: a VR client reclaims its ID after a reconnect; a classifier pairs directly with that player."""
    device: DeviceInfo | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Hello:
        device = data.get("device")
        return cls(
            role=data["role"],
            player_id=data.get("player_id"),
            device=DeviceInfo(**device) if device is not None else None,
        )


@dataclass
class Welcome(Message):
    TYPE: ClassVar[str] = "welcome"
    player_id: str | None


@dataclass
class Error(Message):
    TYPE: ClassVar[str] = "error"
    message: str


@dataclass
class Pinch(Message):
    TYPE: ClassVar[str] = "pinch"
    t: float
    hand: str


@dataclass
class PairStart(Message):
    TYPE: ClassVar[str] = "pair_start"


@dataclass
class PairPrompt(Message):
    TYPE: ClassVar[str] = "pair_prompt"
    player_id: str


@dataclass
class Paired(Message):
    TYPE: ClassVar[str] = "paired"
    player_id: str


class AlignMethod:
    ANCHOR = "anchor"
    """Loaded the host's Shared Spatial Anchor and aligned its tracking space to it."""
    FLOOR_SPOTS = "floor_spots"
    """Fallback: recentered while standing on its marked floor spot, facing `spot_yaw`."""
    MARKER = "marker"
    """Saw the printed QR code on the floor in the middle of the room: its center is the origin and its top (arrow) is
    +z, pointing from P1's side to P2's."""
    CENTER = "center"
    """Both players touched right controller tips in the middle of the room, each pointing at the other: the touch
    point (on the floor) is the origin and the controller's pointing direction is the player's `spot_yaw`."""


@dataclass
class Space(Message):
    """Server → VR: the shared room frame (§5.1). Sent on join and whenever the host or anchor changes."""

    TYPE: ClassVar[str] = "space"
    group_uuid: str
    """Meta colocation group UUID to share the anchor to and load it from."""
    host_id: str | None
    """The headset that should create and share the anchor."""
    anchor_uuid: str | None
    """The shared anchor to align to; None until the host has shared one."""
    spot_pos: list[float]
    """This headset's floor spot in the shared frame, for the `floor_spots` fallback."""
    spot_yaw: float
    """Degrees about +y the player faces on their spot; 0 is +z."""


@dataclass
class AnchorShared(Message):
    """VR (host only) → server: the anchor at the shared frame's origin was saved and shared to `group_uuid`."""

    TYPE: ClassVar[str] = "anchor_shared"
    anchor_uuid: str


@dataclass
class Aligned(Message):
    """VR → server: this headset's poses are now in the shared frame."""

    TYPE: ClassVar[str] = "aligned"
    method: str
    """An `AlignMethod`."""
    anchor_uuid: str | None = None
    """The anchor aligned to; required for `anchor`, so a stale anchor is rejected."""


@dataclass
class Unaligned(Message):
    """VR → server: this headset left the shared frame (e.g. it recentered), so it must calibrate again."""

    TYPE: ClassVar[str] = "unaligned"


@dataclass
class SpaceReset(Message):
    """Any client → server: drop the anchor and re-align everyone."""

    TYPE: ClassVar[str] = "space_reset"


@dataclass
class Pose(Message):
    TYPE: ClassVar[str] = "pose"
    player_id: str | None
    t: float
    joints: dict[str, Joint]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pose:
        joints = {name: Joint.from_dict(joint) for name, joint in data["joints"].items() if joint is not None}
        return cls(player_id=data.get("player_id"), t=float(data["t"]), joints=joints)


@dataclass
class SignMessage(Message):
    TYPE: ClassVar[str] = "sign"
    player_id: str | None
    t: float
    hand: str
    sign: str
    confidence: float = 1.0


@dataclass
class Tension(Message):
    """How hard the band hand is squeezing (classifier → server), about 20 times a second.

    `value` comes from the hand-client's filtered EMG envelope, scaled to this player's own calibration: 0 = relaxed,
    0.7 = the "comfortably firm" fist / shield hand they held while calibrating, up to 1.2 when squeezing harder.
    """

    TYPE: ClassVar[str] = "tension"
    player_id: str | None
    t: float
    hand: str
    value: float
    calibrated: bool = False
    """False until the player has done the relax / fist / palm calibration; the server ignores uncalibrated values."""
    fist: float | None = None
    """Tension against the player's fist calibration alone (drives the sword), same scale as `value`."""
    palm: float | None = None
    """Tension against their shield-hand calibration alone (drives the shield); None if that step didn't register."""


class CalibrationPhase:
    REST = "rest"
    SQUEEZE = "squeeze"
    """Make a fist, comfortably firm (~70%)."""
    PALM = "palm"
    """Shield hand, palm out, comfortably firm (~70%)."""
    DONE = "done"
    FAILED = "failed"


@dataclass
class Calibrate(Message):
    """Restart the grip calibration (headset → server → that player's classifier)."""

    TYPE: ClassVar[str] = "calibrate"
    player_id: str | None = None


@dataclass
class CalibrationStatus(Message):
    """Grip calibration progress (classifier → server → every headset) so the headset can prompt the player."""

    TYPE: ClassVar[str] = "calibration"
    player_id: str | None
    phase: str
    """A `CalibrationPhase`."""
    progress: float = 0.0
    """0–1 through the current phase."""


@dataclass
class Gesture(Message):
    """A band's built-in decoded gesture (classifier → server → every VR client), e.g. for game UI interaction."""

    TYPE: ClassVar[str] = "gesture"
    player_id: str | None
    t: float
    hand: str
    finger: str
    action: str


@dataclass
class Haptic(Message):
    """Server → one player's classifier: buzz that player's band once. Kinesis accepts 1–2000 ms."""

    TYPE: ClassVar[str] = "haptic"
    duration_ms: int


@dataclass
class Wrist(Message):
    TYPE: ClassVar[str] = "wrist"
    player_id: str | None
    t: float
    hand: str
    rot: list[float]


@dataclass
class Spell(Message):
    """Spell lifecycle event.

    Fireball: `charging` on snap, `cast` on throw, `cancelled` on fizzle.
    Sword and shield: `cast` on draw/raise, `sheathed` on release (and for a sword, when it is parried).
    """

    TYPE: ClassVar[str] = "spell"
    caster_id: str
    spell: str
    state: str
    charge: float
    origin: list[float] | None
    direction: list[float] | None


@dataclass
class DomainExpand(Message):
    """VR → server: the player held B long enough to expand their domain."""

    TYPE: ClassVar[str] = "domain_expand"


@dataclass
class DomainExpansion(Message):
    """Server → VR: Infinite Void. Streaks race from the caster to each target over `expand_s`; each target then can't
    attack for `stun_s` more seconds (they can't attack from the cast on)."""

    TYPE: ClassVar[str] = "domain_expansion"
    caster_id: str
    target_ids: list[str]
    expand_s: float
    stun_s: float


class Grade:
    """How well an attack or block was performed (Pokémon Go-style callouts), independent of raw damage."""

    GOOD = "good"
    GREAT = "great"
    EXCELLENT = "excellent"
    PERFECT = "perfect"
    """A headshot or a parry."""


class Zone:
    """The body part a hit landed on (`spellgame.hitboxes`)."""

    HEAD = "head"
    TORSO = "torso"
    ARM = "arm"
    LEG = "leg"


@dataclass
class Damage(Message):
    TYPE: ClassVar[str] = "damage"
    target_id: str
    source_id: str
    amount: float
    hp_after: float
    kind: str | None = None
    """What dealt the damage: `fireball` or `sword`."""
    pos: list[float] | None = None
    """Where the hit landed, e.g. for damage numbers."""
    zone: str | None = None
    """The `Zone` that was hit."""
    grade: str | None = None
    """A `Grade`: how good the hit was (fireball: speed and how centred; sword: blade speed; head = perfect)."""


@dataclass
class Impact(Message):
    """A spell contact.

    Fireballs: `hit` a player, `blocked` by a shield, or `expired`. Swords (`projectile_id` 0): `blocked` by a shield,
    or `parried` by a boosted one, which knocks the sword away. `target_id` is the player hit or shielding.
    """

    TYPE: ClassVar[str] = "impact"
    projectile_id: int
    kind: str
    owner_id: str
    pos: list[float]
    reason: str
    target_id: str | None = None
    grade: str | None = None
    """A `Grade` for `blocked` (how soon after raising the shield) and `parried` (always perfect)."""


@dataclass
class PlayerSnapshot:
    player_id: str
    hp: float
    connected: bool
    band_paired: bool
    sign: str
    item: str
    """What the player currently holds: `none`, `fireball`, `sword` or `shield`."""
    band_hand: str = Hand.RIGHT
    """The hand wearing the Neural Band, where held spells are drawn."""
    cooldown: float = 0.0
    """Seconds until the player can conjure again."""
    shield_boost: float = 0.0
    """0-1 power from the last shield push; at `Tuning.shield_parry_min_boost` or more a sword contact is a parry."""
    shield_strength: float = 0.0
    """0-1 share of damage the raised shield blocks: 1 when fresh, fading to 0 (`Tuning.shield_fade_s`); 0 when down."""
    aligned: bool = False
    """The headset has reported its poses are in the shared room frame (§5.1)."""
    max_hp: float = 0.0
    """Starting HP (`Tuning.max_hp`), so clients can scale HP bars without copying the tuning."""
    void_charge: float = 0.0
    align_method: str | None = None
    """How this headset joined the shared room frame (`AlignMethod`), None until it has."""
    """0-1 progress of an Infinite Void hold (`Tuning.domain_void_hold_s`); back to 0 when released or once it fires."""

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class ProjectileSnapshot:
    id: int
    kind: str
    owner_id: str
    pos: list[float]
    vel: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


class MatchPhase:
    """Server-owned match flow (architecture.md §5.2): `lobby` → `ready` → `countdown` → `playing` → `ended`."""

    LOBBY = "lobby"
    """Menus; no spells, and a defeated player respawns."""
    READY = "ready"
    """A match is set up; waiting for every fighter's `ready`."""
    COUNTDOWN = "countdown"
    PLAYING = "playing"
    ENDED = "ended"
    """Results; `rematch` goes back to `ready`, `match_quit` to the lobby."""


class MatchMode:
    SOLO = "solo"
    """One headset against the server's AI opponent."""
    VERSUS = "versus"
    """The first two connected headsets against each other."""


class MatchEndReason:
    KO = "ko"
    TIME = "time"
    QUIT = "quit"
    DISCONNECT = "disconnect"


MATCH_DURATIONS_S = (60.0, 120.0, 300.0)
"""The durations the headset menu offers; the server accepts any length within `MatchRules`."""
AI_PLAYER_ID = "AI"


@dataclass
class MatchSetup(Message):
    """VR → server, in the lobby or while waiting for ready: choose the mode and length of the next match."""

    TYPE: ClassVar[str] = "match_setup"
    mode: str
    duration_s: float = 60.0
    sword_only: bool = False
    """No spells: only the sword works (no fireball, shield or domain expansion)."""


@dataclass
class Ready(Message):
    """VR → server, while the match is `ready`: this fighter is (or is no longer) ready to start."""

    TYPE: ClassVar[str] = "ready"
    ready: bool = True


@dataclass
class MatchQuit(Message):
    """VR → server: end the running match early, or leave the ready or results screen for the lobby."""

    TYPE: ClassVar[str] = "match_quit"


@dataclass
class Rematch(Message):
    """VR → server, on the results screen: same mode and length again, back to waiting for ready."""

    TYPE: ClassVar[str] = "rematch"


@dataclass
class MatchPause(Message):
    """VR → server, from a fighter while `playing`: pause (limited per fighter) or resume (after a short countdown)."""

    TYPE: ClassVar[str] = "match_pause"
    paused: bool = True


@dataclass
class MatchRestart(Message):
    """VR → server, from a fighter mid-match: vote to restart; it restarts from the countdown once every human has."""

    TYPE: ClassVar[str] = "match_restart"


@dataclass
class MatchSnapshot:
    phase: str = MatchPhase.LOBBY
    mode: str | None = None
    duration_s: float = 0.0
    time_left: float = 0.0
    """Seconds of play left; stays at the full duration until `playing`, and at 0 during sudden death."""
    countdown: float = 0.0
    """Seconds until `playing`, during `countdown`."""
    fighters: list[str] = field(default_factory=list)
    """The players in the match; other headsets watch."""
    ready: list[str] = field(default_factory=list)
    sudden_death: bool = False
    """Time ran out on equal HP: the next hit wins."""
    winner: str | None = None
    """Set when `ended`; None for a draw or a quit."""
    reason: str | None = None
    """A `MatchEndReason`, when `ended`."""
    ended_by: str | None = None
    """Who sent `match_quit`, for a quit."""
    ai_id: str | None = None
    """The AI opponent's player ID in a solo match; its poses arrive like any other player's."""
    sword_only: bool = False
    """The set-up match allows only the sword."""
    paused_by: str | None = None
    """The fighter who paused a `playing` match; everything is frozen until it resumes."""
    resume_in: float = 0.0
    """Seconds until a paused match resumes, once someone chose resume (or the pause ran out); 0 otherwise."""
    pauses_left: list[int] = field(default_factory=list)
    """Pauses each fighter has left this match, in `fighters` order."""
    restart_votes: list[str] = field(default_factory=list)
    """Fighters who asked to restart; the match restarts once every human fighter has."""

    def to_dict(self) -> dict[str, Any]:
        return {f.name: _to_json(getattr(self, f.name)) for f in fields(self)}


@dataclass
class State(Message):
    """Full game state, broadcast every server tick."""

    TYPE: ClassVar[str] = "state"
    tick: int
    players: list[PlayerSnapshot] = field(default_factory=list)
    projectiles: list[ProjectileSnapshot] = field(default_factory=list)
    match: MatchSnapshot | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        match = data.get("match")
        return cls(
            tick=int(data["tick"]),
            players=[PlayerSnapshot(**player) for player in data.get("players", [])],
            projectiles=[ProjectileSnapshot(**projectile) for projectile in data.get("projectiles", [])],
            match=MatchSnapshot(**match) if match is not None else None,
        )


def encode(message: Message) -> str:
    return json.dumps(message.to_dict(), separators=(",", ":"))


def encode_line(message: Message) -> bytes:
    return (encode(message) + "\n").encode()


def decode(line: str | bytes) -> Message:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProtocolError("message must be a JSON object")
    message_type = data.get("type")
    message_class = _REGISTRY.get(message_type)  # type: ignore[arg-type]
    if message_class is None:
        raise ProtocolError(f"unknown message type: {message_type!r}")
    try:
        return message_class.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"malformed {message_type!r} message: {exc}") from exc
