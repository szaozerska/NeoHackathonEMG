"""Turns the band's raw decoded gesture messages into one clean event per physical gesture.

The band can describe one contact twice, as a raw `action` and a `derived_action`, and repeats some messages.
The rules mirror Kinesis's own `GestureRouter` (Kinesis-Axo Sources/KinesisCore/Gestures.swift).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal

from spellgame.protocol import Finger, GestureAction

from .kinesis_feed import BandGestureEvent

DERIVED_ACTIONS = {
    "singleTap": GestureAction.TAP,
    "doubleTap": GestureAction.DOUBLE_TAP,
    "buttonPress": GestureAction.PRESS,
    "buttonRelease": GestureAction.RELEASE,
    "buttonHoldRelease": GestureAction.RELEASE,
    "buttonHold": GestureAction.HOLD,
    "buttonUp": GestureAction.SWIPE_UP,
    "buttonDown": GestureAction.SWIPE_DOWN,
    "buttonLeft": GestureAction.SWIPE_LEFT,
    "buttonRight": GestureAction.SWIPE_RIGHT,
}
RAW_ACTIONS = {
    "tap": GestureAction.TAP,
    "doubletap": GestureAction.DOUBLE_TAP,
    "press": GestureAction.PRESS,
    "release": GestureAction.RELEASE,
    "up": GestureAction.SWIPE_UP,
    "down": GestureAction.SWIPE_DOWN,
    "left": GestureAction.SWIPE_LEFT,
    "right": GestureAction.SWIPE_RIGHT,
}
FINGERS = (Finger.THUMB, Finger.INDEX, Finger.MIDDLE)
PINCH_FINGERS = (Finger.INDEX, Finger.MIDDLE)
PINCH_ACTIONS = (GestureAction.TAP, GestureAction.PRESS)
RAW_DERIVED_DUPLICATE_WINDOW_S = 0.18
REMEMBERED_MESSAGES = 128

Source = Literal["raw", "derived"]
MessageIdentity = tuple[int, int, str, str, str]


@dataclass(frozen=True)
class CleanGesture:
    t: float
    """Mac monotonic time Kinesis received it."""
    finger: str
    action: str

    @property
    def is_pinch(self) -> bool:
        """What pinch-to-pair (architecture.md §5) counts as a pinch."""
        return self.finger in PINCH_FINGERS and self.action in PINCH_ACTIONS


class GestureCleaner:
    def __init__(self) -> None:
        self._seen: set[MessageIdentity] = set()
        self._seen_order: deque[MessageIdentity] = deque()
        self._last_passed: dict[tuple[str, str], tuple[Source, float]] = {}

    def clean(self, event: BandGestureEvent) -> CleanGesture | None:
        """The gesture `event` describes, or None if it's synthetic, unrecognised or a duplicate."""
        if event.synthetic or event.finger not in FINGERS:
            return None
        recognised = _recognise(event)
        if recognised is None:
            return None
        source, action = recognised
        if not self._first_sighting(
            (event.sequence, event.timestamp_us, event.finger, event.action, event.derived_action)
        ):
            return None
        key = (event.finger, action)
        last = self._last_passed.get(key)
        if last is not None and last[0] != source and abs(event.host_time_s - last[1]) < RAW_DERIVED_DUPLICATE_WINDOW_S:
            return None
        self._last_passed[key] = (source, event.host_time_s)
        return CleanGesture(t=event.host_time_s, finger=event.finger, action=action)

    def _first_sighting(self, identity: MessageIdentity) -> bool:
        if identity in self._seen:
            return False
        self._seen.add(identity)
        self._seen_order.append(identity)
        if len(self._seen_order) > REMEMBERED_MESSAGES:
            self._seen.discard(self._seen_order.popleft())
        return True


def _recognise(event: BandGestureEvent) -> tuple[Source, str] | None:
    if event.derived_action in DERIVED_ACTIONS:
        return "derived", DERIVED_ACTIONS[event.derived_action]
    if event.action in RAW_ACTIONS:
        return "raw", RAW_ACTIONS[event.action]
    return None
