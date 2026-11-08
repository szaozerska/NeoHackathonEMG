"""Match flow (architecture.md §5.2), owned by the server: mode, length, ready checks, countdown, timer and result.
`lobby` → `match_setup` → `ready` → every fighter `ready` → `countdown` → `playing` → KO or time-out → `ended`, then
`rematch` (back to `ready`) or `match_quit` (back to the lobby). A KO ends the match at once; at time-out the higher HP
wins and a tie goes to sudden death, where the next hit wins. While `playing`, a fighter can pause (everything frozen,
a few pauses each, resuming after a countdown), and the fighters can restart once all of them have asked to.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from . import protocol as p
from .game_state import GameState, Item, PlayerInput

log = logging.getLogger(__name__)

Phase = p.MatchPhase


@dataclass
class MatchRules:
    countdown_s: float = 3.0
    min_duration_s: float = 10.0
    max_duration_s: float = 600.0
    pauses_per_fighter: int = 2
    max_pause_s: float = 60.0
    """A pause resumes by itself after this, so it can't stall the match."""
    resume_countdown_s: float = 3.0


class Match:
    def __init__(self, rules: MatchRules | None = None) -> None:
        self.rules = rules or MatchRules()
        self.phase = Phase.LOBBY
        self.mode: str | None = None
        self.sword_only = False
        self.duration_s = 0.0
        self.time_left = 0.0
        self.countdown = 0.0
        self.owner: str | None = None
        """Who set the match up; the human fighter of a solo match."""
        self.fighters: list[str] = []
        self.ready: set[str] = set()
        self.sudden_death = False
        self.winner: str | None = None
        self.reason: str | None = None
        self.ended_by: str | None = None
        self.paused_by: str | None = None
        self.pause_left_s = 0.0
        self.resume_in = 0.0
        self.pauses_used: dict[str, int] = {}
        self.restart_votes: set[str] = set()

    @property
    def paused(self) -> bool:
        return self.paused_by is not None

    @property
    def ai_id(self) -> str | None:
        return p.AI_PLAYER_ID if self.mode == p.MatchMode.SOLO and self.phase != Phase.LOBBY else None

    @property
    def in_progress(self) -> bool:
        return self.phase in (Phase.COUNTDOWN, Phase.PLAYING)

    def can_cast(self, player_id: str) -> bool:
        """Spells work as practice in the menus and for fighters while playing; not during the countdown or results."""
        if self.phase in (Phase.LOBBY, Phase.READY):
            return True
        return self.phase == Phase.PLAYING and not self.paused and player_id in self.fighters

    def restrict(self, player_input: PlayerInput) -> PlayerInput:
        """In a sword-only match every sign but the fist is dropped: no fireball, shield or domain expansion."""
        if not self.sword_only:
            return player_input
        sign = player_input.sign if player_input.sign == p.Sign.FIST else p.Sign.NONE
        return replace(player_input, sign=sign, snapped=False, domain_expanded=False)

    def setup(self, player_id: str, mode: str, duration_s: float, sword_only: bool = False) -> str | None:
        """Returns an error message, or None once the match is waiting for ready."""
        if self.phase not in (Phase.LOBBY, Phase.READY):
            return f"can't set up a match while {self.phase}"
        if mode not in (p.MatchMode.SOLO, p.MatchMode.VERSUS):
            return f"unknown match mode {mode!r}"
        self._clear_result()
        self.mode = mode
        self.sword_only = bool(sword_only)
        self.duration_s = min(max(float(duration_s), self.rules.min_duration_s), self.rules.max_duration_s)
        self.time_left = self.duration_s
        self.owner = player_id
        self.fighters = []
        self.ready.clear()
        self.phase = Phase.READY
        rules = " sword-only" if self.sword_only else ""
        log.info("%s set up a %s%s match, %.0f s", player_id, mode, rules, self.duration_s)
        return None

    def set_ready(self, player_id: str, ready: bool) -> None:
        """Readies anyone; `step` drops players who turn out not to be fighters."""
        if self.phase != Phase.READY:
            return
        if ready:
            self.ready.add(player_id)
        else:
            self.ready.discard(player_id)

    def quit(self, player_id: str) -> None:
        if self.phase in (Phase.READY, Phase.ENDED):
            self._to_lobby()
        elif self.in_progress:
            self._end(None, p.MatchEndReason.QUIT, ended_by=player_id)

    def pause(self, player_id: str, paused: bool) -> None:
        """Pauses at most `pauses_per_fighter` times per fighter; any fighter can start the resume countdown."""
        if self.phase != Phase.PLAYING or player_id not in self.fighters:
            return
        if not paused:
            if self.paused and self.resume_in == 0.0:
                self.resume_in = self.rules.resume_countdown_s
            return
        used = self.pauses_used.get(player_id, 0)
        if self.paused or used >= self.rules.pauses_per_fighter:
            return
        self.pauses_used[player_id] = used + 1
        self.paused_by = player_id
        self.pause_left_s = self.rules.max_pause_s
        self.resume_in = 0.0
        log.info("%s paused the match", player_id)

    def vote_restart(self, player_id: str, game: GameState) -> None:
        """Restarts from the countdown, with full HP and clock, once every human fighter has asked."""
        if not self.in_progress or player_id not in self.fighters:
            return
        self.restart_votes.add(player_id)
        if self.restart_votes >= {f for f in self.fighters if f != self.ai_id}:
            self.sudden_death = False
            self._start_countdown(game)

    def rematch(self) -> None:
        if self.phase != Phase.ENDED:
            return
        self._clear_result()
        self.time_left = self.duration_s
        self.ready.clear()
        self.phase = Phase.READY

    def step(self, game: GameState, headsets: list[str], dt: float, aligned: set[str] | None = None) -> None:
        """Advance after `game.step`. `headsets`: connected headset player IDs in join order.

        `aligned`: headsets in the shared room frame (§5.1). A versus countdown waits for both fighters to be in it,
        otherwise each headset judges and draws the other in a different frame. None skips the check.
        """
        if self.phase == Phase.READY:
            self._step_ready(game, headsets, aligned)
        elif self.in_progress and any(f not in headsets and f != self.ai_id for f in self.fighters):
            remaining = [f for f in self.fighters if f in headsets or f == self.ai_id]
            self._end(remaining[0] if len(remaining) == 1 else None, p.MatchEndReason.DISCONNECT)
        elif self.phase == Phase.COUNTDOWN:
            self.countdown -= dt
            if self.countdown <= 0.0:
                self.countdown = 0.0
                self.phase = Phase.PLAYING
        elif self.phase == Phase.PLAYING and self.paused:
            self._step_pause(dt)
        elif self.phase == Phase.PLAYING:
            self._step_playing(game, dt)
        if self.phase in (Phase.LOBBY, Phase.READY):
            for player in game.players.values():
                if not player.alive:
                    player.hp = game.tuning.max_hp

    def snapshot(self) -> p.MatchSnapshot:
        return p.MatchSnapshot(
            phase=self.phase,
            mode=self.mode,
            duration_s=self.duration_s,
            time_left=round(self.time_left, 2),
            countdown=round(self.countdown, 2),
            fighters=list(self.fighters),
            ready=[f for f in self.fighters if f in self.ready],
            sudden_death=self.sudden_death,
            winner=self.winner,
            reason=self.reason,
            ended_by=self.ended_by,
            ai_id=self.ai_id,
            sword_only=self.sword_only,
            paused_by=self.paused_by,
            resume_in=round(self.resume_in, 2),
            pauses_left=[self.rules.pauses_per_fighter - self.pauses_used.get(f, 0) for f in self.fighters],
            restart_votes=[f for f in self.fighters if f in self.restart_votes],
        )

    def _step_ready(self, game: GameState, headsets: list[str], aligned: set[str] | None) -> None:
        if self.mode == p.MatchMode.SOLO:
            if self.owner not in headsets:
                self._to_lobby()
                return
            self.fighters = [self.owner, p.AI_PLAYER_ID]
            self.ready.add(p.AI_PLAYER_ID)
        else:
            self.fighters = headsets[:2]
            if aligned is not None and not aligned >= set(self.fighters):
                self.ready &= set(self.fighters)
                return
        self.ready &= set(self.fighters)
        if len(self.fighters) == 2 and self.ready >= set(self.fighters):
            self._start_countdown(game)

    def _start_countdown(self, game: GameState) -> None:
        for player_id in self.fighters:
            player = game.add_player(player_id)
            player.hp = game.tuning.max_hp
            player.item = Item.NONE
            player.cooldown_until = 0.0
            player.sword_tip = None
            player.sword_hits.clear()
            player.sword_locked_until = 0.0
            player.shield_boost = 0.0
        game.projectiles.clear()
        self._clear_pause()
        self.pauses_used.clear()
        self.time_left = self.duration_s
        self.countdown = self.rules.countdown_s
        self.phase = Phase.COUNTDOWN
        log.info("match starting: %s", " vs ".join(self.fighters))

    def _step_playing(self, game: GameState, dt: float) -> None:
        hp = {f: game.players[f].hp if f in game.players else 0.0 for f in self.fighters}
        defeated = [f for f, value in hp.items() if value <= 0.0]
        if defeated:
            standing = [f for f in self.fighters if f not in defeated]
            self._end(standing[0] if len(standing) == 1 else None, p.MatchEndReason.KO)
            return
        if not self.sudden_death:
            self.time_left = max(0.0, self.time_left - dt)
            if self.time_left > 0.0:
                return
        leader = max(hp, key=hp.__getitem__)
        if all(value == hp[leader] for value in hp.values()):
            self.sudden_death = True
            return
        self._end(leader, p.MatchEndReason.TIME)

    def _step_pause(self, dt: float) -> None:
        if self.resume_in > 0.0:
            self.resume_in -= dt
            if self.resume_in <= 0.0:
                self._clear_pause()
            return
        self.pause_left_s -= dt
        if self.pause_left_s <= 0.0:
            self.resume_in = self.rules.resume_countdown_s

    def _clear_pause(self) -> None:
        self.paused_by = None
        self.pause_left_s = self.resume_in = 0.0
        self.restart_votes.clear()

    def _end(self, winner: str | None, reason: str, ended_by: str | None = None) -> None:
        self._clear_pause()
        self.phase = Phase.ENDED
        self.countdown = 0.0
        self.winner, self.reason, self.ended_by = winner, reason, ended_by
        log.info("match over (%s): %s", reason, f"{winner} wins" if winner else "no winner")

    def _clear_result(self) -> None:
        self.sudden_death = False
        self.winner = self.reason = self.ended_by = None
        self.countdown = 0.0

    def _to_lobby(self) -> None:
        self._clear_result()
        self.phase = Phase.LOBBY
        self.mode = self.owner = None
        self.sword_only = False
        self.fighters = []
        self.ready.clear()
        self.duration_s = self.time_left = 0.0
