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


def aged_sample(value,elapsed):
    """Conservatively account for query and queue residence, not network time."""
    if not math.isfinite(elapsed) or elapsed<0:raise ValueError('invalid sample residence')
    value['sample_age_seconds']+=elapsed
    for worker in value['workers']:
        h = worker['heartbeat']
        if h['status']!='UNKNOWN':
            h['age_seconds']+=elapsed
            h['status']='FRESH' if h['age_seconds']<=15 else 'STALE'
    validate('Telemetry',value)
    return frame('telemetry',value)


class LiveStream(Response):
    media_type = "text/event-stream"

    def __init__(self, reader, cursor, authorized, release_slot, *, poll=0.25,
                 heartbeat=5.0, send_timeout=2.0, max_frames=32, max_bytes=4 * 1024 * 1024, telemetry_interval=1.0):
        if (type(max_frames) is not int or not 1 <= max_frames <= 32 or type(max_bytes) is not int
                or not 1 <= max_bytes <= 4 * 1024 * 1024
                or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (poll, heartbeat, send_timeout))
                or type(telemetry_interval) not in (int,float) or not math.isfinite(telemetry_interval) or telemetry_interval<.1):
            raise ValueError("invalid stream bounds")
        super().__init__(headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
        # Response's zero-length body must not advertise Content-Length: 0.
        self.raw_headers = [(k, v) for k, v in self.raw_headers if k != b"content-length"]
        self.reader, self.cursor, self.authorized, self.release_slot = reader, cursor, authorized, release_slot
        self.poll, self.heartbeat, self.send_timeout = poll, heartbeat, send_timeout
        self.max_frames, self.max_bytes = max_frames, max_bytes
        self.telemetry_interval = telemetry_interval

    async def __call__(self, scope, receive, send):
        queue = asyncio.Queue(self.max_frames)
        buffered = 0
        pending_sample = None
        ready = asyncio.Event()

        def control(reason):
            nonlocal buffered, pending_sample
            pending_sample = None
            while not queue.empty():
                queue.get_nowait()
            payload = {"code": "RESYNC_REQUIRED", "reason": reason}
            validate("Resync", payload)
            data = frame("resync_required", payload)
            buffered = len(data)
            queue.put_nowait((data, True))
            ready.set()

        def enqueue(data):
            nonlocal buffered, pending_sample
            # Optional telemetry never causes domain/control backpressure.
            if pending_sample and buffered+pending_sample[2]+len(data)>self.max_bytes:
                pending_sample = None
            if queue.full() or buffered + len(data) > self.max_bytes:
                control("SLOW_CONSUMER")
                return False
            buffered += len(data)
            queue.put_nowait((data, False))
            ready.set()
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
            nonlocal buffered, pending_sample
            await asyncio.wait_for(send({"type": "http.response.start", "status": 200,
                                         "headers": self.raw_headers}), self.send_timeout)
            while True:
                if not queue.empty():
                    data, closing = queue.get_nowait()
                    buffered -= len(data)
                elif pending_sample is not None:
                    value, issued, _ = pending_sample
                    pending_sample = None
                    try:
                        data, closing = aged_sample(value,time.monotonic()-issued), False
                        if len(data)>min(65536,self.max_bytes):continue
                    except Exception:
                        continue  # Optional serialization cannot halt domain.
                else:
                    ready.clear()
                    await ready.wait()
                    continue
                # Revalidate even a previously buffered domain frame.
                if not self.authorized():
                    data, closing = frame("resync_required", {"code": "RESYNC_REQUIRED", "reason": "AUTH_EXPIRED"}), True
                await asyncio.wait_for(send({"type": "http.response.body", "body": data,
                                             "more_body": not closing}), self.send_timeout)
                if closing:
                    return

        def pending(value,size,issued):
            nonlocal pending_sample
            pending_sample = (value,issued,size)  # Single slot, no FIFO.
            ready.set()

        async def samples():
            sample_id = None
            query = getattr(self.reader,'telemetry',None)
            if query is None:return
            while self.authorized():
                try:
                    issued = time.monotonic()
                    value = await asyncio.to_thread(query)
                    if value is not None and value['sample_id']!=sample_id:
                        validate('Telemetry',value)
                        data = frame('telemetry',value)  # Never durable id.
                        if len(data)<=65536 and buffered+len(data)<=self.max_bytes:
                            pending(value,len(data),issued)
                            sample_id = value['sample_id']
                except Exception:
                    # A failed optional source must not halt durable catch-up.
                    pass
                await asyncio.sleep(self.telemetry_interval)

        async def disconnected():
            while (await receive())["type"] != "http.disconnect":
                pass

        tasks = [asyncio.create_task(produce()), asyncio.create_task(consume()), asyncio.create_task(disconnected()),asyncio.create_task(samples())]
        try:
            done, _ = await asyncio.wait(tasks[1:3], return_when=asyncio.FIRST_COMPLETED)
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
