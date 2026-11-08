"""Hand-sign classification client (architecture.md §2.2): Kinesis feed in, signs and band gestures out to the server.

Threads: the Kinesis reader (only reads, so Kinesis never drops us as a slow reader), the classifier, the haptics
sender (the server's `haptic` messages → Kinesis), and the asyncio loop, which owns the game server connection and all
routing. Both threads post into the loop's inbox, so routing
is single-threaded.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from spellgame.protocol import DISCOVERY_PORT, GAME_PORT

from .band_gestures import GestureCleaner
from .emg_classifier import ClassifierWorker, EmgClassifier, EmgLogger, NeuralSignClassifier, SignPrediction
from .kinesis_feed import BandGestureEvent, BandStatus, EmgBatch, FeedEvent, KinesisFeed, validate_feed_url
from .kinesis_haptics import HapticsWorker
from .server_link import ServerLink
from .server_picker import Server, pick_server
from .tension import CalibrationUpdate, TensionReading, TensionTracker

log = logging.getLogger("handclient")

DEFAULT_NEURAL_MODEL = Path(__file__).resolve().parents[3] / "models" / "neural-emg-05"

InboxItem = BandStatus | BandGestureEvent | SignPrediction | TensionReading | CalibrationUpdate


class BandInputRouter:
    """Tracks the band's status and forwards its gestures and the classifier's signs to the game server."""

    def __init__(self, link: ServerLink) -> None:
        self._link = link
        self._gestures = GestureCleaner()
        self._status: BandStatus | None = None

    async def run(self, inbox: asyncio.Queue[InboxItem]) -> None:
        while True:
            self.handle(await inbox.get())

    def handle(self, item: InboxItem) -> None:
        match item:
            case BandStatus():
                self._on_status(item)
            case BandGestureEvent():
                gesture = self._gestures.clean(item)
                if gesture is not None:
                    log.info("band gesture: %s %s", gesture.finger, gesture.action)
                    self._link.send_gesture(gesture, self._hand())
            case SignPrediction():
                self._link.send_sign(item, self._hand())
            case TensionReading():
                if self._status is not None and self._status.hand is not None:
                    self._link.send_tension(item, self._status.hand)
            case CalibrationUpdate():
                log.info("grip calibration: %s %.0f%%", item.phase, item.progress * 100)
                self._link.send_calibration(item)

    def _on_status(self, status: BandStatus) -> None:
        if status != self._status:
            log.info(
                "band %s, hand %s, EMG %s",
                "connected" if status.connected else "disconnected",
                status.hand,
                "active" if status.emg_active else "not active yet",
            )
        self._status = status

    def _hand(self) -> str:
        if self._status is None or self._status.hand is None:
            raise RuntimeError("Kinesis doesn't know which wrist the band is on: choose it on Kinesis's band page")
        return self._status.hand


async def run_in_thread(work: Callable[[threading.Event], None]) -> None:
    """Runs blocking `work(stop)` on a thread; `stop` is set when this task ends, including on cancellation."""
    stop = threading.Event()
    try:
        await asyncio.to_thread(work, stop)
    finally:
        stop.set()


async def run_hand_client(kinesis_url: str, server: Server, classifier: EmgClassifier) -> None:
    loop = asyncio.get_running_loop()
    inbox: asyncio.Queue[InboxItem] = asyncio.Queue()
    emg_batches: queue.Queue[EmgBatch] = queue.Queue()
    haptic_durations_ms: queue.Queue[int] = queue.Queue()

    def post(item: InboxItem) -> None:
        loop.call_soon_threadsafe(inbox.put_nowait, item)

    def on_feed_event(event: FeedEvent) -> None:
        if isinstance(event, EmgBatch):
            emg_batches.put(event)
        elif isinstance(event, (BandStatus, BandGestureEvent)):
            post(event)

    tension = TensionTracker()
    link = ServerLink(*server, on_haptic=haptic_durations_ms.put)
    feed = KinesisFeed(kinesis_url, on_feed_event)
    worker = ClassifierWorker(emg_batches, classifier, post, tension)
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(run_in_thread(feed.run))
        tasks.create_task(run_in_thread(worker.run))
        tasks.create_task(run_in_thread(HapticsWorker(kinesis_url, haptic_durations_ms).run))
        tasks.create_task(link.run())
        tasks.create_task(BandInputRouter(link).run(inbox))


def wait_for_kinesis_url() -> str:
    """Kinesis's stream URL, taken from the clipboard as soon as its "copy stream URL" puts it there (macOS; no
    terminal needed, so the server can start this client in the background). Elsewhere it's typed in."""
    if shutil.which("pbpaste") is None:
        return validate_feed_url(input("Paste the stream URL from Kinesis's stream tab: ").strip())
    log.info(
        "waiting for the Kinesis stream URL: in Kinesis's stream tab, "
        "enable the local sensor feed and click 'copy stream URL'"
    )
    while True:
        text = subprocess.run(["pbpaste"], capture_output=True, text=True, check=False).stdout.strip()
        with contextlib.suppress(ValueError):
            url = validate_feed_url(text)
            log.info("got the Kinesis stream URL from the clipboard")
            return url
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kinesis-url", type=validate_feed_url, help="the stream URL copied from Kinesis's stream tab")
    parser.add_argument("--host", help="game server IP; omit to pick from the servers found on the LAN")
    parser.add_argument("--port", type=int, default=GAME_PORT)
    parser.add_argument("--discovery-port", type=int, default=DISCOVERY_PORT)
    parser.add_argument("--discovery-s", type=float, default=2.5, help="how long to listen for server beacons")
    parser.add_argument(
        "--neural-model",
        default=str(DEFAULT_NEURAL_MODEL),
        help="trained neural EMG bundle that turns EMG into signs (default: models/neural-emg-05)",
    )
    parser.add_argument(
        "--snap-threshold",
        type=float,
        help="snap confidence needed to fire a fireball (default: the bundle's, 0.995 for neural-emg-05); "
        "0.999 roughly halves accidental snaps but misses more real ones",
    )
    parser.add_argument("--log-only", action="store_true", help="send no signs; only log the EMG stream")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(name)s %(message)s"
    )
    with contextlib.suppress(KeyboardInterrupt):
        kinesis_url = args.kinesis_url or wait_for_kinesis_url()
        server = (args.host, args.port) if args.host else pick_server(args.discovery_port, args.discovery_s)
        classifier = (
            EmgLogger()
            if args.log_only
            else NeuralSignClassifier(args.neural_model, snap_threshold=args.snap_threshold)
        )
        log.info("classifier: %s", "EMG log only" if args.log_only else args.neural_model)
        asyncio.run(run_hand_client(kinesis_url, server, classifier))


if __name__ == "__main__":
    main()
