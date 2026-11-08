# server: authoritative game server

The game server from [architecture.md](../../architecture.md) §2.3. Python 3.11+ and `asyncio`.

- TCP on 9000: `hello` handshake, pairing mode for bands (§5), the shared room frame (§5.1: anchor host, `space`, `aligned`), and a 30 Hz tick that broadcasts `pose`, `state` and events.
- A paired band's `gesture` messages (its built-in decoded taps, swipes and pinches) are relayed straight to every headset.
- UDP discovery beacon `SPELLGAME <port>` on 47777 (§4.1).
- Game logic in `spellgame/game_state.py`, a pure `GameState.step(inputs, dt)` with no networking. Fireball is implemented (§9); sword and shield are next.
- `spellgame/protocol.py` holds the shared message dataclasses; the hand-sign client should import it rather than redefine messages.

## Setup

```bash
cd apps/server
uv sync
```

## Run

```bash
uv run python -m spellgame                 # --port, --tick-hz, --no-beacon, --no-tui, -v
```

The server opens a live monitor (Textual): connected headsets and hand clients side by side, each with its player ID,
address, the device it reported in `hello`, and its most recent incoming packets; the log runs underneath. `p` starts pairing mode, `a` re-anchors the shared room frame (§5.1), `q` quits. Each headset shows whether it is aligned and whether it hosts the anchor.
`--no-tui` logs to stderr instead.

Without a headset or a band, the fake clients stand in for them (each finds the server via the beacon, or pass `--host`):

```bash
uv run python -m spellgame.tools.fake_vr --position 0,0 --facing 0 --throw-every 2   # P1, throws every 2 s
uv run python -m spellgame.tools.fake_vr --position 0,3 --facing 180                 # P2, stands 3 m away
uv run python -m spellgame.tools.fake_band --pinch-on-prompt --snap-every 2          # a band, snaps every 2 s
```

Bands connect unpaired. Press `p` in the server's monitor (or have any client send `pair_start`) to start pairing mode:
the server prompts each headset without a band in join order, and the next band to pinch pairs with the prompted player.
The monitor shows who is being prompted. `--pinch-on-prompt` makes `fake_band` pinch on every prompt until it's
paired. Without `--snap-every`, `fake_band` reads gestures from stdin: `s` snap, `f` fist, `p` open palm, `n` none,
`i` pinch. `fake_vr` prints the `spell`, `damage` and `impact` events it receives. It also plays its part in §5.1: as anchor host it shares a made-up anchor, then reports itself aligned (`--align floor_spots` uses the fallback, `--align none` never aligns).

## Test

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Layout

```
spellgame/
  protocol.py     wire messages (§4.2, §6), NDJSON encode/decode
  server.py       TCP connections, pairing, tick loop, broadcast
  shared_space.py shared room frame (§5.1): anchor host, current anchor, floor spots, who is aligned
  discovery.py    UDP beacon + client-side find_server() / discover_servers()
  game_state.py   simulation: gesture state machines, projectiles, hits, damage; Tuning constants
  geometry.py     segment distance, body facing, quaternion rotation (Unity frame)
  sim.py          synthetic poses and throw motion for fake clients and tests
  client.py       client connection helpers
  tui.py          live monitor: connected clients, device info, recent packets, log
  tools/          fake_vr.py, fake_band.py
```
