import threading

import pytest

from handclient.kinesis_feed import (
    BandGestureEvent,
    BandStatus,
    EmgBatch,
    FeedRejected,
    KinesisFeed,
    SseParser,
    parse_event,
    validate_feed_url,
)
from tests import fake_kinesis as fk


def parse_frames(text: str):
    parser = SseParser()
    return [frame for line in text.splitlines(keepends=True) if (frame := parser.feed_line(line))]


def test_parses_hello_emg_and_gesture_into_typed_events():
    frames = parse_frames(fk.hello() + fk.emg_configuration() + fk.emg(7) + fk.gesture(3, "index", "tap", "singleTap"))
    events = [parse_event(kind, data) for kind, data in frames]
    status, configuration, batch, gesture = events
    assert status == BandStatus(connected=True, hand="right", emg_active=True, band_connection_id="epoch-1")
    assert configuration is None
    assert isinstance(batch, EmgBatch)
    assert (batch.sequence, batch.samples.shape, batch.samples.dtype) == (7, (16, 8), "uint16")
    assert batch.samples[0].tolist() == [32768 + channel for channel in range(8)]
    assert gesture == BandGestureEvent(3, 3000, 0.0, "index", "tap", "singleTap", False)


def test_comments_and_keepalives_yield_no_frames():
    assert parse_frames(": connected\n\n: keepalive\n\n") == []


def test_rejects_unsupported_schema_and_emg_format():
    with pytest.raises(ValueError):
        parse_event("hello", fk.hello().split("data: ")[1].replace('"schema_version": 1', '"schema_version": 2'))
    with pytest.raises(ValueError):
        parse_event(*parse_frames(fk.emg_configuration().replace('"channels": 8', '"channels": 16'))[0])


def test_url_must_be_the_local_events_endpoint():
    assert validate_feed_url(f"http://127.0.0.1:8766/events?token={fk.TOKEN}")
    for url in (
        "http://10.0.0.2:8766/events?token=x",
        "http://127.0.0.1:8766/other?token=x",
        "http://127.0.0.1:8766/events",
    ):
        with pytest.raises(ValueError):
            validate_feed_url(url)


def test_feed_delivers_events_until_stopped():
    received = []
    stop = threading.Event()
    with fk.FakeKinesis([fk.hello(), fk.emg(1), fk.emg(2)]) as kinesis:

        def on_event(event):
            received.append(event)
            if len(received) == 3:
                stop.set()

        thread = threading.Thread(target=KinesisFeed(kinesis.url, on_event).run, args=(stop,))
        thread.start()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert [type(event) for event in received] == [BandStatus, EmgBatch, EmgBatch]


def test_feed_raises_when_kinesis_rejects_the_token():
    with fk.FakeKinesis([]) as kinesis:
        feed = KinesisFeed(kinesis.url.replace(fk.TOKEN, "f" * 32), lambda event: None)
        with pytest.raises(FeedRejected):
            feed.run(threading.Event())
