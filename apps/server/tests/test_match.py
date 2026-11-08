import pytest

from spellgame import protocol as p
from spellgame.game_state import GameState, Item
from spellgame.match import Match

DT = 0.1
BOTH = ["P1", "P2"]


def setup_versus(duration_s=60.0):
    game, match = GameState(), Match()
    for player_id in BOTH:
        game.add_player(player_id)
    assert match.setup("P1", p.MatchMode.VERSUS, duration_s) is None
    return game, match


def start(game, match, headsets=BOTH):
    match.step(game, headsets, DT)
    for player_id in match.fighters:
        match.set_ready(player_id, True)
    match.step(game, headsets, DT)
    assert match.phase == p.MatchPhase.COUNTDOWN
    run(game, match, match.rules.countdown_s + DT, headsets)
    assert match.phase == p.MatchPhase.PLAYING


def run(game, match, seconds, headsets=BOTH):
    for _ in range(round(seconds / DT)):
        match.step(game, headsets, DT)


def test_versus_waits_for_both_players_ready_then_counts_down_and_resets_the_fighters():
    game, match = setup_versus()
    match.step(game, ["P1"], DT)
    match.set_ready("P1", True)
    match.step(game, ["P1"], DT)
    assert match.phase == p.MatchPhase.READY
    assert match.snapshot().fighters == ["P1"]

    game.players["P1"].hp = 40.0
    game.players["P2"].item = Item.SWORD
    match.step(game, BOTH, DT)
    assert match.phase == p.MatchPhase.READY
    match.set_ready("P2", True)
    match.step(game, BOTH, DT)
    assert match.phase == p.MatchPhase.COUNTDOWN
    assert match.snapshot().ready == BOTH
    assert game.players["P1"].hp == game.tuning.max_hp
    assert game.players["P2"].item == Item.NONE

    run(game, match, 2.0)
    assert match.phase == p.MatchPhase.COUNTDOWN
    assert match.snapshot().countdown == pytest.approx(1.0, abs=DT)
    assert match.snapshot().time_left == 60.0
    run(game, match, 1.1)
    assert match.phase == p.MatchPhase.PLAYING
    run(game, match, 10.0)
    assert match.snapshot().time_left == pytest.approx(50.0, abs=2 * DT)


def test_versus_countdown_waits_for_both_fighters_to_be_aligned():
    game, match = setup_versus()
    for player_id in BOTH:
        match.set_ready(player_id, True)
    match.step(game, BOTH, DT, aligned={"P1"})
    assert match.phase == p.MatchPhase.READY
    assert match.snapshot().ready == BOTH
    match.step(game, BOTH, DT, aligned=set(BOTH))
    assert match.phase == p.MatchPhase.COUNTDOWN


def test_solo_does_not_need_the_shared_frame():
    game, match = GameState(), Match()
    game.add_player("P1")
    assert match.setup("P1", p.MatchMode.SOLO, 60.0) is None
    match.set_ready("P1", True)
    match.step(game, ["P1"], DT, aligned=set())
    assert match.phase == p.MatchPhase.COUNTDOWN


def test_unreadying_holds_the_countdown():
    game, match = setup_versus()
    match.step(game, BOTH, DT)
    match.set_ready("P1", True)
    match.set_ready("P1", False)
    match.set_ready("P2", True)
    match.step(game, BOTH, DT)
    assert match.phase == p.MatchPhase.READY


def test_knockout_ends_the_match_at_once():
    game, match = setup_versus()
    start(game, match)
    game.players["P2"].hp = 0.0
    match.step(game, BOTH, DT)
    snapshot = match.snapshot()
    assert (snapshot.phase, snapshot.winner, snapshot.reason) == (p.MatchPhase.ENDED, "P1", p.MatchEndReason.KO)


def test_time_out_goes_to_the_higher_hp_and_a_tie_to_sudden_death():
    game, match = setup_versus(duration_s=10.0)
    start(game, match)
    game.players["P1"].hp = 30.0
    run(game, match, 10.5)
    assert (match.winner, match.reason) == ("P2", p.MatchEndReason.TIME)

    match.rematch()
    assert match.phase == p.MatchPhase.READY and match.winner is None
    start(game, match)
    run(game, match, 10.5)
    assert match.phase == p.MatchPhase.PLAYING and match.sudden_death
    assert match.snapshot().time_left == 0.0
    game.players["P1"].hp -= 8.0
    match.step(game, BOTH, DT)
    assert (match.phase, match.winner) == (p.MatchPhase.ENDED, "P2")


def test_quit_ends_the_match_and_quitting_the_results_returns_to_the_lobby():
    game, match = setup_versus()
    start(game, match)
    match.quit("P2")
    snapshot = match.snapshot()
    assert (snapshot.phase, snapshot.reason, snapshot.ended_by, snapshot.winner) == (
        p.MatchPhase.ENDED,
        p.MatchEndReason.QUIT,
        "P2",
        None,
    )
    match.quit("P1")
    assert match.snapshot() == p.MatchSnapshot()


def test_a_fighter_disconnecting_ends_the_match_for_the_other():
    game, match = setup_versus()
    start(game, match, headsets=["P1", "P2", "P3"])
    assert match.fighters == BOTH
    match.step(game, ["P1", "P3"], DT)
    assert (match.phase, match.winner, match.reason) == (p.MatchPhase.ENDED, "P1", p.MatchEndReason.DISCONNECT)


def test_solo_pairs_the_owner_with_the_ai_which_is_always_ready():
    game, match = GameState(), Match()
    game.add_player("P2")
    assert match.setup("P2", p.MatchMode.SOLO, 120.0) is None
    assert match.ai_id == p.AI_PLAYER_ID
    match.step(game, ["P1", "P2"], DT)
    assert match.snapshot().fighters == ["P2", p.AI_PLAYER_ID]
    assert match.snapshot().ready == [p.AI_PLAYER_ID]
    match.set_ready("P1", True)
    match.set_ready("P2", True)
    match.step(game, ["P1", "P2"], DT)
    assert match.phase == p.MatchPhase.COUNTDOWN
    assert match.duration_s == 120.0


def test_solo_owner_leaving_the_ready_screen_returns_to_the_lobby():
    game, match = GameState(), Match()
    match.setup("P1", p.MatchMode.SOLO, 60.0)
    match.step(game, [], DT)
    assert match.phase == p.MatchPhase.LOBBY and match.ai_id is None


def test_casting_is_practice_in_menus_and_only_for_fighters_while_playing():
    game, match = setup_versus()
    assert match.can_cast("P3")
    start(game, match, headsets=["P1", "P2", "P3"])
    assert match.can_cast("P1") and not match.can_cast("P3")
    match.quit("P1")
    assert not match.can_cast("P1")


def test_countdown_blocks_casting():
    game, match = setup_versus()
    match.step(game, BOTH, DT)
    match.set_ready("P1", True)
    match.set_ready("P2", True)
    match.step(game, BOTH, DT)
    assert match.phase == p.MatchPhase.COUNTDOWN and not match.can_cast("P1")


def test_defeated_players_respawn_outside_a_match():
    game, match = GameState(), Match()
    game.add_player("P1").hp = 0.0
    match.step(game, ["P1"], DT)
    assert game.players["P1"].hp == game.tuning.max_hp


def test_setup_is_rejected_mid_match_or_with_an_unknown_mode_and_duration_is_clamped():
    game, match = setup_versus(duration_s=5000.0)
    assert match.duration_s == match.rules.max_duration_s
    assert match.setup("P1", "teams", 60.0) is not None
    start(game, match)
    assert match.setup("P1", p.MatchMode.SOLO, 60.0) is not None


def test_ready_sent_straight_after_setup_counts_and_spectators_ready_is_ignored():
    game, match = GameState(), Match()
    match.setup("P1", p.MatchMode.SOLO, 60.0)
    match.set_ready("P1", True)
    match.set_ready("P3", True)
    match.step(game, ["P1", "P3"], DT)
    assert match.phase == p.MatchPhase.COUNTDOWN
    assert match.snapshot().ready == ["P1", p.AI_PLAYER_ID]


def test_pause_freezes_the_clock_is_limited_per_fighter_and_resumes_after_a_countdown():
    game, match = setup_versus()
    start(game, match)
    left = match.time_left
    match.pause("P1", True)
    assert match.paused and not match.can_cast("P1") and not match.can_cast("P2")
    run(game, match, 5.0)
    assert match.time_left == left
    match.pause("P2", False)
    run(game, match, match.rules.resume_countdown_s - DT)
    assert match.paused
    run(game, match, 2 * DT)
    assert not match.paused and match.can_cast("P2")
    match.pause("P1", True)
    match.pause("P1", False)
    run(game, match, match.rules.resume_countdown_s + DT)
    match.pause("P1", True)
    assert not match.paused
    assert match.snapshot().pauses_left == [0, 2]


def test_a_pause_runs_out_by_itself():
    game, match = setup_versus()
    start(game, match)
    match.pause("P2", True)
    run(game, match, match.rules.max_pause_s + match.rules.resume_countdown_s + 2 * DT)
    assert not match.paused and match.phase == p.MatchPhase.PLAYING


def test_restart_needs_every_fighter_and_starts_a_fresh_countdown():
    game, match = setup_versus()
    start(game, match)
    game.players["P2"].hp = 10.0
    run(game, match, 5.0)
    match.vote_restart("P1", game)
    assert match.phase == p.MatchPhase.PLAYING and match.snapshot().restart_votes == ["P1"]
    match.vote_restart("P2", game)
    assert match.phase == p.MatchPhase.COUNTDOWN
    assert game.players["P2"].hp == game.tuning.max_hp and match.time_left == match.duration_s
    assert match.snapshot().restart_votes == []


def test_solo_restart_is_immediate():
    game, match = GameState(), Match()
    game.add_player("P1")
    match.setup("P1", p.MatchMode.SOLO, 60.0)
    start(game, match, ["P1"])
    match.vote_restart("P1", game)
    assert match.phase == p.MatchPhase.COUNTDOWN
