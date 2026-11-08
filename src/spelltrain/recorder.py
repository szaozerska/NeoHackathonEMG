from __future__ import annotations
from collections import deque
import json
from pathlib import Path
import queue
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import secrets
from urllib.parse import urlparse, parse_qs, unquote
import numpy as np
from .common import annotation_valid, finite, vector
from .feeds import BatchTimeline, read_sse, tail_kinesis
from .fusion import SpellEngine
from .models import PrimitivePredictor
from .session import Session, load_session
from .signal_check import SignalCheck
from .shield_training import ShieldTraining


def validate_pose(message):
    out = {}
    for name in ("hand", "chest"):
        source = message[name]
        q = vector(source["rot"], 4)
        if not .8 < np.linalg.norm(q) < 1.2:
            raise ValueError("Invalid rotation")
        confidence = finite(source["confidence"])
        if not 0 <= confidence <= 1:
            raise ValueError("Bad confidence")
        out[name] = {"pos": vector(source["pos"]).tolist(), "rot": (q/np.linalg.norm(q)).tolist(),
                     "valid": source["valid"] is True, "confidence": confidence}
        if name == "hand":
            out[name]["palm_normal"] = vector(source["palm_normal"]).tolist()
            if "finger_direction" in source:
                out[name]["finger_direction"] = vector(source["finger_direction"]).tolist()
    out["opponent_direction"] = vector(message.get("opponent_direction", [0, 0, 1])).tolist()
    out["frame_id"] = str(message.get("frame_id", "default"))[:100]
    return out


class Recorder:
    def __init__(self, session, artifact=None, motion=None, review=False, experimental_snaps=False):
        self.session, self.review = session, review
        self.stop = threading.Event()
        self.messages = queue.Queue(maxsize=8192)
        self.errors, self.spells = deque(maxlen=12), deque(maxlen=30)
        self.emg_preview, self.pose_preview = deque(maxlen=512), deque(maxlen=600)
        self.last_emg = self.last_pose = -float("inf")
        self.hand_state = "none"
        self.latest_pose = None
        self.clock_rtt = None
        self.timeline = BatchTimeline()
        if artifact and artifact.get('task') == 'v3_gesture_bundle':
            from .gestures import GesturePredictor
            self.predictor = GesturePredictor(artifact, experimental_snaps=experimental_snaps)
        else:
            self.predictor = PrimitivePredictor(artifact) if artifact else None
        self.engine = SpellEngine(motion)
        self.threads, self.servers = [], []
        self.vr_lock = threading.Lock()
        self.frame_id = None
        self.commands = queue.Queue(maxsize=16)
        self.worker_thread = None
        self.duration = 0.
        self.signal_check = SignalCheck(session)
        if session.meta.get('training_profile') == 'supplemental':
            from .supplemental import SupplementalTraining
            self.shield_training = SupplementalTraining(session)
        else:
            self.shield_training = ShieldTraining(session)
        self.capture_lock = threading.RLock()
        if review:
            _, _, rows = load_session(session.directory)
            self.review_rows = rows
            self.duration = max((r.get("received", r["t"]) for r in rows), default=0)
            for row in rows:
                if row["kind"] == "emg":
                    self.emg_preview.append([row["t"], np.std(row["samples"], axis=0).tolist()])
                elif row["kind"] == "pose":
                    self.pose_preview.append([row["t"], row["pose"]["hand"]["pos"], row["pose"]["hand"]["valid"]])

    def error(self, message):
        self.errors.append({"t": self.session.now() if not self.review else 0, "message": message})

    def enqueue(self, row):
        if self.stop.is_set():
            return
        try:
            self.messages.put_nowait(row)
        except queue.Full:
            self.error("Recording stopped: ingestion queue overflow. This session is incomplete; reduce workload.")
            self.session.meta["incomplete"] = True
            self.stop.set()

    def band_packet(self, packet):
        received = self.session.now()
        uptime_end = None
        if "source_uptime" in packet:
            # Both clocks on macOS are boot-relative; reject mismatches instead of silently mixing epochs.
            candidate = packet["source_uptime"] - self.session.meta["origin_monotonic"]
            if abs(candidate - received) <= 5 and candidate >= 0:
                uptime_end = candidate
            else:
                self.error("Kinesis uptime clock mismatch or stale data; using explicitly approximate receive timing")
        aligned = self.timeline.align(packet, received, uptime_end)
        self.enqueue({"kind": "emg", "received": received, **aligned})

    def start_band(self, url=None, adapter=None, filename=None):
        if url:
            self.spawn(lambda: read_sse(url, adapter, self.stop, self.band_packet, self.error))
        elif filename:
            self.spawn(lambda: tail_kinesis(filename, self.stop, self.band_packet, self.error))

    def spawn(self, fn):
        thread = threading.Thread(target=fn, daemon=True)
        thread.start()
        self.threads.append(thread)
        if fn == self.worker:
            self.worker_thread = thread
        return thread

    def add_spells(self, events):
        for event in events:
            self.spells.append(event)
            self.session.append({"kind": "prediction", "t": event["t"], "received": self.session.now(), "event": event})

    def worker(self):
        while not self.stop.is_set() or not self.messages.empty():
            try:
                row = self.messages.get(timeout=.1)
            except queue.Empty:
                if self.predictor:
                    self.add_spells(self.engine.expire(self.session.now()))
                continue
            try:
                self.session.append(row)
                t = row["received"]
                if row["kind"] == "emg":
                    self.last_emg = t
                    self.signal_check.observe(row)
                    self.shield_training.observe(row)
                    x = np.asarray(row["samples"], dtype=float)
                    self.emg_preview.append([row["t"], np.std(x, axis=0).tolist()])
                    if self.predictor:
                        for p in self.predictor.feed(row):
                            if p["kind"] == "state":
                                self.hand_state = p["label"]
                                self.add_spells(self.engine.state(p["label"], t, p["confidence"]))
                            elif p['kind'] == 'effort':
                                self.add_spells(self.engine.effort(p['effort_index'], t))
                            elif p['kind'] == 'snap_candidate':
                                self.session.append({'kind': 'prediction', 't': p['t'], 'received': t,
                                                     'candidate': p})
                            else:
                                self.add_spells(self.engine.snap(t, p["event_id"]))
                elif row["kind"] == "pose":
                    self.shield_training.observe_pose(row)
                    self.last_pose, self.latest_pose = t, row["pose"]
                    if row["pose"]["frame_id"] != self.frame_id:
                        self.engine.history.clear()
                        self.engine.near_hip, self.engine.gripped_at, self.engine.draw_start = -float("inf"), None, None
                        self.frame_id = row["pose"]["frame_id"]
                    self.pose_preview.append([row["t"], row["pose"]["hand"]["pos"], row["pose"]["hand"]["valid"]])
                    if self.predictor:
                        self.add_spells(self.engine.pose_sample(row["pose"], t, sample_t=row["t"]))
            except Exception as exc:
                self.error("Processing failed: " + type(exc).__name__)
                self.session.meta["incomplete"] = True
                self.stop.set()
            finally:
                self.messages.task_done()

    def start_tcp(self, host, port):
        recorder = self
        class Handler(socketserver.StreamRequestHandler):
            def send(self, value):
                self.wfile.write((json.dumps(value, allow_nan=False) + "\n").encode())
                self.wfile.flush()

            def handle(self):
                self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.request.settimeout(5)
                acquired = False
                try:
                    hello = json.loads(self.rfile.readline(65537))
                    if hello.get("type") != "hello" or hello.get("role") != "vr":
                        self.send({"type": "error", "message": "Expected VR hello"})
                        return
                    acquired = recorder.vr_lock.acquire(blocking=False)
                    if not acquired:
                        self.send({"type": "error", "message": "One Quest per recording session"})
                        return
                    self.send({"type": "welcome", "player_id": "P1", "session_id": recorder.session.meta["id"]})
                    while not recorder.stop.is_set():
                        line = self.rfile.readline(65537)
                        received_absolute = time.monotonic()
                        if not line:
                            break
                        if len(line) > 65536:
                            raise ValueError("Oversized Quest packet")
                        message = json.loads(line)
                        try:
                            self.send(recorder.commands.get_nowait())
                        except queue.Empty:
                            pass
                        if message.get("type") == "time_ping":
                            self.send({"type": "time_pong", "client_t": finite(message["t"]),
                                       "server_recv": received_absolute, "server_send": time.monotonic()})
                        elif message.get("type") == "pose":
                            received = received_absolute - recorder.session.meta["origin_monotonic"]
                            pose = validate_pose(message)
                            rtt = finite(message.get("sync_rtt", -1))
                            mapped = finite(message.get("t_mac", 0)) - recorder.session.meta["origin_monotonic"]
                            synced = 0 <= rtt <= .1 and abs(mapped - received) <= .5
                            recorder.clock_rtt = rtt if synced else None
                            recorder.enqueue({"kind": "pose", "received": received, "t": mapped if synced else received,
                                              "source_t": finite(message["t"]), "seq": int(message.get("seq", 0)),
                                              "timing": "clock_offset_estimate" if synced else "receive_anchored",
                                              "sync_rtt": rtt if synced else None, "pose": pose})
                except (OSError, ValueError, KeyError, TypeError):
                    recorder.error("Quest disconnected or sent invalid tracking packets")
                finally:
                    if acquired:
                        recorder.vr_lock.release()
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
        server = Server((host, port), Handler)
        self.servers.append(server)
        self.spawn(server.serve_forever)
        return server.server_address[1]

    def beacon(self, port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                while not self.stop.is_set():
                    sock.sendto(f"SPELLGAME {port}".encode(), ("255.255.255.255", 47777))
                    self.stop.wait(1)
        except OSError:
            self.error("LAN discovery unavailable; enter the Mac IP manually in Unity")

    def status(self):
        now = self.duration if self.review else self.session.now()
        return {"session": self.session.meta, "now": now, "review": self.review,
                "stopped": self.stop.is_set(), "counts": dict(self.session.counts),
                "emg_fresh": now - self.last_emg < .5, "quest_fresh": now - self.last_pose < .5,
                "pose": self.latest_pose, "hand_state": self.hand_state if now-self.last_emg < .3 else "none",
                "mode": self.engine.mode, "clock_rtt": self.clock_rtt,
                "errors": list(self.errors), "spells": list(self.spells),
                "annotations": list(self.session.annotations), "emg": list(self.emg_preview),
                "trajectory": list(self.pose_preview), "queue": self.messages.qsize()}

    def start_web(self, port):
        recorder, csrf = self, secrets.token_urlsafe(24)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, value, code=200):
                body = json.dumps(value, allow_nan=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                route = urlparse(self.path)
                if route.path in ("/", "/shield", "/check", "/advanced"):
                    asset = ("dashboard-advanced.html" if route.path == "/advanced" or recorder.review
                             else "dashboard-check.html" if route.path == "/check"
                             else "dashboard-supplemental.html" if recorder.session.meta.get('training_profile') == 'supplemental'
                             else "dashboard.html")
                    body = files("spelltrain").joinpath(asset).read_text().replace("__CSRF__", csrf).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                elif route.path == "/api/status":
                    self.respond(recorder.status())
                elif route.path == "/api/check":
                    self.respond(recorder.signal_check.status())
                elif route.path == "/api/shield":
                    self.respond(recorder.shield_training.status())
                elif route.path == '/api/reference':
                    result_id = parse_qs(route.query).get('id', [''])[0]
                    result = next((r for r in recorder.shield_training.status()['results']
                                   if r['id'] == result_id), None)
                    reference = result.get('reference') if result else None
                    if not reference:
                        self.respond({'error': 'Reference not found'}, 404)
                        return
                    path = recorder.session.directory / reference['file']
                    if not path.is_file():
                        self.respond({'error': 'Reference file missing'}, 404)
                        return
                    size = path.stat().st_size
                    start, end, code = 0, size-1, 200
                    requested = self.headers.get('Range')
                    if requested:
                        try:
                            unit, span = requested.split('=', 1)
                            first, last = span.split('-', 1)
                            if unit != 'bytes' or not first.isdigit() or (last and not last.isdigit()):
                                raise ValueError()
                            start, end = int(first), min(int(last), size-1) if last else size-1
                            if not 0 <= start <= end < size:
                                raise ValueError()
                            code = 206
                        except ValueError:
                            self.send_response(416)
                            self.send_header('Content-Range', f'bytes */{size}')
                            self.end_headers()
                            return
                    self.send_response(code)
                    self.send_header('Content-Type', reference['mime'])
                    self.send_header('Content-Length', str(end-start+1))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Cache-Control', 'no-store')
                    if code == 206:
                        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    with path.open('rb') as media:
                        media.seek(start)
                        self.wfile.write(media.read(end-start+1))
                elif route.path == "/api/trace":
                    try:
                        args = parse_qs(route.query)
                        start, end = float(args.get("start", [0])[0]), float(args.get("end", [10])[0])
                        rows = recorder.review_rows if recorder.review else []
                        emg, pose = [], []
                        for r in rows:
                            if start <= r["t"] <= end:
                                if r["kind"] == "emg":
                                    emg.append([r["t"], np.std(r["samples"], axis=0).tolist()])
                                elif r["kind"] == "pose":
                                    pose.append([r["t"], r["pose"]["hand"]["pos"], r["pose"]["hand"]["valid"]])
                        self.respond({"emg": emg[::max(1, len(emg)//1000)], "trajectory": pose[::max(1, len(pose)//1000)]})
                    except ValueError:
                        self.respond({"error": "Bad time range"}, 400)
                else:
                    self.respond({"error": "Not found"}, 404)

            def do_POST(self):
                if self.headers.get("X-Session-Token") != csrf:
                    self.respond({"error": "Invalid session token"}, 403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if self.path == '/api/reference-binary':
                        if recorder.review or recorder.stop.is_set() or recorder.session.meta.get('training_profile') != 'supplemental':
                            raise ValueError('Reference upload requires a live supplemental session')
                        if not 100 <= length <= 8*1024*1024:
                            raise ValueError('Reference must be between 100 bytes and 8 MB')
                        alignment = json.loads(unquote(self.headers.get('X-Reference-Alignment', '')))
                        payload = self.rfile.read(length)
                        if len(payload) != length:
                            raise ValueError('Reference upload interrupted; retry saving it')
                        self.respond(recorder.shield_training.attach_reference_bytes(
                            self.headers.get('X-Result-Id', ''), self.headers.get('Content-Type', ''), payload, alignment))
                        return
                    limit = 12*1024*1024 if self.path == '/api/reference' else 65536
                    if not 0 < length <= limit:
                        raise ValueError("Invalid request size")
                    value = json.loads(self.rfile.read(length))
                    if self.path == '/api/reference':
                        if recorder.review or recorder.stop.is_set() or recorder.session.meta.get('training_profile') != 'supplemental':
                            raise ValueError('Reference upload requires a live supplemental session')
                        self.respond(recorder.shield_training.attach_reference(value['id'], value['mime'],
                                                                              value['data'], value['alignment']))
                    elif self.path in ("/api/shield/start", "/api/shield/stop", "/api/shield/confirm"):
                        if recorder.review or recorder.stop.is_set():
                            raise ValueError("Start a live recording session first")
                        with recorder.capture_lock:
                            if self.path.endswith('/start'):
                                if recorder.signal_check.status()['active']:
                                    raise ValueError('Stop the signal check first')
                                if recorder.session.now() - recorder.last_emg >= .5:
                                    raise ValueError('Wait for fresh EMG before recording')
                                result = recorder.shield_training.start(value['trial_id'])
                            elif self.path.endswith('/confirm'):
                                result = recorder.shield_training.confirm(value['id'], value['accepted'])
                            else:
                                result = recorder.shield_training.finish()
                        self.respond(result)
                    elif self.path in ("/api/check/start", "/api/check/stop"):
                        if recorder.review or recorder.stop.is_set():
                            raise ValueError("Start a live recording session first")
                        with recorder.capture_lock:
                            if self.path.endswith('/start') and recorder.shield_training.status()['active']:
                                raise ValueError('Stop shield training first')
                            result = (recorder.signal_check.start(value['motion']) if self.path.endswith('/start')
                                      else recorder.signal_check.finish())
                        self.respond(result)
                    elif self.path == "/api/annotation":
                        row = recorder.session.annotate(value)
                        self.respond(row)
                    elif self.path == "/api/stop":
                        if recorder.review:
                            raise ValueError("This is an offline review")
                        self.respond({"ok": True})
                        recorder.stop.set()
                    elif self.path == "/api/command":
                        if value.get("type") not in ("calibrate_palm", "reset_frame") or recorder.review:
                            raise ValueError("Unsupported or offline Quest command")
                        recorder.commands.put_nowait({"type": value["type"]})
                        self.respond({"ok": True})
                    elif self.path == "/api/delete":
                        recorder.session.delete(value["id"])
                        self.respond({"ok": True})
                    else:
                        self.respond({"error": "Not found"}, 404)
                except (ValueError, KeyError, TypeError, queue.Full) as exc:
                    self.respond({"error": str(exc)}, 400)
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.servers.append(server)
        self.spawn(server.serve_forever)
        return server.server_address[1]

    def close(self):
        self.stop.set()
        for server in self.servers:
            server.shutdown()
            server.server_close()
        if self.worker_thread is not None:
            self.messages.join()
            self.worker_thread.join()
        for thread in self.threads:
            thread.join(timeout=2)
        self.session.close()
