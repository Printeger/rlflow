"""Durable observation SSE with bounded buffering and actual-send deadlines."""
from __future__ import annotations

import asyncio
import json
import math
import time

from starlette.responses import Response

from .hybrid_protocol import ProtocolError
from .hybrid_protocol import validate


def frame(event, data, cursor=None):
    body = json.dumps(data, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return ((f"id: {cursor}\n" if cursor else "") + f"event: {event}\ndata: {body}\n\n").encode()


class LiveStream(Response):
    media_type = "text/event-stream"

    def __init__(self, reader, cursor, authorized, release_slot, *, poll=0.25,
                 heartbeat=5.0, send_timeout=2.0, max_frames=32, max_bytes=4 * 1024 * 1024):
        if (type(max_frames) is not int or not 1 <= max_frames <= 32 or type(max_bytes) is not int
                or not 1 <= max_bytes <= 4 * 1024 * 1024
                or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (poll, heartbeat, send_timeout))):
            raise ValueError("invalid stream bounds")
        super().__init__(headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
        # Response's zero-length body must not advertise Content-Length: 0.
        self.raw_headers = [(k, v) for k, v in self.raw_headers if k != b"content-length"]
        self.reader, self.cursor, self.authorized, self.release_slot = reader, cursor, authorized, release_slot
        self.poll, self.heartbeat, self.send_timeout = poll, heartbeat, send_timeout
        self.max_frames, self.max_bytes = max_frames, max_bytes

    async def __call__(self, scope, receive, send):
        queue = asyncio.Queue(self.max_frames)
        buffered = 0

        def control(reason):
            nonlocal buffered
            while not queue.empty():
                queue.get_nowait()
            payload = {"code": "RESYNC_REQUIRED", "reason": reason}
            validate("Resync", payload)
            data = frame("resync_required", payload)
            buffered = len(data)
            queue.put_nowait((data, True))

        def enqueue(data):
            nonlocal buffered
            if queue.full() or buffered + len(data) > self.max_bytes:
                control("SLOW_CONSUMER")
                return False
            buffered += len(data)
            queue.put_nowait((data, False))
            return True

        async def produce():
            cursor = self.cursor
            last_heartbeat = time.monotonic()
            try:
                while True:
                    if not self.authorized():
                        control("AUTH_EXPIRED")
                        return
                    # A single envelope is bounded by the transactional bridge.
                    # Do not prefetch 200 potentially 2 MiB envelopes outside
                    # the bounded queue, or classify a healthy backlog as slow.
                    events = await asyncio.to_thread(self.reader.events, cursor, limit=1)
                    for event in events:
                        cursor = f'{event["store_epoch"]}:{event["seq"]}'
                        if not enqueue(frame("domain", event, cursor)):
                            return
                        await asyncio.sleep(0)
                    if time.monotonic() - last_heartbeat >= self.heartbeat:
                        head = await asyncio.to_thread(self.reader.head)
                        payload = {"server_time": head["server_time"], "cursor": head["cursor"]}
                        validate("Heartbeat", payload)
                        if not enqueue(frame("heartbeat", payload)):
                            return
                        last_heartbeat = time.monotonic()
                    if not events:
                        await asyncio.sleep(self.poll)
            except ProtocolError:
                control("RESYNC_REQUIRED")
            except Exception:
                # Never expose database errors, private filenames or traces.
                control("SOURCE_UNAVAILABLE")

        async def consume():
            nonlocal buffered
            await asyncio.wait_for(send({"type": "http.response.start", "status": 200,
                                         "headers": self.raw_headers}), self.send_timeout)
            while True:
                data, closing = await queue.get()
                buffered -= len(data)
                # Revalidate even a previously buffered domain frame.
                if not self.authorized():
                    data, closing = frame("resync_required", {"code": "RESYNC_REQUIRED", "reason": "AUTH_EXPIRED"}), True
                await asyncio.wait_for(send({"type": "http.response.body", "body": data,
                                             "more_body": not closing}), self.send_timeout)
                if closing:
                    return

        async def disconnected():
            while (await receive())["type"] != "http.disconnect":
                pass

        tasks = [asyncio.create_task(produce()), asyncio.create_task(consume()), asyncio.create_task(disconnected())]
        try:
            done, _ = await asyncio.wait(tasks[1:], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                # A blocked socket cannot safely carry a final resync. Closing
                # lets the client reconnect using its last durable event ID.
                try:
                    task.result()
                except (TimeoutError, OSError):
                    pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.release_slot()
