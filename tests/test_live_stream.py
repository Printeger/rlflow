import asyncio
import copy
import json
import threading
import time as real_time
from types import SimpleNamespace

import pytest

from rlflow.live_stream import LiveStream
from rlflow.live_stream import aged_sample
from test_telemetry import observed  # noqa: F401
from rlflow import telemetry


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


def test_telemetry_is_no_id_once_per_sample_and_does_not_move_cursor(observed):
    store,reader = observed;assert telemetry.sample(store)
    value = reader.telemetry()
    class Samples(Reader):
        def telemetry(self):return value
    async def run():
        messages=[];ended=asyncio.Event()
        async def receive():await ended.wait();return {'type':'http.disconnect'}
        async def send(message):
            messages.append(message)
            if b'event: heartbeat' in message.get('body',b''):ended.set()
        await LiveStream(Samples(0),'store_test:0',lambda:True,lambda:None,heartbeat=.35,poll=.01,telemetry_interval=.1)({},receive,send)
        return b''.join(m.get('body',b'') for m in messages)
    before = reader.head()['cursor'];body = asyncio.run(run())
    frames = body.split(b'\n\n');samples = [f for f in frames if b'event: telemetry' in f]
    assert len(samples)==1 and b'id:' not in samples[0]
    assert value['sample_id'].encode() in samples[0] and reader.head()['cursor']==before


def test_latest_slot_coalesces_during_send_and_bad_optional_source_keeps_domain(observed):
    store,reader = observed;assert telemetry.sample(store);value = reader.telemetry()
    class Samples(Reader):
        seq=0
        def telemetry(self):
            self.seq+=1;new=copy.deepcopy(value);new['sample_seq']=self.seq;new['sample_id']=new['sampler_epoch']+':'+str(self.seq);return new
    async def run():
        ended=asyncio.Event();messages=[];samples=Samples(0)
        async def receive():await ended.wait();return {'type':'http.disconnect'}
        async def send(message):
            if message['type']=='http.response.start':await asyncio.sleep(.35)
            messages.append(message)
            if b'event: telemetry' in message.get('body',b''):ended.set()
        await LiveStream(samples,'store_test:0',lambda:True,lambda:None,heartbeat=5,poll=.01,telemetry_interval=.1)({},receive,send)
        return b''.join(m.get('body',b'') for m in messages)
    body=asyncio.run(run());assert b'SLOW_CONSUMER' not in body and body.count(b'event: telemetry')==1
    parsed=json.loads(body.split(b'data: ')[1].split(b'\n')[0]);assert parsed['sample_seq']>=3
    class Broken(Reader):
        def telemetry(self):raise RecursionError('PRIVATE source detail')
    body=asyncio.run(stream(Broken(1)))
    assert b'event: domain' in body and b'PRIVATE' not in body and b'SOURCE_UNAVAILABLE' not in body


def test_queue_residence_recomputes_age_before_serializing(observed):
    store,reader=observed;assert telemetry.sample(store);value=reader.telemetry()
    value['workers']=[dict(execution_id='ref_'+'a'*64,process=dict(scope='SUPERVISOR_PROCESS',status='UNKNOWN',cpu_seconds=None,rss_bytes=None),
                          heartbeat=dict(status='FRESH',counter=2,age_seconds=1))]
    parsed=json.loads(aged_sample(value,20).split(b'data: ')[1])
    assert parsed['sample_age_seconds']>=20 and parsed['workers'][0]['heartbeat']['status']=='STALE'
    assert parsed['workers'][0]['heartbeat']['age_seconds']==21


def test_optional_send_serialization_failure_keeps_following_domain(observed,monkeypatch):
    from rlflow import live_stream
    from rlflow.hybrid_protocol import ProtocolError
    store,reader=observed;assert telemetry.sample(store);value=reader.telemetry();failed=threading.Event()
    def broken(*args):failed.set();raise ProtocolError('private injected exception')
    monkeypatch.setattr(live_stream,'aged_sample',broken)
    class Samples(Reader):
        def telemetry(self):return copy.deepcopy(value)
        def events(self,cursor,*,limit):return super().events(cursor,limit=limit) if failed.is_set() else []
    body=asyncio.run(stream(Samples(1)))
    assert failed.is_set() and b'event: domain' in body and b'event: heartbeat' in body
    assert b'event: telemetry' not in body and b'private injected' not in body and b'resync_required' not in body


def test_delayed_optional_frame_behind_domain_is_stale_at_actual_send(observed,monkeypatch):
    from rlflow import live_stream
    store,reader=observed;assert telemetry.sample(store);value=reader.telemetry()
    value['workers']=[dict(execution_id='ref_'+'a'*64,process=dict(scope='SUPERVISOR_PROCESS',status='UNKNOWN',cpu_seconds=None,rss_bytes=None),
                          heartbeat=dict(status='FRESH',counter=2,age_seconds=1))]
    offset=[0];read=threading.Event()
    monkeypatch.setattr(live_stream,'time',SimpleNamespace(monotonic=lambda:real_time.monotonic()+offset[0]))
    class Samples(Reader):
        def telemetry(self):read.set();return copy.deepcopy(value)
    async def run():
        ended=asyncio.Event();messages=[]
        async def receive():await ended.wait();return {'type':'http.disconnect'}
        async def send(message):
            if message['type']=='http.response.start':
                while not read.is_set():await asyncio.sleep(.001)
                await asyncio.sleep(.01);offset[0]=20
            messages.append(message)
            if b'event: telemetry' in message.get('body',b''):ended.set()
        await asyncio.wait_for(LiveStream(Samples(1),'store_test:0',lambda:True,lambda:None,heartbeat=100,poll=.01,telemetry_interval=.1)({},receive,send),2)
        return b''.join(m.get('body',b'') for m in messages)
    body=asyncio.run(run());assert body.index(b'event: domain')<body.index(b'event: telemetry')
    parsed=json.loads(body.split(b'event: telemetry\ndata: ')[1].split(b'\n')[0])
    assert parsed['sample_age_seconds']>=20 and parsed['workers'][0]['heartbeat']['status']=='STALE'
