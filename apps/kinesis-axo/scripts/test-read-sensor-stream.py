#!/usr/bin/env python3
"""Synthetic parser/URL fixtures; no live stream, tokens, or hardware access."""

import argparse
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("reader", Path(__file__).with_name("read-sensor-stream.py"))
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class SensorStreamReaderTests(unittest.TestCase):
    def test_multiline_payload_and_comments(self):
        parser = reader.SSEParser()
        for line in [": keepalive\n", "id: 42\r\n", "event: gyro\n", "data: {\n", 'data: "type":"gyro"}\n']:
            self.assertIsNone(parser.feed_line(line))
        self.assertEqual(parser.feed_line("\n"), ("gyro", "42", '{\n"type":"gyro"}'))
        self.assertIsNone(parser.feed_line(": keepalive\n"))
        self.assertIsNone(parser.feed_line("\n"))

    def test_event_type_resets_and_valid_last_id_persists(self):
        parser = reader.SSEParser()
        parser.feed_line("id: 2\n")
        parser.feed_line("event: status\n")
        parser.feed_line("data: {}\n")
        self.assertEqual(parser.feed_line("\n"), ("status", "2", "{}"))
        parser.feed_line("id: bad\0id\n")
        parser.feed_line("data: []\n")
        self.assertEqual(parser.feed_line("\n"), ("message", "2", "[]"))

    def test_empty_data_is_an_event_but_incomplete_data_is_not(self):
        parser = reader.SSEParser()
        self.assertIsNone(parser.feed_line("data:\n"))
        self.assertEqual(parser.feed_line("\n"), ("message", "", ""))
        self.assertIsNone(parser.feed_line("data: incomplete\n"))

    def test_event_memory_is_bounded_across_multiple_lines(self):
        parser = reader.SSEParser()
        parser.feed_line("data: " + "x" * (reader.MAX_LINE // 2 - 1))
        parser.feed_line("data: " + "x" * (reader.MAX_LINE // 2 - 1))
        with self.assertRaises(ValueError):
            parser.feed_line("data: x")

    def test_local_capability_urls_only(self):
        token = "0" * 32
        for host in ["127.0.0.1", "localhost"]:
            url = f"http://{host}:8766/events?token={token}"
            self.assertEqual(reader.validate_url(url), url)
        for url in [f"https://localhost:8766/events?token={token}",
                    f"http://example.com:8766/events?token={token}",
                    f"http://localhost@evil.example:8766/events?token={token}",
                    f"http://name:password@localhost:8766/events?token={token}",
                    f"http://localhost:8766/wrong?token={token}",
                    f"http://localhost:8766/events?token={token}&token={token}",
                    f"http://localhost:8766/events?token={token}#fragment",
                    f"http://localhost:99999/events?token={token}",
                    f"http://localhost:8766/events?token={token}\n",
                    "http://localhost:8766/events?token=not-a-token"]:
            with self.subTest(url=url), self.assertRaises(argparse.ArgumentTypeError) as caught:
                reader.validate_url(url)
            self.assertNotIn(token, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
