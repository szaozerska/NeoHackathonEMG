"""Wire protocol (architecture.md §4.2 and §6): newline-delimited JSON, one message per line.

Shared by the server, the hand-sign client and the fake clients so the message format can't drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar

GAME_PORT = 9000
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
    """The sword was put away (the fist was released)."""


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

    Fireball: `charging` on snap, `cast` on throw, `cancelled` on fizzle. Sword: `cast` on draw, `sheathed` on release.
    """

    TYPE: ClassVar[str] = "spell"
    caster_id: str
    spell: str
    state: str
    charge: float
    origin: list[float] | None
    direction: list[float] | None


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


@dataclass
class Impact(Message):
    """A projectile ended: it hit a player (`hit`) or ran out of lifetime (`expired`)."""

    TYPE: ClassVar[str] = "impact"
    projectile_id: int
    kind: str
    owner_id: str
    pos: list[float]
    reason: str
    target_id: str | None = None


@dataclass
class PlayerSnapshot:
    player_id: str
    hp: float
    connected: bool
    band_paired: bool
    sign: str
    item: str
    """What the player currently holds: `none`, `fireball` or `sword`."""
    band_hand: str = Hand.RIGHT
    """The hand wearing the Neural Band, where held spells are drawn."""
    cooldown: float = 0.0
    """Seconds until the player can conjure again."""

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


@dataclass
class State(Message):
    """Full game state, broadcast every server tick."""

    TYPE: ClassVar[str] = "state"
    tick: int
    players: list[PlayerSnapshot] = field(default_factory=list)
    projectiles: list[ProjectileSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        return cls(
            tick=int(data["tick"]),
            players=[PlayerSnapshot(**player) for player in data.get("players", [])],
            projectiles=[ProjectileSnapshot(**projectile) for projectile in data.get("projectiles", [])],
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
