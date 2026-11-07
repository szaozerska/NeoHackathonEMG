# AR Spell Game: Implementation Plan

Scope: how players see spells cast, how spells fly and hit, scoring, and the HUD/menus, on the Quest 3 passthrough client
(`apps/vr-client`) plus the matching mechanics in the authoritative server (`apps/server/spellgame/game_state.py`).
Shape of the system: [architecture.md](architecture.md).

**Ground rules**
- The server decides what exists and what hits; the client only renders (architecture.md §2.3).
- Your own held items (orb, sword, shield) follow **local** hand tracking, so they never lag behind your real hand. Remote
  players' items follow the server's poses.
- Band input is faked until the classifier lands: `python -m spellgame.tools.fake_band` (keys `s` snap, `f` fist,
  `p` open palm, `n` none) and `fake_vr` as a scripted opponent. The real classifier and teammates' pose/sign fusion
  plug in behind the same `sign` + `pose` messages.
- Every value below is a default in `Tuning`; change freely.

## Stage 1: three basic spells in AR (fake band input)

### 1a. Fireball (PR #2)
- **Snap** (`spell charging`): spark burst at the fingertips, then a flaming held orb on the band hand while
  `item == "fireball"`.
- **Throw** (`spell cast`): the orb leaves the hand as a projectile with a trail, drawn from `state.projectiles` and
  extrapolated with `vel` between ticks.
- `impact hit`: explosion. `impact expired` or a fizzle (8 s hold limit, `spell cancelled`): smoke puff.
- Cooldown: a shrinking ember on the hand (`players[].cooldown`).

### 1b. Sword
Server done (`_step_sword` in `game_state.py`, all values in `Tuning.sword_*`); Unity blade view still to do.
- **Draw:** `fist` that starts within about 20 cm of the hip opposite the band hand ("left pocket" for a right-hand band),
  then pulls up diagonally across the body at least about 30 cm within 0.6 s.
- **Release:** letting go of the fist removes the sword at once.
- **Blade:** about 0.9 m capsule along the hand. Damage scales with tip speed above a minimum, with a per-target re-hit
  cooldown so one swing can't hit every tick.
- **Visual:** glowing blade plus a swing trail that brightens with speed.
- **Server specifics:** pocket = hips moved 15 cm toward the side opposite the band hand. The pull counts from the last
  fist sample inside the pocket, ignores motion toward/away from the opponent, and must lie within 50° of the 45° up-and-
  across diagonal. The blade runs 0.9 m from the hand along the forearm (elbow → hand); the Unity view must draw it the
  same way. Damage: 6 at 2 m/s tip speed, rising to 15 at 8 m/s; below 2 m/s the blade touches without hurting. One hit
  per target per 0.5 s.
- **Events:** `spell {spell: sword, state: cast}` on draw, `state: sheathed` on release. Sword hits send `damage` with
  `kind: sword` and the contact `pos` (fireball damage now carries `kind`/`pos` too).

### 1c. Shield
Server: `_step_shield` in `game_state.py`, all values in `Tuning.shield_*`. Unity view still to do.
- **Server specifics:** the disc (0.3 m radius) sits 8 cm in front of the band hand, facing away from the chest through
  the hand (no hand-rotation dependency). Boost = hand speed along that normal, 0 at 1 m/s to 1 at 3 m/s, fading over
  0.3 s. Blocks only from the front. A sword touching the disc at boost ≥ 0.3 is parried: the sword is sheathed and the
  attacker can't redraw for 1.5 s. Otherwise a fast blade on the shield is `blocked` (no damage).
- **Raise:** `open_palm` with the palm facing away from the player (toward the opponent) raises a disc in front of the palm.
  It blocks fireballs and sword hits.
- **Push boost:** boost comes from the *impulse* of the push, not its distance: peak push speed along the palm normal over
  the last about 0.2 s, decaying over about 0.3 s.
- **Parry:** a sword contact during the boost knocks the attacker's sword away and briefly locks their draw.
- **Visual:** the disc pulses with boost strength, flashes on a block, and flashes bigger on a parry.

### Protocol additions (defaults)
- `item`: add `sword`, `shield`. Player state: add `shield_boost`.
- `impact.reason`: add `blocked`, `parried`. `spell` events also cover sword draw/sheath.

Each spell ships as one PR: server state machine + pytest (using `sim.py` motions), then the Unity view.

## Stage 2: aiming, flight and readable hit areas
- **Input contract** for teammates' fusion: band-hand position, velocity and rotation in the shared room frame, plus the
  current sign. Nothing in this stage depends on how the fusion is done.
- **Direction:** peak hand-velocity direction with aim assist (20° cone, 50%). Try blending in some head gaze, which is
  usually more forgiving in AR.
- **Flight:** straight line at 6–10 m/s, so a ball is in the air about 0.4–0.7 s across a 3–5 m room and players can
  dodge or shield.
- **Readability:**
  - A faint trajectory line and a target highlight while holding a fireball with the opponent inside the aim-assist cone.
  - A debug toggle that shows hit capsules, the shield disc and the sword capsule.
  - An impact marker where each spell landed.
- **Shared frame:** both headsets must share one coordinate frame. Meta colocation / Shared Spatial Anchors if available;
  fallback is "recenter on marked floor spot".

## Stage 3: health, scoring and the 1-minute match
Cadence: about one throw every 1.5–2 s, so 30–35 attempts a minute. At about 40% landing (dodges, blocks), that's
about 12–14 hits a minute.

| | Default |
|---|---|
| HP | 100 |
| Fireball | 8 damage (about 13 hits to win) |
| Sword | 6–15 damage by tip speed: close range, high risk, hard-countered by parry |
| Shield | Fully blocks a frontal fireball. No extra cost: the band hand does one gesture at a time, so shielding means not attacking |
| Match | 60 s. Lower HP at time-out loses; a tie goes to sudden death |

- The server owns the match phase (`countdown` / `playing` / `ended`), the time left and the winner.
- **Display:**
  - The opponent's HP bar floats above their real head.
  - Your own HP and the timer sit on a small panel on your off-hand wrist (more comfortable than head-locked).
  - Damage numbers appear at impact points, with a red edge vignette and a sound when you're hit.

## Stage 4: menus
- **Screens:**
  - Main menu: Play, Pair Bands, Calibrate shared space, Debug toggles.
  - Lobby/ready, then a 3-2-1 countdown.
  - Results: winner, damage dealt, accuracy, Rematch.
- **Input:** poke with the off hand (Meta Interaction SDK) and/or band pinch (the server already relays `gesture` messages
  to headsets).

## Later versions
- **Charge-up:** spells take time to charge (e.g. holding a conjured fireball longer makes it stronger), driving
  `spell.charge`.
- **Difficulty settings:** selectable `Tuning` presets (HP, damage, spell speed, aim assist, cooldowns), chosen from the menu.
- More spells, more complex versions of the three basic ones, and cosmetic modes.

## Verification
- Server: `cd apps/server && .venv/bin/python -m pytest && .venv/bin/ruff check .`
- Unity: compile on the dev Mac (Unity 6000.6.8f1), run **SpellGame → Rebuild Main Scene**, then Build And Run to the
  Quest over USB against a local server + `fake_band`.
