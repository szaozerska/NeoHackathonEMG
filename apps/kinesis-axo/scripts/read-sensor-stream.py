#!/usr/bin/env python3
"""Read Kinesis's local SSE feed without third-party packages or sensor logging by default."""

import argparse
from collections import Counter
import json
import math
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


MAX_LINE = 512 * 1024
EVENT_TYPES = {"hello", "status", "emg_configuration", "emg", "gyro", "orientation", "gesture"}


class SSEParser:
    """Consume complete SSE lines, preserving multiline data and ignoring comments."""

    def __init__(self):
        self.data = []
        self.kind = "message"
        self.identifier = ""
        self.size = 0

    def feed_line(self, line):
        line = line.removesuffix("\n").removesuffix("\r")
        if not line:
            event = (self.kind, self.identifier, "\n".join(self.data)) if self.data else None
            self.data = []
            self.kind = "message"
            self.size = 0
            return event
        if line.startswith(":"):
            return None
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "data":
            self.size += len(value) + 1  # Bound even an endless run of empty data lines.
            if self.size > MAX_LINE:
                raise ValueError("SSE event is too large")
            self.data.append(value)
        elif field == "event":
            self.kind = value
        elif field == "id" and "\0" not in value:
            self.identifier = value
        return None


def validate_url(value):
    """Reject remote destinations, embedded credentials, redirects, and malformed capabilities."""
    try:
        if any(ord(char) < 33 or ord(char) == 127 for char in value):
            raise ValueError()
        parts = urllib.parse.urlsplit(value)
        query = urllib.parse.parse_qsl(parts.query, strict_parsing=True)
        valid = (parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost"}
                 and parts.username is None and parts.password is None
                 and parts.port is not None and 1 <= parts.port <= 65535
                 and parts.path == "/events" and not parts.fragment
                 and len(query) == 1 and query[0][0] == "token"
                 and re.fullmatch(r"[0-9a-f]{32}", query[0][1]) is not None)
        if not valid:
            raise ValueError()
    except ValueError:
        raise argparse.ArgumentTypeError("Use the local /events URL copied from Kinesis's stream page.") from None
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_stream(url, seconds, print_jsonl=False):
    counts = Counter()
    emg_samples = 0
    started = time.monotonic()
    deadline = started + seconds
    exit_code = 0
    # Bypass proxy settings so this local capability never travels to an HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    parser = SSEParser()
    try:
        with opener.open(request, timeout=min(2.0, seconds)) as response:
            if response.headers.get_content_type() != "text/event-stream":
                raise ValueError("Unexpected content type")
            while time.monotonic() < deadline:
                line = response.readline(MAX_LINE + 1)
                if not line:
                    raise EOFError()
                if len(line) > MAX_LINE:
                    raise ValueError("SSE line is too large")
                parsed = parser.feed_line(line.decode("utf-8"))
                if parsed is None:
                    continue
                kind, _, data = parsed
                event = json.loads(data)
                if (not isinstance(event, dict) or event.get("schema_version") != 1
                        or event.get("type") != kind or kind not in EVENT_TYPES
                        or not isinstance(event.get("payload"), dict)):
                    raise ValueError("Unsupported event schema")
                counts[kind] += 1
                if kind == "emg":
                    emg_samples += len(event.get("payload", {}).get("values", []))
                if print_jsonl:
                    print(json.dumps(event, separators=(",", ":")), flush=True)
    except urllib.error.HTTPError as error:
        print(f"Kinesis rejected the reader (HTTP {error.code}). Copy a fresh stream URL.", file=sys.stderr)
        exit_code = 1
    except (socket.timeout, TimeoutError):
        if time.monotonic() < deadline:
            print("The local stream stopped responding.", file=sys.stderr)
            exit_code = 1
    except (urllib.error.URLError, OSError):
        print("Could not read the local stream. Check that Kinesis's stream is enabled.", file=sys.stderr)
        exit_code = 1
    except EOFError:
        print("Kinesis closed the stream. Reconnect with the current stream URL.", file=sys.stderr)
        exit_code = 1
    except (ValueError, UnicodeError):
        print("The local stream returned an invalid or unsupported event.", file=sys.stderr)
        exit_code = 1
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        summary = {"duration_s": round(time.monotonic() - started, 2),
                   "events": dict(sorted(counts.items())), "emg_samples_per_channel": emg_samples}
        print(json.dumps(summary), file=sys.stderr if print_jsonl else sys.stdout)
    return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, type=validate_url, help="Copy stream URL from Kinesis.")
    parser.add_argument("--seconds", type=float, default=10, help="Read duration in seconds (default: 10).")
    parser.add_argument("--jsonl", action="store_true", help="Explicitly print raw sensor events as JSONL.")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be a finite positive number.")
    return read_stream(args.url, args.seconds, args.jsonl)


if __name__ == "__main__":
    sys.exit(main())
