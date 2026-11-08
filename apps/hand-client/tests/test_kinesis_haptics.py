import http.server
import queue
import threading
import time

from handclient.kinesis_haptics import HapticsWorker


class RejectEverything(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.server.requests.append(self.path)
        self.send_response(405, "Rejected")
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


def test_a_rejected_buzz_is_dropped_and_the_worker_keeps_going():
    server = http.server.HTTPServer(("127.0.0.1", 0), RejectEverything)
    server.requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    durations: queue.Queue[int] = queue.Queue()
    stop = threading.Event()
    feed_url = f"http://127.0.0.1:{server.server_port}/events?token=T"
    worker = threading.Thread(target=HapticsWorker(feed_url, durations).run, args=(stop,))
    worker.start()
    try:
        durations.put(120)
        durations.put(60)
        deadline = time.monotonic() + 3
        while len(server.requests) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        stop.set()
        worker.join(timeout=3)
        server.shutdown()
    assert server.requests == ["/haptics?token=T&ms=120", "/haptics?token=T&ms=60"]
    assert not worker.is_alive()
