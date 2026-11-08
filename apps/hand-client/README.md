# hand-client: Neural Band → game server

The hand-sign classification client from [architecture.md](../../architecture.md) §2.2. It runs on the Mac running Kinesis, reads the band through Kinesis's local sensor feed, and sends the band's gestures (and, once a model exists, hand signs) to the game server.

## Setup

```bash
cd apps/hand-client
uv sync
```

`uv sync` installs `apps/server` as an editable dependency. It imports `spellgame.protocol`, `spellgame.client` and `spellgame.discovery` from `apps/server`, so messages can't drift.

## Run

1. Start the patched Kinesis from [`apps/kinesis-axo`](../kinesis-axo) (unzip `release/Kinesis-haptics-arm64.zip`) and pair the band. On the **band** page, pick the wrist it's on.
2. On the **stream** tab, enable **local sensor feed** and **copy stream URL**. The URL changes every time the feed restarts.
3. Run the client, then pick a game server from the list (or type `IP[:port]`):

```bash
uv run python -m handclient                                  # prompts for the Kinesis URL, then the server
uv run python -m handclient --kinesis-url 'URL' --host 10.0.0.5   # no prompts
```

The client connects unpaired. To pair, start pairing mode on the server (`p` in its monitor): when the server prompts your headset's player, pinch your index or middle finger to your thumb.

## What it does

| Thread | Job |
|---|---|
| Kinesis reader (`kinesis_feed.py`) | Holds the SSE connection, parses events. It only reads, because Kinesis drops a reader that falls 1 s behind. Reconnects if the feed drops; exits if Kinesis rejects the URL (feed restarted). |
| Classifier (`emg_classifier.py`) | Consumes EMG batches. The model is the injected `EmgClassifier`; for now it's `EmgLogger`, which logs rate, sequence gaps and per-channel means once a second. |
| Haptics sender (`kinesis_haptics.py`) | Turns the server's `haptic` messages into `POST /haptics?token=…&ms=…` on Kinesis, using the feed URL's token. Needs the patched Kinesis in [`apps/kinesis-axo`](../kinesis-axo). |
| asyncio loop (`main.py`, `server_link.py`) | Holds the game server TCP connection (reconnects and reclaims its player ID), and routes everything: band gestures are cleaned (`band_gestures.py`: synthetic and raw/derived duplicates dropped) and sent as `gesture` messages once paired, or as `pinch` while unpaired. Signs go out as `sign`. |

## Test

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
MYPYPATH=../server uv run mypy -p handclient --check-untyped-defs
```

`tests/fake_kinesis.py` stands in for Kinesis's feed, so the tests need no band.
