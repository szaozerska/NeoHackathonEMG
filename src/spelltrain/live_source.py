"""Discover Kinesis's open recording or consume its explicitly supplied local feed."""
import os
from pathlib import Path
import subprocess
import threading
from urllib.parse import urlsplit, parse_qs

from .feeds import read_sse, tail_kinesis


def validate_stream_url(url):
    try:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, strict_parsing=True)
        valid = (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1')
                 and parsed.port is not None and parsed.path == '/events'
                 and not parsed.username and not parsed.password and not parsed.fragment
                 and set(query) == {'token'} and len(query['token']) == 1
                 and bool(query['token'][0]))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError('Use the local stream URL copied from Kinesis.')
    return url


def discover_recording():
    """Inspect only files held open by Kinesis; never scan user directories."""
    try:
        result = subprocess.run(['/usr/sbin/lsof', '-a', '-c', 'Kinesis', '-Fn'],
                                capture_output=True, text=True, timeout=3)
        candidates = []
        for line in result.stdout.splitlines():
            if not line.startswith('n/') or not line.endswith('.jsonl'):
                continue
            path = Path(line[1:])
            # Honor this workspace's excluded repository without inspecting it.
            # Check from the filesystem root so symlinked parents are never followed.
            if 'QCompany' in path.parts or any(parent.is_symlink() for parent in (*reversed(path.parents),path)):
                continue
            if path.is_file():
                candidates.append(path)
        return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
    except (OSError, subprocess.TimeoutExpired):
        return None


class LiveInput:
    def __init__(self, fallback, callback, error, changed, state_file=None, event_callback=None):
        self.fallback = Path(fallback)
        self.callback, self.error, self.changed = callback, error, changed
        self.state_file = Path(state_file) if state_file else None
        self.url = None
        self.event_callback = event_callback
        if self.state_file and self.state_file.exists():
            try:
                self.url = validate_stream_url(self.state_file.read_text().strip())
            except (OSError, ValueError):
                pass

    def set_stream(self, url):
        url = validate_stream_url(url)
        if self.state_file:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.state_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(url)
        self.url = url

    def run(self, stop):
        current = None
        worker_stop = None
        generation = [0]
        try:
            while not stop.is_set():
                source = ('stream', self.url) if self.url else ('file', str(discover_recording() or self.fallback))
                if source != current:
                    if worker_stop:
                        worker_stop.set()
                    generation[0] += 1
                    worker_stop = threading.Event()
                    current = source
                    self.changed(source[0], None if self.url else source[1])

                    def consume(packet, revision=generation[0]):
                        if not stop.is_set() and revision == generation[0]:
                            self.callback({**packet, 'input_generation': (revision, packet.get('stream_session'))})

                    def run_source(selected=source, cancelled=worker_stop, callback=consume):
                        try:
                            if selected[0] == 'stream':
                                adapter = {'samples_path': 'payload.values', 'sequence_path': 'payload.sequence',
                                           'timestamp_path': 'band_timestamp_us', 'uptime_path': 'host_time_s'}
                                def event_callback(kind, payload):
                                    if self.event_callback and not cancelled.is_set():
                                        self.event_callback(kind, payload)
                                read_sse(selected[1], adapter, cancelled, callback, self.error, event_callback)
                            else:
                                tail_kinesis(selected[1], cancelled, callback, self.error)
                        except Exception as exc:
                            self.error('Model input failed: ' + type(exc).__name__)

                    threading.Thread(target=run_source, daemon=True).start()
                stop.wait(1)
        finally:
            generation[0] += 1
            if worker_stop:
                worker_stop.set()
