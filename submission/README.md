# Devpost submission (draft)

- `pitch.md` — short pitch, under 250 words. Architecture and the rest get added later.
- `diagrams/architecture-tldraw-ken.png` — Ken's original architecture sketch, exported from the [public tldraw board](https://www.tldraw.com/f/j9TtJhe8cWZyB6hVz3jwV?d=v-977.-580.3038.1929.page).
- `diagrams/system-architecture.svg` / `.png` — cleaned-up system design: band → Kinesis → hand client → authoritative server ↔ Quest AR clients.
- `diagrams/game-systems.svg` / `.png` — how spells, tension, hit testing and the match work on the server, and how the Unity client is organised.

Numbers in the diagrams come from the code on `main`: `apps/server/spellgame/game_state.py` (`Tuning`), `match.py`, `server.py`, `apps/hand-client/handclient/tension.py`, `models/neural-emg-04/model.json`, and the Unity scripts under `apps/vr-client/Assets/SpellGame/Runtime/`. Edit the SVGs and re-export the PNGs if any of those change.
