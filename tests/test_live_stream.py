import asyncio

import pytest

from rlflow.live_stream import LiveStream


class Reader:
    def __init__(self, count):
        self.count, self.limits = count, []

    def events(self, cursor, *, limit):
        self.limits.append(limit)
        seq = int(cursor.rsplit(":", 1)[1])
        return [{"seq": seq + 1, "store_epoch": "store_test", "payload": {}}] if seq < self.count else []

    def head(self):
        return {"cursor": f"store_test:{self.count}", "server_time": "2026-10-08T00:00:00.000Z"}


async def stream(reader, *, delay=0, authorized=lambda: True, revoke=None, **options):
    messages, slots = [], []
    disconnected = asyncio.Event()
    response = LiveStream(reader, "store_test:0", authorized, lambda: slots.append("released"),
                          poll=0.001, heartbeat=0.01, send_timeout=0.5, **options)

    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if delay:
            await asyncio.sleep(delay)
        messages.append(message)
        body = message.get("body", b"")
        if revoke and b"event: domain" in body:
            revoke()
        if b"event: heartbeat" in body or not message.get("more_body", True):
            disconnected.set()

    await asyncio.wait_for(response({"type": "http"}, receive, send), 3)
    assert slots == ["released"]
    return b"".join(m.get("body", b"") for m in messages)


def test_healthy_large_backlog_is_not_slow_consumer_and_prefetch_is_bounded():
    reader = Reader(100)
    # Large heartbeat interval ensures this test waits for all 100 domain IDs.
    async def run():
        messages, slots = [], []
        ended = asyncio.Event()
        async def receive():
            await ended.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            messages.append(message)
            if b"id: store_test:100\n" in message.get("body", b""):
                ended.set()
        response = LiveStream(reader, "store_test:0", lambda: True, lambda: slots.append(1), heartbeat=5)
        await asyncio.wait_for(response({"type": "http"}, receive, send), 3)
        assert slots == [1]
        return b"".join(m.get("body", b"") for m in messages)
    body = asyncio.run(run())
    assert body.count(b"event: domain") == 100 and b"SLOW_CONSUMER" not in body
    assert set(reader.limits) == {1}


def test_actual_slow_consumer_resyncs_and_revocation_blocks_buffered_domain():
    body = asyncio.run(stream(Reader(100), delay=0.02, max_frames=2))
    assert b"SLOW_CONSUMER" in body and b"event: resync_required" in body
    active = [True]
    body = asyncio.run(stream(Reader(100), authorized=lambda: active[0], revoke=lambda: active.__setitem__(0, False)))
    assert body.count(b"event: domain") == 1 and b"AUTH_EXPIRED" in body


def test_invalid_bounds_never_create_unbounded_queue():
    for args in ({"max_frames": 0}, {"max_bytes": 0}, {"poll": float("nan")}, {"send_timeout": -1}):
        with pytest.raises(ValueError):
            LiveStream(Reader(0), "store_test:0", lambda: True, lambda: None, **args)
