# hand-client: Neural Band → game server

The hand-sign classification client from [architecture.md](../../architecture.md) §2.2. It runs on the Mac running Kinesis, reads the band through Kinesis's local sensor feed, and sends the band's gestures (and, once a model exists, hand signs) to the game server.

## Setup

```bash
cd apps/hand-client
python3 -m venv .venv
.venv/bin/pip install -e ../server -e '.[dev]'
```

It imports `spellgame.protocol`, `spellgame.client` and `spellgame.discovery` from `apps/server`, so messages can't drift.

## Run

1. Start Kinesis and pair the band. On the **band** page, pick the wrist it's on.
2. On the **stream** tab, enable **local sensor feed** and **copy stream URL**. The URL changes every time the feed restarts.
3. Run the client, then pick a game server from the list (or type `IP[:port]`):

```bash
.venv/bin/python -m handclient                                  # prompts for the Kinesis URL, then the server
.venv/bin/python -m handclient --kinesis-url 'URL' --host 10.0.0.5   # no prompts
```

Pairing with a headset follows the server's join order (§5): join with the headset first.

## What it does

| Thread | Job |
|---|---|
| Kinesis reader (`kinesis_feed.py`) | Holds the SSE connection, parses events. It only reads, because Kinesis drops a reader that falls 1 s behind. Reconnects if the feed drops; exits if Kinesis rejects the URL (feed restarted). |
| Classifier (`emg_classifier.py`) | Consumes EMG batches. The model is the injected `EmgClassifier`; for now it's `EmgLogger`, which logs rate, sequence gaps and per-channel means once a second. |
| asyncio loop (`main.py`, `server_link.py`) | Holds the game server TCP connection (reconnects and reclaims its player ID), and routes everything: band gestures are cleaned (`band_gestures.py`: synthetic and raw/derived duplicates dropped) and sent as `gesture` messages once paired, or as `pinch` while unpaired. Signs go out as `sign`. |

## Test

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
MYPYPATH=../server .venv/bin/mypy -p handclient --check-untyped-defs
```

`tests/fake_kinesis.py` stands in for Kinesis's feed, so the tests need no band.
