# server: authoritative game server

The game server from [architecture.md](../../architecture.md) §2.3. Python 3.11+ and `asyncio`.

- TCP on 9000: `hello` handshake, join-order band pairing (§5), and a 30 Hz tick that broadcasts `pose`, `state` and events.
- A paired band's `gesture` messages (its built-in decoded taps, swipes and pinches) are relayed straight to every headset.
- UDP discovery beacon `SPELLGAME <port>` on 47777 (§4.1).
- Game logic in `spellgame/game_state.py`, a pure `GameState.step(inputs, dt)` with no networking. Fireball is implemented (§9); sword and shield are next.
- `spellgame/protocol.py` holds the shared message dataclasses; the hand-sign client should import it rather than redefine messages.

## Setup

```bash
cd apps/server
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Run

```bash
.venv/bin/python -m spellgame                 # --port, --tick-hz, --no-beacon, --no-tui, -v
```

The server opens a live monitor (Textual): connected headsets and hand clients side by side, each with its player ID,
address, the device it reported in `hello`, and its most recent incoming packets; the log runs underneath. `q` quits.
`--no-tui` logs to stderr instead.

Without a headset or a band, the fake clients stand in for them (each finds the server via the beacon, or pass `--host`):

```bash
.venv/bin/python -m spellgame.tools.fake_vr --position 0,0 --facing 0 --throw-every 2   # P1, throws every 2 s
.venv/bin/python -m spellgame.tools.fake_band --snap-every 2                            # P1's band, snaps every 2 s
.venv/bin/python -m spellgame.tools.fake_vr --position 0,3 --facing 180                 # P2, stands 3 m away
```

Start them in that order so join-order pairing gives the band to P1. Without `--snap-every`, `fake_band` reads gestures
from stdin: `s` snap, `f` fist, `p` open palm, `n` none. `fake_vr` prints the `spell`, `damage` and `impact` events it receives.

## Test

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

## Layout

```
spellgame/
  protocol.py     wire messages (§4.2, §6), NDJSON encode/decode
  server.py       TCP connections, pairing, tick loop, broadcast
  discovery.py    UDP beacon + client-side find_server() / discover_servers()
  game_state.py   simulation: gesture state machines, projectiles, hits, damage; Tuning constants
  geometry.py     segment distance, body facing, quaternion rotation (Unity frame)
  sim.py          synthetic poses and throw motion for fake clients and tests
  client.py       client connection helpers
  tui.py          live monitor: connected clients, device info, recent packets, log
  tools/          fake_vr.py, fake_band.py
```
