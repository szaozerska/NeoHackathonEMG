# Spell-Casting Game: System Architecture Spec

Diagram: https://www.tldraw.com/f/j9TtJhe8cWZyB6hVz3jwV?d=v-977.-580.3038.1929.page

**How to read this spec:**
- **Binding:** the shape of the system:
  - which components exist and what each one is responsible for;
  - what flows between them (§3);
  - the transports, including TCP for game traffic and the UDP discovery beacon (§4, §4.1);
  - the server-authoritative model;
  - the shared player ID (§5).
  
  Any implementation must preserve these.
- **Recommended, not binding:** the libraries and implementation choices in the **Stack** and **Data collection** items of §2.2 (classifier) and §2.3 (server). Swap them out if something else works better.
- **(default):** values that are proposed starting points rather than decisions, such as ports, framing, message fields, and rates. Change them freely.

## 1. Overview

A multiplayer mixed-reality (passthrough AR) spell-casting game.

- **Meta Quest 3** tracks each player's body.
- **Meta Neural Band** reads the player's forearm EMG, and an ML classifier on a Mac turns it into hand signs.
- **One authoritative game server** on a Mac combines both inputs, runs all game mechanics, and sends the resulting state back to every headset.

There is one Quest, one Neural Band, and one classification Mac per player, plus one shared server Mac. Everything runs on one local network.

## 2. Components

### 2.1 Meta Quest 3: AR client (Unity, passthrough; called the VR client / role `vr` in code and protocol)
- **Inputs:**
  - Built-in camera tracking through Meta's Movement SDK (full-body tracking, legs estimated): hands, wrists, elbows, shoulders, chest, hips, knees, ankles, feet.
- **Responsibilities:**
  - Find the game server on the LAN (§4.1), then open a TCP connection to it.
  - Stream position/pose packets (body and arms) to the server.
  - Receive **all** game-state packets (pose, hand sign, damage) and render them.
  - Process **no** game mechanics.
  - Show the real room through passthrough; players see each other's real bodies, so skeletons are debug lines only. The local skeleton comes from local tracking, other players' from the server.
- **Identity:** tagged with a player ID (§5).

### 2.2 Hand sign classification client (Mac, one per player)
- **Inputs from the Neural Band** (via Axo's Kinesis app, Bluetooth → Kinesis → local feed):
  - Raw EMG: 8 channels, 2,048 Hz, 16-bit unsigned ADC counts, sent in batches of 16 samples. The values are uncalibrated and unfiltered.
  - Wrist rotation quaternion `[w, x, y, z]`, ~128 Hz.
  - Also available but optional: gyro, and the band's built-in decoded gestures, which make a useful baseline or fallback.
- **Data access:**
  - Kinesis serves Server-Sent Events at `http://127.0.0.1:8766/events?token=…`.
  - The feed is loopback-only, so the classifier **must run on the same Mac as Kinesis**.
  - Kinesis allows at most 4 readers per feed.
  - A slow reader is disconnected, so read the feed on a dedicated thread.
  - The URL and token change every time the feed is restarted.
- **Responsibilities:**
  - Run the ML hand sign classifier on windows of EMG, using the wrist quaternion as an extra feature.
  - Find the server (§4.1) and open a TCP connection to it.
  - Send **current hand sign** packets to the server.
  - **Optional:** send **wrist orientation** packets, used only if the headset's arm tracking proves inaccurate. The band provides rotation only, not position.
- **Identity:** tagged with the **same player ID** as that player's Quest (§5).
- **Requirements:** macOS 14+ on Apple Silicon (for the packaged Kinesis build), and the band paired and enrolled via Meta sign-in in Kinesis.
- **Stack (recommended):** Python 3 with a classical EMG pipeline. Hand-built features plus a simple model beat deep learning when there is little labeled data and only one or two users.
  - **Feed reader:** standard-library `urllib` reading the SSE stream line by line, on its own thread, pushing EMG batches into a ring buffer (`collections.deque` or a preallocated `numpy` array).
  - **Preprocessing (`scipy.signal`):**
    - Subtract the per-channel mean (the raw counts are unsigned and not centered).
    - Band-pass 20–450 Hz (`butter` + `sosfilt`).
    - Notch at 60 Hz (`iirnotch`).
    - Use streaming filters with persistent state (`sosfilt` with `zi`) so windows join without edge artifacts.
  - **Windowing:** ~150–250 ms windows with a ~50 ms hop, giving a prediction every 50 ms.
  - **Features (`numpy`):** per channel, RMS, mean absolute value, waveform length, zero crossings, and slope-sign changes (8 × 5 = 40 features). Optionally append the wrist quaternion.
  - **Model (`scikit-learn`):**
    - Baseline: LDA.
    - Next to try: `RandomForestClassifier` or `LogisticRegression`.
    - Wrap scaling and the model in a `Pipeline`; save and load it with `joblib`.
  - **Output smoothing:** a majority vote over the last 3–5 predictions plus a confidence threshold before a `sign` packet changes. This is our own code, not a library.
  - **Debug plotting:** `pyqtgraph` for live 8-channel plots; `matplotlib` for offline analysis.
  - **Stretch goal:** a small 1D CNN on raw windows in `PyTorch`, only if the baseline plateaus. It needs much more data.
- **Data collection (recommended):**
  - A recording script prompts the player ("make sign X") and saves labeled windows to `.npz` files, including rest and `none` samples.
  - Recalibrate every session, because the EMG shifts whenever the band is taken off and put back on.

### 2.3 Game server (Mac)
- **Authoritative.** Runs the entire game simulation; clients only send inputs and render state.
- **Responsibilities:**
  - Accept TCP connections from all VR clients and classification clients.
  - Merge each player's pose stream and hand sign stream using the shared player ID.
  - Track the state of complex spells, such as charge-ups that span several frames or several signs.
  - Resolve hits and damage.
  - Broadcast all packets (pose, hand sign, damage) to every VR client.
  - Run the UDP discovery beacon (§4.1).
- **Scale:** 2 players, so performance is not a constraint.
- **Stack (recommended):** Python 3 with `asyncio`, using the standard library.
  - **Why:** the classifier is also Python, so both can share one `protocol.py` (message dataclasses plus JSON encode/decode) and the message format can't drift between them.
- **Structure:**
  - `asyncio.start_server` handles TCP connections, with one reader task per connection that writes into per-player latest-state slots.
  - A fixed-tick loop: `step()`, then broadcast, then `await asyncio.sleep(dt)`.
  - An `asyncio` `DatagramProtocol` runs the discovery beacon.
  - Everything is single-threaded, so no locks are needed.
  - Game logic is a pure function `game_state.step(inputs, dt) -> events`, kept separate from networking, so spell and charge logic can be unit-tested with fake inputs.
- **Libraries:**
  - `numpy` for vector math in hit detection (e.g. a ray or sphere from the caster's hand tested against the target's chest capsule).
  - `dataclasses` or `pydantic` for the message schema.
- **Alternatives:**
  - **C# / .NET console app:** lets the server share message classes with the Unity client, but loses code sharing with the classifier.
  - **Headless Unity build:** worth it if hit detection needs real geometry, such as walls, shield colliders, or projectiles colliding with the arena, because it gets Unity's physics engine. The cost is slower iteration.

### 2.4 Meta Neural Band
- A wrist-worn surface-EMG band (it reads muscle signals, not brain signals).
- Pairs with the classification Mac over Bluetooth through Kinesis. It does **not** connect to the Quest.

## 3. Data flows

| # | From → To | Transport | Payload | Rate |
|---|---|---|---|---|
| F1 | Quest cameras → VR client | On-device SDK | Hand pos/dir, wrists, elbows, shoulders, chest | Tracking rate |
| F2 | Neural Band → Kinesis (Mac) | Bluetooth | EMG, wrist quaternion, gyro, gestures | 2,048 Hz EMG / 128 Hz motion |
| F3 | Kinesis → classifier | HTTP SSE on loopback | Same as F2, as timestamped JSON | Same as F2 |
| F4 | VR client → server | TCP | Position/pose packet | 30–60 Hz **(default)** |
| F5 | Classifier → server | TCP | Current hand sign packet | On change, plus 10 Hz heartbeat **(default)** |
| F6 | Classifier → server *(optional)* | TCP | Wrist orientation packet | 30–60 Hz **(default)** |
| F7 | Server → every VR client | TCP | All state: pose, hand sign, damage | Server tick, 30–60 Hz **(default)** |
| F8 | Server → LAN | UDP broadcast | Discovery beacon | 1 Hz |

## 4. Networking

- **Transport:**
  - All game traffic is **TCP over LAN**.
  - The **only** exception is the discovery beacon, which is UDP broadcast.
  - Set `TCP_NODELAY` on every socket.
- **Framing (default):** newline-delimited JSON, one message per line.
- **Ports (default):** UDP `47777` for discovery, TCP `9000` for game traffic.
- **Network:** use a dedicated travel router or a laptop hotspot. Venue Wi-Fi often blocks device-to-device traffic (client isolation), which would kill both the TCP connections and the broadcast.

### 4.1 Server discovery
1. The server broadcasts `SPELLGAME <tcp_port>` to `255.255.255.255:47777` once per second.
2. Each client listens on UDP 47777 and takes the server IP from the packet's **sender address** and the port from the payload.
3. The client then connects over TCP.
4. The Quest client may need an Android `WifiManager.MulticastLock` to receive broadcasts.
5. Every client keeps a manual IP entry as a fallback.

### 4.2 Connection handshake (default)
The first message on every TCP connection:
```json
{"type":"hello","role":"vr"|"classifier"}
```
- **VR client:** the server replies `{"type":"welcome","player_id":"P1"}`.
- **Classifier:** the server replies `{"type":"welcome","player_id":null}`, then sends `{"type":"paired","player_id":"P1"}` once pairing completes (§5).
- While a classifier is unpaired, it sends only `pinch` messages and no `sign` packets.

## 5. Player identity

- Every player has one ID, shared by their VR client and their classification client.
- The server uses this ID to link the two streams to one player.
- The server assigns player IDs in the order the headsets join: `P1`, `P2`, and so on. Each headset shows its own ID.
- **Pairing a Neural Band with a headset** uses one of two methods (which one is still open, §8):
  1. **Join order:**
     - Player 1 joins with their headset, then connects their band's classification client; then player 2 does the same, and so on.
     - The server pairs each newly connected classifier with the most recently joined headset that has no band yet.
  2. **"Pair Neural Bands" screen:**
     - Triggered from the game server or a Quest controller.
     - The server prompts player 1 to pinch their fingers, then player 2, and so on.
     - The first classifier to report a pinch (using the band's built-in decoded `gesture` events, so no trained model is needed) is paired with the player currently being prompted.
- With either method, classifier clients connect **unpaired** and receive their player ID from the server once paired.

## 6. Message types (default schema)

| Type | Direction | Fields |
|---|---|---|
| `hello` / `welcome` / `error` | client ↔ server | see §4.2. `hello` may carry an optional `player_id`: a VR client reclaims its ID after a reconnect; a classifier pairs directly with that player |
| `pinch` | classifier → server | `t`, `hand` (sent during the pairing screen) |
| `pair_start` / `pair_prompt` / `paired` | server → VR and classifier | `pair_prompt`: `player_id` currently being prompted; `paired`: `player_id` |
| `pose` | VR → server, server → VR | `player_id`, `t`, `joints{head, chest, hips, l/r_shoulder, l/r_elbow, l/r_wrist, l/r_hand, l/r_knee, l/r_ankle, l/r_foot}` each `{pos:[x,y,z], rot:[w,x,y,z], vel?:[x,y,z]}`. `hips` is needed for the sword draw; legs come from full-body tracking (estimated by the Quest runtime) and are for debugging and display only; `vel` (optional, measured on the headset) gives cleaner hand speed than the server's finite difference |
| `sign` | classifier → server | `player_id`, `t`, `hand` (`left`/`right`, the hand wearing the band), `sign` (`fist`, `open_palm`, `snap` or `none`), `confidence`. `snap` is momentary: the server acts on the transition into it |
| `wrist` *(optional)* | classifier → server | `player_id`, `t`, `hand`, `rot:[w,x,y,z]` |
| `spell` | server → VR | `caster_id`, `spell`, `state` (`charging`/`cast`/`cancelled`/`sheathed`), `charge` (0–1), `origin`, `direction`. Lifecycle events; continuous state is in `state`. Fireball: `charging` on snap, `cast` on throw, `cancelled` on fizzle. Sword: `cast` on draw, `sheathed` on release |
| `state` | server → VR, every tick | `tick`, `players[{player_id, hp, connected, band_paired, sign, item, band_hand, cooldown, shield_boost}]` (`cooldown`: seconds until the player can conjure again; `shield_boost`: 0–1 push power, a sword contact at ≥ 0.3 is a parry), `projectiles[{id, kind, owner_id, pos, vel}]` |
| `impact` | server → VR | `projectile_id` (0 for sword contacts), `kind`, `owner_id`, `pos`, `reason` (`hit`/`blocked`/`expired` for fireballs; `blocked`/`parried` for swords), `target_id` (player hit or shielding) |
| `damage` | server → VR | `target_id`, `source_id`, `amount`, `hp_after`, `kind` (`fireball`/`sword`), `pos` (where the hit landed) |

Timestamps (`t`) are sender-local and used only for ordering within one stream. Never compare the band's clock, a Mac clock, and the Quest clock directly.

## 7. Constraints and known limitations

- The band provides **wrist rotation only, not position**. All position data comes from the Quest.
- Quest elbow and shoulder positions are partly inferred. Hands drop out of tracking when they leave the cameras' view.
- One player needs one Mac running Kinesis with one band.
- TCP head-of-line blocking can delay pose updates under packet loss. This is acceptable on a clean LAN; if it isn't, the fallback is to move `pose` to UDP.
- End-to-end sign latency adds up from: EMG window length + classifier inference + TCP + server tick + TCP back to the headset. Measure each stage early.

## 8. Open decisions

- The hand sign vocabulary, and the spell grammar (which signs, sequences, and charge rules make which spells).
- What EMG detects that the Quest's own hand tracking can't (occlusion, grip tension, charge intensity). This decides whether EMG is the primary input or a fallback.
- Which band-to-headset pairing method to use: join order, or the pinch-to-pair screen (§5).
- Server tick rate and pose send rate.
- Whether the optional `wrist` stream is needed at all.
- How much geometry spells need. This decides between the Python server and a headless Unity server (§2.3).

## 9. Gestures (default)

- The band hand does one gesture at a time. Finger and wrist state comes from the band (`sign`); arm motion comes from the Quest (`pose`).
- Players share one physical room, so both headsets must agree on one coordinate frame (Meta colocation + Shared Spatial Anchors; fallback: recenter on marked floor spots). The server assumes poses arrive in that shared frame.
- Each gesture is a server-side state machine over the band sign and a short history of the band hand's pose.

| Gesture | Band | Quest | Server behaviour |
|---|---|---|---|
| **Fireball** (implemented) | `snap` | Throw: hand speed ≥ 2.5 m/s, mostly along the body's facing | Snap conjures a held fireball. The throw releases it at the hand with the peak hand velocity's direction (light aim assist), as a projectile hit-tested against a head-to-hips capsule. Held fireballs fizzle after 8 s |
| **Sword** | `fist` held | Fist starts near the left hip, then pulls up diagonally | Drawn while the fist is held, gone on release. Blade capsule along the hand; damage scales with tip speed |
| **Shield** | `open_palm` held | Palm facing away from the player; push impulse = peak push speed | Raised shield blocks; a forceful push gives a short power boost, and a sword contact during the boost is a parry |

Tuning values live in `apps/server/spellgame/game_state.py` (`Tuning`).

**Starting balance (default):** 100 HP; fireball 8 damage, flying at 6–10 m/s so it can be seen, dodged or blocked across a 3–5 m room. That is roughly 13 hits, or about a minute of steady exchange.

**Later versions:**
- Spells take time to charge up (e.g. holding a conjured fireball longer makes it stronger), driving `spell.charge`.
- Difficulty settings: selectable `Tuning` presets (HP, damage, spell speed, aim assist, cooldowns).
