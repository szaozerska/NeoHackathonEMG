"""Which player's band buzzes for which game event, and for how long."""

from __future__ import annotations

from . import protocol as p

CHARGING_MS = 40
CAST_MS = 120
HIT_TAKEN_MS = 300
HIT_DEALT_MS = 60
MATCH_START_MS = 250
MATCH_END_MS = 500


def haptics_for(event: p.Message) -> list[tuple[str, int]]:
    """(player ID, duration in ms) for every band that should buzz on `event`."""
    match event:
        case p.Spell(state=p.SpellState.CHARGING, caster_id=caster):
            return [(caster, CHARGING_MS)]
        case p.Spell(state=p.SpellState.CAST, caster_id=caster):
            return [(caster, CAST_MS)]
        case p.Damage(target_id=target, source_id=source):
            return [(target, HIT_TAKEN_MS), (source, HIT_DEALT_MS)]
        case _:
            return []
